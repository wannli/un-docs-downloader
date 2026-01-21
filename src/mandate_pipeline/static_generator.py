"""Static site generator for Mandate Pipeline."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .checks import load_checks, run_checks
from .extractor import extract_text, extract_operative_paragraphs
from .pipeline import load_patterns


def get_un_document_url(symbol: str) -> str:
    """
    Generate UN ODS URL for a document symbol.

    Args:
        symbol: Document symbol (e.g., "A/80/L.1")

    Returns:
        URL to view the document on UN ODS
    """
    # Use the new docs.un.org format with direct PDF link
    # e.g., A/RES/80/233 -> https://docs.un.org/en/a/res/80/233?direct=true
    symbol_lower = symbol.lower()
    return f"https://docs.un.org/en/{symbol_lower}?direct=true"


def symbol_to_filename(symbol: str) -> str:
    """Convert a UN symbol to a safe filename."""
    # Replace / with _ but preserve dots
    return symbol.replace("/", "_")


def filename_to_symbol(filename: str) -> str:
    """Convert a filename back to UN symbol.
    
    Handles patterns like:
    - A_80_L.1.pdf -> A/80/L.1
    - A_RES_77_1.pdf -> A/RES/77/1
    """
    # Remove .pdf extension
    stem = filename.replace(".pdf", "")
    
    # The tricky part: we need to know which underscores were slashes
    # UN symbols have patterns like A/80/L.1, A/RES/77/1, A/C.1/80/L.1
    # The key insight: dots in symbols come BEFORE numbers (L.1, C.1)
    # So we can't just replace all underscores with slashes
    
    # Strategy: replace underscores with slashes, but handle L.X and C.X patterns
    # First, replace all underscores
    symbol = stem.replace("_", "/")
    
    return symbol


def load_all_documents(data_dir: Path, checks: list) -> list[dict]:
    """
    Load all documents from the data directory.

    Scans all PDFs, extracts text, runs checks, and returns metadata.

    Args:
        data_dir: Path to data directory (contains pdfs/ subdirectory)
        checks: List of check definitions

    Returns:
        List of document dicts with metadata, paragraphs, and signals
    """
    documents = []
    pdfs_dir = data_dir / "pdfs"

    if not pdfs_dir.exists():
        return documents

    for pdf_file in pdfs_dir.glob("*.pdf"):
        # Extract symbol from filename
        symbol = filename_to_symbol(pdf_file.stem)

        try:
            # Extract text and paragraphs
            text = extract_text(pdf_file)
            paragraphs = extract_operative_paragraphs(text)

            # Run checks
            signals = run_checks(paragraphs, checks) if checks else {}

            # Build signal summary
            signal_summary = {}
            for para_signals in signals.values():
                for sig in para_signals:
                    signal_summary[sig] = signal_summary.get(sig, 0) + 1

            documents.append({
                "symbol": symbol,
                "filename": pdf_file.name,
                "paragraphs": paragraphs,
                "signals": signals,
                "signal_summary": signal_summary,
                "num_paragraphs": len(paragraphs),
                "un_url": get_un_document_url(symbol),
            })

        except Exception as e:
            print(f"Error processing {pdf_file}: {e}")
            continue

    # Sort by symbol
    def sort_key(doc):
        numbers = re.findall(r'\d+', doc["symbol"])
        return [int(n) for n in numbers] if numbers else [0]

    documents.sort(key=sort_key)

    return documents


def generate_data_json(documents: list, checks: list, output_dir: Path) -> None:
    """
    Generate data.json with all document metadata.

    Args:
        documents: List of document dicts
        checks: List of check definitions
        output_dir: Output directory for the static site
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Calculate aggregate stats
    total_signal_counts = {}
    for doc in documents:
        for sig, count in doc.get("signal_summary", {}).items():
            total_signal_counts[sig] = total_signal_counts.get(sig, 0) + count

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "documents": documents,
        "stats": {
            "total_documents": len(documents),
            "documents_with_signals": len([d for d in documents if d.get("signals")]),
            "signal_counts": total_signal_counts,
        },
    }

    with open(output_dir / "data.json", "w") as f:
        json.dump(data, f, indent=2)


def generate_search_index(documents: list, output_dir: Path) -> None:
    """
    Generate search index for Lunr.js client-side search.

    Args:
        documents: List of document dicts
        output_dir: Output directory for the static site
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build search documents - flatten paragraphs into searchable content
    search_docs = []
    for doc in documents:
        # Combine all paragraph text
        content = " ".join(doc.get("paragraphs", {}).values())

        # Get signal names
        signals = list(doc.get("signal_summary", {}).keys())

        search_docs.append({
            "symbol": doc["symbol"],
            "filename": symbol_to_filename(doc["symbol"]) + ".html",
            "content": content,
            "signals": signals,
            "num_paragraphs": doc.get("num_paragraphs", 0),
        })

    index_data = {
        "documents": search_docs,
    }

    with open(output_dir / "search-index.json", "w") as f:
        json.dump(index_data, f)


def get_templates_env() -> Environment:
    """Get Jinja2 environment for static templates."""
    templates_dir = Path(__file__).parent / "templates" / "static"
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=True,
    )


def generate_document_page(doc: dict, checks: list, output_dir: Path) -> None:
    """
    Generate individual document HTML page.

    Args:
        doc: Document dict with metadata
        checks: List of check definitions
        output_dir: Output directory (documents/ subdirectory)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = get_templates_env()
    template = env.get_template("document_detail.html")

    # Build paragraph data
    paragraph_data = []
    paragraphs = doc.get("paragraphs", {})
    signals = doc.get("signals", {})

    for num in sorted(paragraphs.keys()):
        paragraph_data.append({
            "number": num,
            "text": paragraphs[num],
            "signals": signals.get(num, []),
        })

    html = template.render(
        doc=doc,
        symbol=doc["symbol"],
        paragraphs=paragraph_data,
        checks=checks,
        un_url=doc.get("un_url", get_un_document_url(doc["symbol"])),
    )

    filename = symbol_to_filename(doc["symbol"]) + ".html"
    with open(output_dir / filename, "w") as f:
        f.write(html)


def generate_signal_page(documents: list, check: dict, output_dir: Path) -> None:
    """
    Generate signal-filtered HTML page.

    Args:
        documents: All documents
        check: Check definition for this signal
        output_dir: Output directory (signals/ subdirectory)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = get_templates_env()
    template = env.get_template("signal.html")

    signal = check["signal"]

    # Filter documents that have this signal
    filtered_docs = []
    for doc in documents:
        if signal in doc.get("signal_summary", {}):
            # Get paragraphs with this signal
            signal_paras = []
            for para_num, para_signals in doc.get("signals", {}).items():
                if signal in para_signals:
                    signal_paras.append({
                        "num": para_num,
                        "text": doc.get("paragraphs", {}).get(para_num, ""),
                    })

            filtered_docs.append({
                **doc,
                "signal_paragraphs": signal_paras,
            })

    html = template.render(
        check=check,
        signal=signal,
        documents=filtered_docs,
        total_docs=len(filtered_docs),
    )

    # Use check signal as filename (slug)
    filename = check["signal"].lower().replace(" ", "-") + ".html"
    with open(output_dir / filename, "w") as f:
        f.write(html)


def symbol_matches_pattern(symbol: str, pattern: dict) -> bool:
    """
    Check if a document symbol matches a pattern template.

    Args:
        symbol: Document symbol (e.g., "A/RES/80/1")
        pattern: Pattern definition with template and variable values

    Returns:
        True if symbol matches the pattern
    """
    template = pattern.get("template", "")
    
    # Convert template to regex pattern
    # For variables with specific values in the pattern, use those values
    # For {number}, always use \d+ since it varies
    regex_pattern = template
    
    # Replace {number} with \d+ (always variable)
    regex_pattern = regex_pattern.replace("{number}", r"\d+")
    
    # Replace other placeholders with their actual values or \d+
    for key in ["session", "committee"]:
        placeholder = "{" + key + "}"
        if placeholder in regex_pattern:
            value = pattern.get(key)
            if value is not None:
                # Use the specific value from the pattern
                regex_pattern = regex_pattern.replace(placeholder, str(value))
            else:
                # No specific value, match any digits
                regex_pattern = regex_pattern.replace(placeholder, r"\d+")
    
    regex_pattern = "^" + regex_pattern + "$"
    
    return bool(re.match(regex_pattern, symbol))


def group_documents_by_pattern(documents: list, patterns: list) -> dict:
    """
    Group documents by matching pattern.

    Args:
        documents: List of document dicts
        patterns: List of pattern definitions

    Returns:
        Dict mapping pattern names to lists of documents
    """
    documents_by_pattern = {p["name"]: [] for p in patterns}
    documents_by_pattern["Other"] = []
    
    for doc in documents:
        symbol = doc.get("symbol", "")
        matched = False
        for pattern in patterns:
            if symbol_matches_pattern(symbol, pattern):
                documents_by_pattern[pattern["name"]].append(doc)
                matched = True
                break
        if not matched:
            documents_by_pattern["Other"].append(doc)
    
    # Remove empty "Other" category
    if not documents_by_pattern["Other"]:
        del documents_by_pattern["Other"]
    
    return documents_by_pattern


def natural_sort_key(symbol: str) -> list:
    """
    Generate a sort key for natural sorting of document symbols.
    
    This ensures A/80/L.9 comes before A/80/L.10.
    """
    import re
    parts = re.split(r'(\d+)', symbol)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def generate_documents_list_page(documents: list, checks: list, patterns: list, output_dir: Path) -> None:
    """
    Generate documents list page (documents/index.html).

    Args:
        documents: All documents
        checks: All check definitions
        patterns: All pattern definitions
        output_dir: Output directory (documents/ subdirectory)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = get_templates_env()
    template = env.get_template("documents.html")

    # Calculate stats
    total_signal_counts = {}
    for doc in documents:
        for sig, count in doc.get("signal_summary", {}).items():
            total_signal_counts[sig] = total_signal_counts.get(sig, 0) + count

    # Group documents by pattern and sort naturally within each group
    docs_by_pattern = group_documents_by_pattern(documents, patterns)
    
    # Sort documents within each pattern group using natural sort
    for pattern_name in docs_by_pattern:
        docs_by_pattern[pattern_name].sort(key=lambda d: natural_sort_key(d["symbol"]))

    html = template.render(
        documents=documents,
        checks=checks,
        patterns=patterns,
        docs_by_pattern=docs_by_pattern,
        total_docs=len(documents),
        docs_with_signals=len([d for d in documents if d.get("signals")]),
        total_signal_counts=total_signal_counts,
    )

    with open(output_dir / "index.html", "w") as f:
        f.write(html)


def compute_matrix(documents: list, patterns: list, checks: list) -> dict:
    """
    Compute the pattern × signal matrix.

    Args:
        documents: All documents
        patterns: Pattern definitions
        checks: Check definitions

    Returns:
        Dict mapping pattern_name -> {signal_name: count}
    """
    # Group documents by pattern
    docs_by_pattern = group_documents_by_pattern(documents, patterns)
    
    matrix = {}
    for pattern in patterns:
        pattern_name = pattern["name"]
        pattern_docs = docs_by_pattern.get(pattern_name, [])
        
        matrix[pattern_name] = {}
        for check in checks:
            signal = check["signal"]
            count = 0
            for doc in pattern_docs:
                if signal in doc.get("signal_summary", {}):
                    count += doc["signal_summary"][signal]
            matrix[pattern_name][signal] = count
    
    return matrix


def compute_pattern_doc_counts(documents: list, patterns: list) -> dict:
    """
    Compute document counts per pattern.

    Args:
        documents: All documents
        patterns: Pattern definitions

    Returns:
        Dict mapping pattern_name -> doc count
    """
    docs_by_pattern = group_documents_by_pattern(documents, patterns)
    
    counts = {}
    for pattern in patterns:
        pattern_name = pattern["name"]
        counts[pattern_name] = len(docs_by_pattern.get(pattern_name, []))
    
    return counts


def generate_pattern_page(documents: list, pattern: dict, checks: list, patterns: list, output_dir: Path) -> None:
    """
    Generate individual pattern page.

    Args:
        documents: All documents
        pattern: Pattern definition
        checks: All check definitions
        patterns: All pattern definitions (for grouping)
        output_dir: Output directory (patterns/ subdirectory)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = get_templates_env()
    template = env.get_template("pattern.html")

    pattern_name = pattern["name"]
    docs_by_pattern = group_documents_by_pattern(documents, patterns)
    pattern_docs = docs_by_pattern.get(pattern_name, [])

    # Calculate signal counts for this pattern
    pattern_signal_counts = {}
    for doc in pattern_docs:
        for sig, count in doc.get("signal_summary", {}).items():
            pattern_signal_counts[sig] = pattern_signal_counts.get(sig, 0) + count

    html = template.render(
        pattern=pattern,
        documents=pattern_docs,
        checks=checks,
        pattern_signal_counts=pattern_signal_counts,
        total_docs=len(pattern_docs),
    )

    # Create slug from pattern name
    slug = pattern_name.lower().replace(" ", "_").replace(".", "").replace("(", "").replace(")", "")
    with open(output_dir / f"{slug}.html", "w") as f:
        f.write(html)


def get_pattern_slug(pattern_name: str) -> str:
    """Convert pattern name to URL slug."""
    return pattern_name.lower().replace(" ", "_").replace(".", "").replace("(", "").replace(")", "")


def get_signal_slug(signal: str) -> str:
    """Convert signal name to URL slug."""
    return signal.lower().replace(" ", "-")


def generate_pattern_signal_page(
    documents: list,
    pattern: dict,
    signal: str,
    patterns: list,
    output_dir: Path
) -> None:
    """
    Generate page showing documents with a specific signal in a specific pattern.

    Args:
        documents: All documents
        pattern: Pattern definition
        signal: Signal name to filter by
        patterns: All pattern definitions (for grouping)
        output_dir: Output directory (matrix/ subdirectory)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = get_templates_env()
    template = env.get_template("pattern_signal.html")

    pattern_name = pattern["name"]
    pattern_slug = get_pattern_slug(pattern_name)
    signal_slug = get_signal_slug(signal)

    # Get documents matching this pattern that have this signal
    docs_by_pattern = group_documents_by_pattern(documents, patterns)
    pattern_docs = docs_by_pattern.get(pattern_name, [])
    
    # Filter to only docs with this signal
    filtered_docs = [
        doc for doc in pattern_docs
        if signal in doc.get("signal_summary", {})
    ]
    
    # Sort by signal count descending
    filtered_docs.sort(key=lambda d: d.get("signal_summary", {}).get(signal, 0), reverse=True)

    html = template.render(
        pattern=pattern,
        pattern_slug=pattern_slug,
        signal=signal,
        documents=filtered_docs,
    )

    filename = f"{pattern_slug}_{signal_slug}.html"
    with open(output_dir / filename, "w") as f:
        f.write(html)


def generate_index_page(documents: list, checks: list, patterns: list, output_dir: Path) -> None:
    """
    Generate main index/dashboard page.

    Args:
        documents: All documents
        checks: All check definitions
        patterns: All pattern definitions
        output_dir: Root output directory
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = get_templates_env()
    template = env.get_template("index.html")

    # Calculate stats
    total_signal_counts = {}
    for doc in documents:
        for sig, count in doc.get("signal_summary", {}).items():
            total_signal_counts[sig] = total_signal_counts.get(sig, 0) + count

    # Compute matrix data
    matrix = compute_matrix(documents, patterns, checks)
    pattern_doc_counts = compute_pattern_doc_counts(documents, patterns)

    html = template.render(
        documents=documents,
        checks=checks,
        patterns=patterns,
        matrix=matrix,
        pattern_doc_counts=pattern_doc_counts,
        total_docs=len(documents),
        docs_with_signals=len([d for d in documents if d.get("signals")]),
        total_signal_counts=total_signal_counts,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    with open(output_dir / "index.html", "w") as f:
        f.write(html)


def generate_site(config_dir: Path, data_dir: Path, output_dir: Path) -> None:
    """
    Generate the complete static site.

    Args:
        config_dir: Directory containing checks.yaml and patterns.yaml
        data_dir: Directory containing pdfs/ subdirectory
        output_dir: Output directory for static site
    """
    config_dir = Path(config_dir)
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)

    # Load config
    checks = load_checks(config_dir / "checks.yaml")
    patterns = load_patterns(config_dir / "patterns.yaml")

    # Load all documents
    documents = load_all_documents(data_dir, checks)

    # Create output directories
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "documents").mkdir(exist_ok=True)
    (output_dir / "signals").mkdir(exist_ok=True)
    (output_dir / "patterns").mkdir(exist_ok=True)
    (output_dir / "matrix").mkdir(exist_ok=True)

    # Generate pages
    generate_index_page(documents, checks, patterns, output_dir)
    generate_documents_list_page(documents, checks, patterns, output_dir / "documents")

    for doc in documents:
        generate_document_page(doc, checks, output_dir / "documents")

    for check in checks:
        generate_signal_page(documents, check, output_dir / "signals")

    for pattern in patterns:
        generate_pattern_page(documents, pattern, checks, patterns, output_dir / "patterns")
        # Generate pattern+signal pages
        for check in checks:
            generate_pattern_signal_page(documents, pattern, check["signal"], patterns, output_dir / "matrix")

    # Generate data exports
    generate_data_json(documents, checks, output_dir)
    generate_search_index(documents, output_dir)

    print(f"Generated static site with {len(documents)} documents in {output_dir}")


def generate_site_verbose(
    config_dir: Path,
    data_dir: Path,
    output_dir: Path,
    on_load_start: callable = None,
    on_load_document: callable = None,
    on_load_error: callable = None,
    on_load_end: callable = None,
    on_generate_start: callable = None,
    on_generate_page: callable = None,
    on_generate_end: callable = None,
) -> dict:
    """
    Generate the complete static site with verbose callbacks.

    Args:
        config_dir: Directory containing checks.yaml and patterns.yaml
        data_dir: Directory containing pdfs/ subdirectory
        output_dir: Output directory for static site
        on_load_start: Callback() when starting to load documents
        on_load_document: Callback(symbol, num_paragraphs, signals, duration) for each doc
        on_load_error: Callback(path, error) for load errors
        on_load_end: Callback(total, duration) when done loading
        on_generate_start: Callback() when starting to generate pages
        on_generate_page: Callback(page_type, name) for each page
        on_generate_end: Callback(duration) when done generating

    Returns:
        Dict with stats: total_documents, documents_with_signals, signal_counts, etc.
    """
    import time

    config_dir = Path(config_dir)
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)

    # Load config
    checks = load_checks(config_dir / "checks.yaml")
    patterns = load_patterns(config_dir / "patterns.yaml")

    # Load all documents with callbacks
    if on_load_start:
        on_load_start()

    load_start_time = time.time()
    documents = []
    pdfs_dir = data_dir / "pdfs"

    if pdfs_dir.exists():
        for pdf_file in pdfs_dir.glob("*.pdf"):
            doc_start_time = time.time()
            symbol = filename_to_symbol(pdf_file.stem)

            try:
                text = extract_text(pdf_file)
                paragraphs = extract_operative_paragraphs(text)
                signals = run_checks(paragraphs, checks) if checks else {}

                # Build signal summary
                signal_summary = {}
                for para_signals in signals.values():
                    for sig in para_signals:
                        signal_summary[sig] = signal_summary.get(sig, 0) + 1

                doc = {
                    "symbol": symbol,
                    "filename": pdf_file.name,
                    "paragraphs": paragraphs,
                    "signals": signals,
                    "signal_summary": signal_summary,
                    "num_paragraphs": len(paragraphs),
                    "un_url": get_un_document_url(symbol),
                }
                documents.append(doc)

                doc_duration = time.time() - doc_start_time
                if on_load_document:
                    on_load_document(symbol, len(paragraphs), signal_summary, doc_duration)

            except Exception as e:
                if on_load_error:
                    on_load_error(str(pdf_file), str(e))

    # Sort documents
    def sort_key(doc):
        numbers = re.findall(r'\d+', doc["symbol"])
        return [int(n) for n in numbers] if numbers else [0]
    documents.sort(key=sort_key)

    load_duration = time.time() - load_start_time
    if on_load_end:
        on_load_end(len(documents), load_duration)

    # Generate pages
    if on_generate_start:
        on_generate_start()

    generate_start_time = time.time()

    # Create output directories
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "documents").mkdir(exist_ok=True)
    (output_dir / "signals").mkdir(exist_ok=True)
    (output_dir / "patterns").mkdir(exist_ok=True)
    (output_dir / "matrix").mkdir(exist_ok=True)

    # Generate pages
    generate_index_page(documents, checks, patterns, output_dir)
    if on_generate_page:
        on_generate_page("index", "index.html")

    generate_documents_list_page(documents, checks, patterns, output_dir / "documents")
    if on_generate_page:
        on_generate_page("documents_list", "documents/index.html")

    for doc in documents:
        generate_document_page(doc, checks, output_dir / "documents")
        if on_generate_page:
            on_generate_page("document", f"documents/{symbol_to_filename(doc['symbol'])}.html")

    for check in checks:
        generate_signal_page(documents, check, output_dir / "signals")
        if on_generate_page:
            on_generate_page("signal", f"signals/{check['signal'].lower().replace(' ', '-')}.html")

    for pattern in patterns:
        generate_pattern_page(documents, pattern, checks, patterns, output_dir / "patterns")
        pattern_slug = get_pattern_slug(pattern["name"])
        if on_generate_page:
            on_generate_page("pattern", f"patterns/{pattern_slug}.html")
        # Generate pattern+signal pages
        for check in checks:
            generate_pattern_signal_page(documents, pattern, check["signal"], patterns, output_dir / "matrix")
            signal_slug = get_signal_slug(check["signal"])
            if on_generate_page:
                on_generate_page("matrix", f"matrix/{pattern_slug}_{signal_slug}.html")

    # Generate data exports
    generate_data_json(documents, checks, output_dir)
    if on_generate_page:
        on_generate_page("data", "data.json")

    generate_search_index(documents, output_dir)
    if on_generate_page:
        on_generate_page("search", "search-index.json")

    generate_duration = time.time() - generate_start_time
    if on_generate_end:
        on_generate_end(generate_duration)

    # Calculate stats
    total_signal_counts = {}
    for doc in documents:
        for sig, count in doc.get("signal_summary", {}).items():
            total_signal_counts[sig] = total_signal_counts.get(sig, 0) + count

    return {
        "total_documents": len(documents),
        "documents_with_signals": len([d for d in documents if d.get("signals")]),
        "document_pages": len(documents),
        "signal_pages": len(checks),
        "signal_counts": total_signal_counts,
    }
