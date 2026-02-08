"""Static site generator for Mandate Pipeline."""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

# Module-level logger
logger = logging.getLogger(__name__)


def safe_paragraph_number(para: dict, default: int = 0) -> int:
    """
    Safely extract and convert paragraph number to int for sorting.

    Args:
        para: Paragraph dict with 'number' key
        default: Default value if conversion fails

    Returns:
        Integer paragraph number, or default if conversion fails
    """
    try:
        num = para.get("number", default)
        return int(num)
    except (TypeError, ValueError) as e:
        logger.warning(f"Invalid paragraph number '{para.get('number')}': {e}")
        return default

from .detection import load_checks, run_checks

from .extractor import (
    extract_text,
    extract_operative_paragraphs,
    extract_lettered_paragraphs,
    extract_amendment_text,
    extract_title,
    extract_agenda_items,
    find_symbol_references,
)
from .linking import (
    link_documents,
    annotate_linkage,
    is_resolution,
    is_proposal,
    symbol_to_filename,
    derive_resolution_origin,
    derive_origin_from_symbol,
    normalize_title,
    get_linking_audit,
    get_undl_cache_stats,
    COMMITTEE_NAMES,
)
from .igov import load_igov_decisions, load_igov_decisions_all


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


def derive_session_from_symbol(symbol: str) -> str | None:
    """Derive the UN General Assembly session from a document symbol."""
    if not symbol:
        return None

    res_match = re.match(r"^A/RES/(\d+)", symbol)
    if res_match:
        return res_match.group(1)

    committee_match = re.match(r"^A/C\.\d+/(\d+)/L\.", symbol)
    if committee_match:
        return committee_match.group(1)

    plenary_match = re.match(r"^A/(\d+)/L\.", symbol)
    if plenary_match:
        return plenary_match.group(1)

    return None


def ensure_document_sessions(documents: list[dict]) -> None:
    """Ensure documents include a session derived from their symbols."""
    for doc in documents:
        if doc.get("session"):
            continue
        derived_session = derive_session_from_symbol(doc.get("symbol", ""))
        if derived_session:
            doc["session"] = derived_session


def classify_doc_type(symbol: str, text: str) -> str:
    """Classify document type for linking metadata."""
    if is_resolution(symbol):
        return "resolution"
    if is_proposal(symbol):
        front_matter = "\n".join(text.splitlines()[:50])
        if "/Rev." in symbol or re.search(r"\bamendment\b", front_matter, re.IGNORECASE):
            return "amendment"
        return "proposal"
    return "other"


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
            title = extract_title(text)
            agenda_items = extract_agenda_items(text)
            symbol_references = find_symbol_references(text)
            doc_type = classify_doc_type(symbol, text)

            # For amendments without numbered paragraphs, try alternative extraction
            if doc_type == "amendment" and not paragraphs:
                # Try lettered paragraphs first
                lettered = extract_lettered_paragraphs(text)
                if lettered:
                    # Convert letter keys to numeric for consistency
                    paragraphs = {i + 1: v for i, (k, v) in enumerate(sorted(lettered.items()))}
                else:
                    # Fall back to body text extraction
                    paragraphs = extract_amendment_text(text)

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
                "doc_type": doc_type,
                "paragraphs": paragraphs,
                "title": title,
                "agenda_items": agenda_items,
                "symbol_references": symbol_references,
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


def generate_data_json(
    documents: list,
    checks: list,
    output_dir: Path,
    filename: str = "data.json",
) -> None:
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

    with open(output_dir / filename, "w") as f:
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


def highlight_signal_phrases(text: str, phrases: list[str]) -> str:
    """
    Highlight signal phrases in text with <mark> tags.

    Args:
        text: The paragraph text
        phrases: List of phrases to highlight

    Returns:
        Text with phrases wrapped in <mark> tags
    """
    from markupsafe import Markup, escape

    # Escape HTML in the original text first
    escaped_text = str(escape(text))

    # Sort phrases by length (longest first) to avoid partial replacements
    sorted_phrases = sorted(phrases, key=len, reverse=True)

    for phrase in sorted_phrases:
        # Case-insensitive replacement
        escaped_phrase = str(escape(phrase))
        pattern = re.compile(re.escape(escaped_phrase), re.IGNORECASE)
        escaped_text = pattern.sub(
            lambda m: f'<mark class="bg-yellow-200 px-0.5 rounded">{m.group(0)}</mark>',
            escaped_text
        )

    return Markup(escaped_text)


# Global variable to store checks for use in template filter
_template_checks = []


def get_templates_env(checks=None) -> Environment:
    """Get Jinja2 environment for static templates."""
    global _template_checks
    if checks is not None:
        _template_checks = checks

    templates_dir = Path(__file__).parent / "templates" / "static"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=True,
    )

    # Add custom filter for highlighting signal phrases
    def highlight_signals_filter(text, signals=None):
        """
        Jinja2 filter to highlight signal phrases in text.
        
        Args:
            text: The paragraph text
            signals: List of signal names that matched this paragraph
        
        Returns:
            Text with matched phrases highlighted
        """
        if not signals or not _template_checks:
            return text

        # Collect all phrases for the signals that matched
        phrases_to_highlight = []
        for check in _template_checks:
            if check.get("signal") in signals:
                phrases_to_highlight.extend(check.get("phrases", []))

        if not phrases_to_highlight:
            return text

        return highlight_signal_phrases(text, phrases_to_highlight)

    env.filters["highlight_signals"] = highlight_signals_filter

    return env






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


def unified_sort_key(doc: dict) -> tuple:
    """
    Sort key for unified signals browser.

    Order: Draft Proposals (L-series) → Committee Proposals (C-series) → Resolutions
    Within each group: Committee order (C1→C6) then natural numerical sorting
    """
    symbol = doc["symbol"]
    doc_type = doc.get("doc_type", "other")

    # Primary: Document type hierarchy
    type_hierarchy = {
        "proposal": 0,  # All proposals together
        "resolution": 1
    }
    type_priority = type_hierarchy.get(doc_type, 2)

    # Secondary: Within proposals, L-series before C-series
    if doc_type == "proposal":
        is_l_series = "/L." in symbol
        series_priority = 0 if is_l_series else 1  # L-series first

        # Tertiary: Committee order for C-series (or 0 for L-series)
        if is_l_series:
            committee_priority = 0
        else:
            committee_order = {"C1": 1, "C2": 2, "C3": 3, "C4": 4, "C5": 5, "C6": 6}
            committee_priority = committee_order.get(doc.get("origin", ""), 99)
    else:
        series_priority = 0  # Not applicable for resolutions
        committee_priority = 0  # Not applicable for resolutions

    # Quaternary: Natural numerical sorting
    natural_key = natural_sort_key(symbol)

    return (type_priority, series_priority, committee_priority, natural_key)




















def build_igov_decision_documents(decisions: list[dict], checks: list) -> list[dict]:
    """Normalize IGov decision data into the unified document shape."""
    decision_docs = []
    for decision in decisions:
        decision_text = (decision.get("decision_text") or "").strip()
        paragraphs = {1: decision_text} if decision_text else {}
        signals = run_checks(paragraphs, checks) if checks and paragraphs else {}

        signal_summary = {}
        signal_paragraphs = []
        for para_num, para_signals in signals.items():
            if not para_signals:
                continue
            signal_paragraphs.append({
                "number": para_num,
                "text": paragraphs.get(para_num, ""),
                "signals": para_signals,
            })
            for sig in para_signals:
                signal_summary[sig] = signal_summary.get(sig, 0) + 1

        decision_number = str(decision.get("decision_number") or "").strip()
        session = decision.get("session")
        
        # Format symbol as A/DEC/{session}/{number} to align with A/RES format
        if decision_number and session:
            # Extract the number part: "80/518" -> "518", or use entire string if no slash
            if '/' in decision_number:
                number_part = decision_number.split('/', 1)[1]  # Take part after first slash
            else:
                # No slash present, use entire decision_number as-is
                number_part = decision_number
            symbol = f"A/DEC/{session}/{number_part}"
        elif decision_number:
            symbol = decision_number
        else:
            symbol = str(decision.get("title") or "").strip() or "Decision"

        decision_docs.append({
            **decision,
            "symbol": symbol,
            "doc_type": "decision",
            "source": "igov",
            "origin": "IGov",
            "paragraphs": paragraphs,
            "signals": signals,
            "signal_summary": signal_summary,
            "signal_paragraphs": signal_paragraphs,
        })

    return decision_docs


def generate_unified_explorer_page(
    documents: list[dict],
    checks: list,
    output_dir: Path
) -> None:
    """
    Generate the unified signals explorer page with proper UN document sorting.

    Args:
        documents: All processed documents
        checks: All check definitions
        output_dir: Root output directory
    """
    # Use module-level logger and time imports
    start_time = time.time()
    logger.info(f"Starting unified explorer generation for {len(documents)} documents")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Template preparation
    template_start = time.time()
    env = get_templates_env(checks)
    template = env.get_template("signals_unified_explorer.html")
    template_prep_time = time.time() - template_start
    logger.info(f"Template preparation in {template_prep_time:.2f}s")

    # Template rendering
    render_start = time.time()
    html = template.render(
        checks=checks,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    render_time = time.time() - render_start
    logger.info(f"Template rendering in {render_time:.2f}s, HTML size: {len(html)} characters")

    # File writing
    write_start = time.time()
    with open(output_dir / "index.html", "w") as f:
        f.write(html)
    write_time = time.time() - write_start
    logger.info(f"File writing in {write_time:.2f}s")

    total_time = time.time() - start_time
    logger.info(f"Unified explorer generation completed in {total_time:.2f}s")






def generate_signals_info_page(
    checks: list,
    output_dir: Path
) -> None:
    """
    Generate the signals info page explaining what signals are and how they're configured.

    Args:
        checks: All check definitions
        output_dir: Root output directory
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = get_templates_env(checks)
    template = env.get_template("signals_info.html")

    # Define signal colors for consistency
    signal_colors = {
        "agenda": {"bg": "bg-blue-50", "text": "text-blue-700", "border": "border-blue-200"},
        "PGA": {"bg": "bg-purple-50", "text": "text-purple-700", "border": "border-purple-200"},
        "process": {"bg": "bg-amber-50", "text": "text-amber-700", "border": "border-amber-200"},
        "report": {"bg": "bg-green-50", "text": "text-green-700", "border": "border-green-200"},
    }

    html = template.render(
        checks=checks,
        signal_colors=signal_colors,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    with open(output_dir / "signals-info.html", "w") as f:
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

    # Load all documents
    documents = load_all_documents(data_dir, checks)

    # Limit documents for faster testing if requested
    max_docs = os.getenv("MAX_DOCUMENTS")
    if max_docs and max_docs.isdigit():
        max_docs = int(max_docs)
        print(f"Limiting to {max_docs} documents for faster processing")
        documents = documents[:max_docs]

    # Skip UNDL metadata fetching for faster processing if requested
    use_undl_metadata = os.getenv("SKIP_UNDL_METADATA", "false").lower() != "true"
    link_documents(documents, use_undl_metadata=use_undl_metadata)
    annotate_linkage(documents)
    visible_documents = [doc for doc in documents if not doc.get("is_adopted_draft")]
    igov_decisions = build_igov_decision_documents(load_igov_decisions_all(data_dir), checks)
    browser_documents = visible_documents + igov_decisions
    ensure_document_sessions(browser_documents)

    # Create output directories
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate essential pages
    generate_signals_info_page(checks, output_dir)
    generate_unified_explorer_page(browser_documents, checks, output_dir)

    # Generate data exports
    generate_data_json(browser_documents, checks, output_dir)
    generate_search_index(browser_documents, output_dir)

    print(f"Generated static site with {len(browser_documents)} documents in {output_dir}")


def generate_site_verbose(
    config_dir: Path,
    data_dir: Path,
    output_dir: Path,
    skip_debug: bool = False,
    max_documents: Optional[int] = None,
    on_load_start=None,
    on_load_document=None,
    on_load_error=None,
    on_load_end=None,
    on_generate_start=None,
    on_generate_page=None,
    on_generate_end=None,
) -> dict:
    """
    Generate the complete static site with verbose callbacks.

    Args:
        config_dir: Directory containing checks.yaml and patterns.yaml
        data_dir: Directory containing pdfs/ subdirectory
        output_dir: Output directory for static site
        skip_debug: If True, skip generating debug pages (faster builds)
        max_documents: If set, limit processing to this many documents (for testing)
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
    from concurrent.futures import ThreadPoolExecutor, as_completed

    config_dir = Path(config_dir)
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)

    # Load config
    checks = load_checks(config_dir / "checks.yaml")

    # Load all documents with callbacks
    if on_load_start:
        on_load_start()

    load_start_time = time.time()
    documents = []
    pdfs_dir = data_dir / "pdfs"

    def process_pdf(pdf_file: Path) -> tuple:
        """Process a single PDF file and return (doc, error) tuple."""
        doc_start_time = time.time()
        symbol = filename_to_symbol(pdf_file.stem)

        try:
            text = extract_text(pdf_file)
            paragraphs = extract_operative_paragraphs(text)
            title = extract_title(text)
            agenda_items = extract_agenda_items(text)
            symbol_references = find_symbol_references(text)
            doc_type = classify_doc_type(symbol, text)

            # For amendments without numbered paragraphs, try alternative extraction
            if doc_type == "amendment" and not paragraphs:
                # Try lettered paragraphs first
                lettered = extract_lettered_paragraphs(text)
                if lettered:
                    # Convert letter keys to numeric for consistency
                    paragraphs = {i + 1: v for i, (k, v) in enumerate(sorted(lettered.items()))}
                else:
                    # Fall back to body text extraction
                    paragraphs = extract_amendment_text(text)

            signals = run_checks(paragraphs, checks) if checks else {}

            # Build signal summary
            signal_summary = {}
            for para_signals in signals.values():
                for sig in para_signals:
                    signal_summary[sig] = signal_summary.get(sig, 0) + 1

            doc = {
                "symbol": symbol,
                "filename": pdf_file.name,
                "doc_type": doc_type,
                "paragraphs": paragraphs,
                "title": title,
                "agenda_items": agenda_items,
                "symbol_references": symbol_references,
                "signals": signals,
                "signal_summary": signal_summary,
                "num_paragraphs": len(paragraphs),
                "un_url": get_un_document_url(symbol),
            }
            doc_duration = time.time() - doc_start_time
            return (doc, None, symbol, len(paragraphs), signal_summary, doc_duration)

        except Exception as e:
            return (None, str(e), str(pdf_file), 0, {}, 0)

    if pdfs_dir.exists():
        pdf_files = list(pdfs_dir.glob("*.pdf"))
        # Limit documents if max_documents is set (for testing/development)
        if max_documents and max_documents > 0:
            pdf_files = pdf_files[:max_documents]
        # Use ThreadPoolExecutor for parallel PDF extraction
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(process_pdf, pdf_file): pdf_file for pdf_file in pdf_files}
            for future in as_completed(futures):
                doc, error, identifier, num_paras, signal_summary, duration = future.result()
                if doc:
                    documents.append(doc)
                    if on_load_document:
                        on_load_document(identifier, num_paras, signal_summary, duration)
                elif error and on_load_error:
                    on_load_error(identifier, error)

    # Sort documents
    def sort_key(doc):
        numbers = re.findall(r'\d+', doc["symbol"])
        return [int(n) for n in numbers] if numbers else [0]
    documents.sort(key=sort_key)

    link_documents(documents)
    annotate_linkage(documents)
    visible_documents = [doc for doc in documents if not doc.get("is_adopted_draft")]
    igov_decisions = build_igov_decision_documents(load_igov_decisions_all(data_dir), checks)
    browser_documents = visible_documents + igov_decisions
    ensure_document_sessions(browser_documents)

    load_duration = time.time() - load_start_time
    if on_load_end:
        on_load_end(len(documents), load_duration)

    # Generate pages
    if on_generate_start:
        on_generate_start()

    generate_start_time = time.time()

    # Create output directories
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate pages
    generate_signals_info_page(checks, output_dir)
    if on_generate_page:
        on_generate_page("signals_info", "signals-info.html")

    generate_unified_explorer_page(browser_documents, checks, output_dir)
    if on_generate_page:
        on_generate_page("signals_unified_explorer", "index.html")

    # Generate data exports
    generate_data_json(browser_documents, checks, output_dir)
    if on_generate_page:
        on_generate_page("data", "data.json")

    generate_search_index(browser_documents, output_dir)
    if on_generate_page:
        on_generate_page("search", "search-index.json")

    generate_duration = time.time() - generate_start_time
    if on_generate_end:
        on_generate_end(generate_duration)

    # Calculate stats
    total_signal_counts = {}
    for doc in visible_documents:
        for sig, count in doc.get("signal_summary", {}).items():
            total_signal_counts[sig] = total_signal_counts.get(sig, 0) + count

    return {
        "total_documents": len(browser_documents),
        "documents_with_signals": len([d for d in browser_documents if d.get("signals")]),
        "document_pages": len(documents),
        "signal_pages": len(checks),
        "signal_counts": total_signal_counts,
    }


