"""Pipeline for discovering and processing UN documents."""

import json
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Iterator

import requests
import yaml

from .downloader import download_document


def load_patterns(config_path: Path) -> list[dict]:
    """
    Load symbol patterns from a YAML configuration file.

    Args:
        config_path: Path to the YAML config file

    Returns:
        List of pattern definitions
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    return config.get("patterns", [])


def generate_symbols(pattern: dict, count: int = None, start_override: int = None) -> Iterator[str]:
    """
    Generate document symbols from a pattern definition.

    For simple patterns: generates A/80/L.1, A/80/L.2, A/80/L.3...
    For patterns WITHOUT list variables.

    Args:
        pattern: Pattern definition with template and variables
        count: Maximum number of symbols to generate (None for infinite)
        start_override: Override the start number (used for resuming)

    Yields:
        Document symbols (e.g., "A/80/L.1", "A/RES/77/1")
    """
    template = pattern["template"]
    start = start_override if start_override is not None else pattern.get("start", 1)

    # Find list-valued variables (like committee: [1,2,3])
    list_vars = {}
    scalar_vars = {}

    for key, value in pattern.items():
        if key in ("name", "template", "start"):
            continue
        if isinstance(value, list):
            list_vars[key] = value
        else:
            scalar_vars[key] = value

    generated = 0
    number = start

    while count is None or generated < count:
        if list_vars:
            # Generate all combinations for this number
            # NOTE: This cycles through list vars for each number
            # For sequential processing by list var, use expand_pattern_by_list_vars
            keys = list(list_vars.keys())
            values = [list_vars[k] for k in keys]

            for combo in product(*values):
                if count is not None and generated >= count:
                    return

                vars_dict = dict(zip(keys, combo))
                vars_dict.update(scalar_vars)
                vars_dict["number"] = number

                yield template.format(**vars_dict)
                generated += 1
        else:
            # Simple case: just increment number
            vars_dict = scalar_vars.copy()
            vars_dict["number"] = number

            yield template.format(**vars_dict)
            generated += 1

        number += 1


def expand_pattern_by_list_vars(pattern: dict) -> list[dict]:
    """
    Expand a pattern with list variables into multiple simple patterns.
    
    For example, a pattern with committee: [1, 2, 3] becomes three patterns,
    one for each committee. This allows processing each committee sequentially
    (all docs for committee 1, then all docs for committee 2, etc.)
    
    Args:
        pattern: Pattern definition that may have list variables
        
    Returns:
        List of expanded patterns (each with scalar values only)
    """
    # Find list-valued variables
    list_vars = {}
    other_keys = {}
    
    for key, value in pattern.items():
        if key in ("name", "template", "start"):
            other_keys[key] = value
        elif isinstance(value, list):
            list_vars[key] = value
        else:
            other_keys[key] = value
    
    if not list_vars:
        # No list variables, return as-is
        return [pattern]
    
    # Generate all combinations of list variables
    expanded = []
    keys = list(list_vars.keys())
    values = [list_vars[k] for k in keys]
    
    for combo in product(*values):
        new_pattern = other_keys.copy()
        combo_dict = dict(zip(keys, combo))
        new_pattern.update(combo_dict)
        
        # Create a unique name for this sub-pattern
        combo_str = "_".join(f"{k}{v}" for k, v in combo_dict.items())
        base_name = pattern.get("name", "pattern")
        new_pattern["name"] = f"{base_name} ({combo_str})"
        new_pattern["_parent_name"] = base_name  # Track parent for state grouping
        new_pattern["_combo"] = combo_dict  # Track the combination
        
        expanded.append(new_pattern)
    
    return expanded


def document_exists(symbol: str) -> bool:
    """
    Check if a UN document exists.

    Args:
        symbol: Document symbol (e.g., "A/80/L.1")

    Returns:
        True if document exists, False otherwise
    """
    url = f"https://documents.un.org/api/symbol/access?s={symbol}&l=en&t=pdf"

    try:
        response = requests.head(url, allow_redirects=True, timeout=10)
        # 200 = found, 302 redirect to PDF = found
        # 404 or error page = not found
        if response.status_code == 200:
            content_type = response.headers.get("Content-Type", "")
            return "pdf" in content_type.lower()
        return False
    except requests.RequestException:
        return False


def discover_documents(
    pattern: dict,
    max_consecutive_misses: int = 3,
) -> Iterator[str]:
    """
    Discover available documents matching a pattern.

    Generates symbols and checks if they exist, stopping after
    N consecutive misses (indicating we've reached the end).

    Args:
        pattern: Pattern definition
        max_consecutive_misses: Stop after this many consecutive misses

    Yields:
        Symbols of documents that exist
    """
    consecutive_misses = 0

    for symbol in generate_symbols(pattern):
        if document_exists(symbol):
            consecutive_misses = 0
            yield symbol
        else:
            consecutive_misses += 1
            if consecutive_misses >= max_consecutive_misses:
                return


def load_sync_state(state_path: Path) -> dict:
    """
    Load sync state from JSON file.

    Args:
        state_path: Path to state.json file

    Returns:
        State dict with patterns info, or empty state if file doesn't exist
    """
    state_path = Path(state_path)

    if not state_path.exists():
        return {"patterns": {}}

    with open(state_path) as f:
        return json.load(f)


def save_sync_state(state_path: Path, state: dict) -> None:
    """
    Save sync state to JSON file.

    Args:
        state_path: Path to state.json file
        state: State dict to save
    """
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def get_start_number(pattern: dict, state: dict) -> int:
    """
    Get the starting number for a pattern based on sync state.

    Args:
        pattern: Pattern definition
        state: Current sync state

    Returns:
        Number to start checking from (highest_found + 1, or pattern start)
    """
    pattern_name = pattern["name"]
    pattern_state = state.get("patterns", {}).get(pattern_name, {})

    highest_found = pattern_state.get("highest_found")
    if highest_found is not None:
        return highest_found + 1

    return pattern.get("start", 1)


def sync_simple_pattern(
    pattern: dict,
    state: dict,
    data_dir: Path,
    output_dir: Path,
    max_consecutive_misses: int = 3,
) -> tuple[list[str], int]:
    """
    Sync documents for a simple pattern (no list variables).

    Args:
        pattern: Pattern definition (must not have list variables)
        state: Current sync state
        data_dir: Base data directory
        output_dir: Directory to store PDFs
        max_consecutive_misses: Stop after this many consecutive 404s

    Returns:
        Tuple of (list of newly downloaded symbols, new highest_found number)
    """
    pattern_name = pattern["name"]
    start_number = get_start_number(pattern, state)

    new_docs = []
    highest_found = state.get("patterns", {}).get(pattern_name, {}).get(
        "highest_found", pattern.get("start", 1) - 1
    )
    consecutive_misses = 0
    current_number = start_number

    for symbol in generate_symbols(pattern, start_override=start_number):
        if document_exists(symbol):
            consecutive_misses = 0
            download_document(symbol, output_dir=output_dir)
            new_docs.append(symbol)
            highest_found = current_number
        else:
            consecutive_misses += 1
            if consecutive_misses >= max_consecutive_misses:
                break

        current_number += 1

    return new_docs, highest_found


def sync_pattern(
    pattern: dict,
    state: dict,
    data_dir: Path,
    max_consecutive_misses: int = 3,
) -> tuple[list[str], int]:
    """
    Sync documents for a single pattern - discover and download new ones.
    
    For patterns with list variables (like committee: [1,2,3]), this expands
    them and processes each sub-pattern sequentially (all docs for committee 1,
    then all docs for committee 2, etc.)

    Args:
        pattern: Pattern definition
        state: Current sync state
        data_dir: Directory to store PDFs (data_dir/pdfs/{pattern_name}/)
        max_consecutive_misses: Stop after this many consecutive 404s

    Returns:
        Tuple of (list of newly downloaded symbols, new highest_found number)
    """
    # Get the parent pattern name for output directory
    parent_name = pattern.get("_parent_name", pattern["name"])
    
    # Create output directory using parent name
    output_dir = data_dir / "pdfs" / parent_name.replace(" ", "_")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Expand pattern if it has list variables
    expanded = expand_pattern_by_list_vars(pattern)
    
    all_new_docs = []
    last_highest = pattern.get("start", 1) - 1
    
    for sub_pattern in expanded:
        new_docs, highest = sync_simple_pattern(
            sub_pattern, state, data_dir, output_dir, max_consecutive_misses
        )
        all_new_docs.extend(new_docs)
        
        # Update state for this sub-pattern
        sub_name = sub_pattern["name"]
        if sub_name not in state["patterns"]:
            state["patterns"][sub_name] = {}
        state["patterns"][sub_name]["highest_found"] = highest
        
        last_highest = max(last_highest, highest)
    
    return all_new_docs, last_highest


def sync_all_patterns(
    config_dir: Path,
    data_dir: Path,
    max_consecutive_misses: int = 3,
) -> dict:
    """
    Sync all patterns defined in patterns.yaml.

    Args:
        config_dir: Directory containing patterns.yaml
        data_dir: Directory to store PDFs and state
        max_consecutive_misses: Stop after this many consecutive 404s per pattern

    Returns:
        Dict with sync results: {pattern_name: [new_symbols], ...}
    """
    patterns = load_patterns(config_dir / "patterns.yaml")
    state_path = data_dir / "state.json"
    state = load_sync_state(state_path)

    results = {}

    for pattern in patterns:
        new_docs, _ = sync_pattern(
            pattern, state, data_dir, max_consecutive_misses
        )
        results[pattern["name"]] = new_docs

    # Save updated state
    state["last_sync"] = datetime.now(timezone.utc).isoformat()
    save_sync_state(state_path, state)

    return results


def sync_all_patterns_verbose(
    config_dir: Path,
    data_dir: Path,
    max_consecutive_misses: int = 3,
    on_check: callable = None,
    on_download: callable = None,
    on_error: callable = None,
    on_pattern_start: callable = None,
    on_pattern_end: callable = None,
) -> dict:
    """
    Sync all patterns with verbose callbacks for logging.
    
    For patterns with list variables (like committee: [1,2,3]), this expands
    them and processes each sub-pattern sequentially (all docs for committee 1,
    then all docs for committee 2, etc.)

    Args:
        config_dir: Directory containing patterns.yaml
        data_dir: Directory to store PDFs and state
        max_consecutive_misses: Stop after this many consecutive 404s per pattern
        on_check: Callback(symbol, exists, consecutive_misses) for each check
        on_download: Callback(symbol, path, size, duration) for each download
        on_error: Callback(symbol, error) for download errors
        on_pattern_start: Callback(pattern_name, start_number) when starting a pattern
        on_pattern_end: Callback(pattern_name, new_count, duration) when done with pattern

    Returns:
        Dict with sync results: {pattern_name: [new_symbols], ...}
    """
    import time

    patterns = load_patterns(config_dir / "patterns.yaml")
    state_path = data_dir / "state.json"
    state = load_sync_state(state_path)

    results = {}

    for pattern in patterns:
        parent_name = pattern["name"]
        
        # Create output directory using parent pattern name
        output_dir = data_dir / "pdfs" / parent_name.replace(" ", "_")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Expand pattern if it has list variables
        expanded = expand_pattern_by_list_vars(pattern)
        
        all_new_docs = []
        parent_start_time = time.time()
        
        for sub_pattern in expanded:
            sub_name = sub_pattern["name"]
            start_number = get_start_number(sub_pattern, state)
            pattern_start_time = time.time()

            if on_pattern_start:
                on_pattern_start(sub_name, start_number)

            new_docs = []
            highest_found = state.get("patterns", {}).get(sub_name, {}).get(
                "highest_found", sub_pattern.get("start", 1) - 1
            )
            consecutive_misses = 0
            current_number = start_number

            for symbol in generate_symbols(sub_pattern, start_override=start_number):
                exists = document_exists(symbol)

                if exists:
                    consecutive_misses = 0

                    if on_check:
                        on_check(symbol, True, 0)

                    # Download the document
                    try:
                        download_start = time.time()
                        pdf_path = download_document(symbol, output_dir=output_dir)
                        download_duration = time.time() - download_start
                        file_size = pdf_path.stat().st_size

                        if on_download:
                            on_download(symbol, pdf_path, file_size, download_duration)

                        new_docs.append(symbol)
                        highest_found = current_number

                    except Exception as e:
                        if on_error:
                            on_error(symbol, str(e))
                else:
                    consecutive_misses += 1

                    if on_check:
                        on_check(symbol, False, consecutive_misses)

                    if consecutive_misses >= max_consecutive_misses:
                        break

                current_number += 1

            # Update state for this sub-pattern
            if sub_name not in state["patterns"]:
                state["patterns"][sub_name] = {}
            state["patterns"][sub_name]["highest_found"] = highest_found

            all_new_docs.extend(new_docs)

            pattern_duration = time.time() - pattern_start_time
            if on_pattern_end:
                on_pattern_end(sub_name, len(new_docs), pattern_duration)

        results[parent_name] = all_new_docs

    # Save updated state
    state["last_sync"] = datetime.now(timezone.utc).isoformat()
    save_sync_state(state_path, state)

    return results
