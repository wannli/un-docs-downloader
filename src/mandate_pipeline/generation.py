"""Static site generator for Mandate Pipeline."""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

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
from .discovery import load_patterns
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

    env = get_templates_env(checks)
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


def generate_signal_page(
    documents: list,
    visible_documents: list,
    check: dict,
    checks: list,
    output_dir: Path
) -> None:
    """
    Generate signal-filtered HTML page.

    Args:
        documents: All documents
        check: Check definition for this signal
        checks: All check definitions (for highlighting)
        output_dir: Output directory (signals/ subdirectory)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = get_templates_env(checks)
    template = env.get_template("signal.html")

    signal = check["signal"]

    # Filter documents that have this signal
    filtered_docs = []
    visible_filtered_docs = []
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

            enriched = {
                **doc,
                "signal_paragraphs": signal_paras,
            }
            filtered_docs.append(enriched)
            if not doc.get("is_adopted_draft"):
                visible_filtered_docs.append(enriched)

    html = template.render(
        check=check,
        signal=signal,
        documents=filtered_docs,
        total_docs=len(visible_filtered_docs),
        adopted_hidden_count=len(filtered_docs) - len(visible_filtered_docs),
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


def generate_documents_list_page(
    documents: list,
    visible_documents: list,
    checks: list,
    patterns: list,
    output_dir: Path
) -> None:
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
    for doc in visible_documents:
        for sig, count in doc.get("signal_summary", {}).items():
            total_signal_counts[sig] = total_signal_counts.get(sig, 0) + count

    # Group documents by pattern and sort naturally within each group
    docs_by_pattern = group_documents_by_pattern(documents, patterns)
    docs_by_pattern_visible = group_documents_by_pattern(visible_documents, patterns)
    
    # Sort documents within each pattern group using natural sort
    for pattern_name in docs_by_pattern:
        docs_by_pattern[pattern_name].sort(key=lambda d: natural_sort_key(d["symbol"]))
    for pattern_name in docs_by_pattern_visible:
        docs_by_pattern_visible[pattern_name].sort(key=lambda d: natural_sort_key(d["symbol"]))

    html = template.render(
        documents=documents,
        checks=checks,
        patterns=patterns,
        docs_by_pattern=docs_by_pattern,
        docs_by_pattern_visible=docs_by_pattern_visible,
        total_docs=len(visible_documents),
        visible_docs=len(visible_documents),
        adopted_hidden_count=len(documents) - len(visible_documents),
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


def generate_pattern_page(
    documents: list,
    visible_documents: list,
    pattern: dict,
    checks: list,
    patterns: list,
    output_dir: Path
) -> None:
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

    env = get_templates_env(checks)
    template = env.get_template("pattern.html")

    pattern_name = pattern["name"]
    docs_by_pattern = group_documents_by_pattern(documents, patterns)
    docs_by_pattern_visible = group_documents_by_pattern(visible_documents, patterns)
    pattern_docs = docs_by_pattern.get(pattern_name, [])
    pattern_docs_visible = docs_by_pattern_visible.get(pattern_name, [])

    # Calculate signal counts for this pattern
    pattern_signal_counts = {}
    for doc in pattern_docs_visible:
        for sig, count in doc.get("signal_summary", {}).items():
            pattern_signal_counts[sig] = pattern_signal_counts.get(sig, 0) + count

    # Add signal_paragraphs to each document
    enriched_docs = []
    for doc in pattern_docs:
        doc_copy = doc.copy()
        
        # Find all paragraphs that have any signal
        signal_paras = []
        for para_num, para_signals in doc.get("signals", {}).items():
            if para_signals:  # Has at least one signal
                para_text = doc.get("paragraphs", {}).get(para_num, "")
                signal_paras.append({
                    "number": para_num,
                    "text": para_text,
                    "signals": para_signals
                })
        
        # Sort paragraphs by number
        signal_paras.sort(key=lambda p: int(p["number"]))
        doc_copy["signal_paragraphs"] = signal_paras
        enriched_docs.append(doc_copy)
    
    # Sort documents naturally by symbol
    enriched_docs.sort(key=lambda d: natural_sort_key(d["symbol"]))

    # Create slug from pattern name
    pattern_slug = get_pattern_slug(pattern_name)

    html = template.render(
        pattern=pattern,
        pattern_slug=pattern_slug,
        documents=enriched_docs,
        checks=checks,
        pattern_signal_counts=pattern_signal_counts,
        total_docs=len(pattern_docs_visible),
        adopted_hidden_count=len(pattern_docs) - len(pattern_docs_visible),
    )
    with open(output_dir / f"{pattern_slug}.html", "w") as f:
        f.write(html)


def get_pattern_slug(pattern_name: str) -> str:
    """Convert pattern name to URL slug."""
    return pattern_name.lower().replace(" ", "_").replace(".", "").replace("(", "").replace(")", "")


def get_signal_slug(signal: str) -> str:
    """Convert signal name to URL slug."""
    return signal.lower().replace(" ", "-")


def generate_pattern_signal_page(
    documents: list,
    visible_documents: list,
    pattern: dict,
    signal: str,
    checks: list,
    patterns: list,
    output_dir: Path
) -> None:
    """
    Generate page showing documents with a specific signal in a specific pattern.

    Args:
        documents: All documents
        pattern: Pattern definition
        signal: Signal name to filter by
        checks: All check definitions (for highlighting)
        patterns: All pattern definitions (for grouping)
        output_dir: Output directory (matrix/ subdirectory)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = get_templates_env(checks)
    template = env.get_template("pattern_signal.html")

    pattern_name = pattern["name"]
    pattern_slug = get_pattern_slug(pattern_name)
    signal_slug = get_signal_slug(signal)

    # Get documents matching this pattern that have this signal
    docs_by_pattern = group_documents_by_pattern(documents, patterns)
    docs_by_pattern_visible = group_documents_by_pattern(visible_documents, patterns)
    pattern_docs = docs_by_pattern.get(pattern_name, [])
    pattern_docs_visible = docs_by_pattern_visible.get(pattern_name, [])
    
    # Filter to only docs with this signal and add signal_paragraphs
    filtered_docs = []
    total_paragraphs = 0
    visible_paragraphs = 0
    
    for doc in pattern_docs:
        if signal not in doc.get("signal_summary", {}):
            continue
        
        # Find paragraphs that have this signal
        signal_paras = []
        for para_num, para_signals in doc.get("signals", {}).items():
            if signal in para_signals:
                para_text = doc.get("paragraphs", {}).get(para_num, "")
                signal_paras.append({
                    "number": para_num,
                    "text": para_text
                })
        
        # Sort paragraphs by number
        signal_paras.sort(key=lambda p: int(p["number"]))
        
        # Add to filtered docs with signal_paragraphs
        doc_copy = doc.copy()
        doc_copy["signal_paragraphs"] = signal_paras
        filtered_docs.append(doc_copy)
        total_paragraphs += len(signal_paras)

        if not doc.get("is_adopted_draft"):
            visible_paragraphs += len(signal_paras)
    
    # Sort documents naturally by symbol
    filtered_docs.sort(key=lambda d: natural_sort_key(d["symbol"]))

    html = template.render(
        pattern=pattern,
        pattern_slug=pattern_slug,
        signal=signal,
        documents=filtered_docs,
        total_paragraphs=visible_paragraphs,
        total_docs=len([doc for doc in pattern_docs_visible if signal in doc.get("signal_summary", {})]),
        adopted_hidden_count=len([doc for doc in pattern_docs if signal in doc.get("signal_summary", {})]) - len([doc for doc in pattern_docs_visible if signal in doc.get("signal_summary", {})]),
    )

    filename = f"{pattern_slug}_{signal_slug}.html"
    with open(output_dir / filename, "w") as f:
        f.write(html)


def generate_index_page(documents: list, checks: list, patterns: list, output_dir: Path) -> None:
    """Deprecated: the signal browser is now the index page."""
    return


def generate_provenance_page(
    documents: list,
    checks: list,
    output_dir: Path
) -> None:
    """
    Generate the Resolution Provenance page showing resolutions grouped by origin committee.

    Args:
        documents: All documents
        checks: All check definitions
        output_dir: Output directory (provenance/ subdirectory)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = get_templates_env(checks)
    template = env.get_template("provenance.html")

    # Get linking audit data
    audit_data = get_linking_audit()

    # Group resolutions by origin
    resolutions = [doc for doc in documents if is_resolution(doc.get("symbol", ""))]
    origin_order = ["Plenary", "C1", "C2", "C3", "C4", "C5", "C6", "Unknown"]
    origins = {code: {"name": COMMITTEE_NAMES.get(code, code), "resolutions": []} for code in origin_order}

    linked_count = 0
    for res in resolutions:
        origin = derive_resolution_origin(res)
        res_data = {
            **res,
            "filename": symbol_to_filename(res["symbol"]) + ".html",
        }
        # Add linking method info from audit
        if res["symbol"] in audit_data:
            audit = audit_data[res["symbol"]]
            res_data["linking_method"] = audit.get("final_method")
            res_data["linking_confidence"] = audit.get("confidence")
        if res.get("linked_proposals"):
            linked_count += 1
        origins[origin]["resolutions"].append(res_data)

    # Sort resolutions within each origin
    for origin_data in origins.values():
        origin_data["resolutions"].sort(key=lambda r: natural_sort_key(r["symbol"]))

    # Coverage stats
    total_resolutions = len(resolutions)
    coverage = {
        "total": total_resolutions,
        "linked": linked_count,
        "unlinked": total_resolutions - linked_count,
        "percentage": round(linked_count / total_resolutions * 100, 1) if total_resolutions > 0 else 0,
    }

    html = template.render(
        origins=origins,
        coverage=coverage,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    with open(output_dir / "index.html", "w") as f:
        f.write(html)


def generate_origin_matrix_page(
    documents: list,
    checks: list,
    output_dir: Path
) -> None:
    """
    Generate the Origin × Signal matrix page.

    Args:
        documents: All documents
        checks: All check definitions
        output_dir: Root output directory
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = get_templates_env(checks)
    template = env.get_template("origin_matrix.html")

    # Get resolutions only
    resolutions = [doc for doc in documents if is_resolution(doc.get("symbol", ""))]

    # Build origin × signal matrix
    origin_order = ["Plenary", "C1", "C2", "C3", "C4", "C5", "C6", "Unknown"]
    origin_matrix = {code: {} for code in origin_order}
    origin_totals = {code: 0 for code in origin_order}
    signal_totals = {check["signal"]: 0 for check in checks}

    for res in resolutions:
        origin = derive_resolution_origin(res)
        for check in checks:
            signal = check["signal"]
            count = res.get("signal_summary", {}).get(signal, 0)
            origin_matrix[origin][signal] = origin_matrix[origin].get(signal, 0) + count
            if count > 0:
                signal_totals[signal] += count
                origin_totals[origin] += count

    grand_total = sum(origin_totals.values())

    # Top producers
    top_producers = sorted(
        [{"origin": code, "count": count} for code, count in origin_totals.items()],
        key=lambda x: x["count"],
        reverse=True
    )

    html = template.render(
        origin_matrix=origin_matrix,
        origin_order=origin_order,
        origin_names=COMMITTEE_NAMES,
        origin_totals=origin_totals,
        signal_totals=signal_totals,
        grand_total=grand_total,
        top_producers=top_producers,
        checks=checks,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    with open(output_dir / "origin_matrix.html", "w") as f:
        f.write(html)


def generate_unified_signals_page(
    documents: list[dict],
    checks: list,
    output_dir: Path
) -> None:
    """
    Generate the unified signals page showing all documents with signals.

    Args:
        documents: All processed documents
        checks: All check definitions
        output_dir: Root output directory
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Filter to documents with signals (use signal_summary for linked documents)
    docs_with_signals = [doc for doc in documents if doc.get("signal_summary") or doc.get("signal_paragraphs")]

    # Count signal types
    resolution_count = len([d for d in docs_with_signals if d.get("doc_type") == "resolution"])
    proposal_count = len([d for d in docs_with_signals if d.get("doc_type") == "proposal"])

    # Count total paragraphs with signals
    total_paragraphs = sum(len(doc.get("signal_paragraphs", [])) for doc in docs_with_signals)

    # Get origin order for filtering
    origin_order = ["Plenary", "C1", "C2", "C3", "C4", "C5", "C6"]

    env = get_templates_env(checks)
    template = env.get_template("signals_unified.html")

    html = template.render(
        documents=docs_with_signals,
        checks=checks,
        origin_order=origin_order,
        origin_names=COMMITTEE_NAMES,
        total_docs=len(docs_with_signals),
        total_paragraphs=total_paragraphs,
        resolution_count=resolution_count,
        proposal_count=proposal_count,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    with open(output_dir / "signals.html", "w") as f:
        f.write(html)


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
    import time
    import logging

    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    start_time = time.time()
    logger.info(f"Starting unified explorer generation for {len(documents)} documents")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Ensure signal_paragraphs are populated for current-session docs
    enrichment_start = time.time()
    enriched_docs = []
    for doc in documents:
        if doc.get("signal_paragraphs"):
            enriched_docs.append(doc)
            continue

        signal_paras = []
        for para_num, para_signals in doc.get("signals", {}).items():
            if para_signals:
                para_text = doc.get("paragraphs", {}).get(para_num, "")
                signal_paras.append({
                    "number": para_num,
                    "text": para_text,
                    "signals": para_signals,
                })

        if signal_paras:
            signal_paras.sort(key=lambda p: int(p["number"]))
            doc_copy = doc.copy()
            doc_copy["signal_paragraphs"] = signal_paras
            enriched_docs.append(doc_copy)
        else:
            enriched_docs.append(doc)

    documents = enriched_docs
    enrichment_time = time.time() - enrichment_start
    logger.info(f"Enriched documents with signal_paragraphs in {enrichment_time:.2f}s")

    # Filter to documents with signals
    filter_start = time.time()
    docs_with_signals = [doc for doc in documents if doc.get("signal_paragraphs")]
    filter_time = time.time() - filter_start
    logger.info(f"Filtered to {len(docs_with_signals)} documents with signals in {filter_time:.2f}s")

    # Sort documents using unified sorting logic
    sort_start = time.time()
    docs_with_signals.sort(key=unified_sort_key)
    sort_time = time.time() - sort_start
    logger.info(f"Sorted {len(docs_with_signals)} documents in {sort_time:.2f}s")

    # Count signal types
    count_start = time.time()
    resolution_count = len([d for d in docs_with_signals if d.get("doc_type") == "resolution"])
    proposal_count = len([d for d in docs_with_signals if d.get("doc_type") == "proposal"])

    # Count total paragraphs/signals (use available data)
    if docs_with_signals and docs_with_signals[0].get("signal_paragraphs"):
        # Original format with paragraph details
        total_paragraphs = sum(len(doc.get("signal_paragraphs", [])) for doc in docs_with_signals)
    else:
        # Linked format with summary only - count total signal instances
        total_paragraphs = sum(sum(counts.values()) for doc in docs_with_signals
                              for counts in [doc.get("signal_summary", {})])
    count_time = time.time() - count_start
    logger.info(f"Counted statistics in {count_time:.2f}s: {resolution_count} resolutions, {proposal_count} proposals, {total_paragraphs} paragraphs")

    # Get origin order for filtering
    origin_order = ["Plenary", "C1", "C2", "C3", "C4", "C5", "C6"]

    # Template preparation
    template_start = time.time()
    env = get_templates_env(checks)
    template = env.get_template("signals_unified_explorer.html")
    template_prep_time = time.time() - template_start
    logger.info(f"Template preparation in {template_prep_time:.2f}s")

    # Template rendering
    render_start = time.time()
    html = template.render(
        documents=docs_with_signals,
        checks=checks,
        origin_order=origin_order,
        origin_names=COMMITTEE_NAMES,
        total_docs=len(docs_with_signals),
        total_paragraphs=total_paragraphs,
        resolution_count=resolution_count,
        proposal_count=proposal_count,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    render_time = time.time() - render_start
    logger.info(f"Template rendering in {render_time:.2f}s, HTML size: {len(html)} characters")

    # File writing
    write_start = time.time()
    with open(output_dir / "signals-unified.html", "w") as f:
        f.write(html)
    with open(output_dir / "index.html", "w") as f:
        f.write(html)
    write_time = time.time() - write_start
    logger.info(f"File writing in {write_time:.2f}s")

    total_time = time.time() - start_time
    logger.info(f"Unified explorer generation completed in {total_time:.2f}s")


def generate_igov_signals_page(
    checks: list,
    data_dir: Path,
    output_dir: Path,
    session=None,
) -> dict:
    """Generate a standalone IGov decision signal browser page."""
    if session is None:
        decisions = load_igov_decisions_all(data_dir)
    else:
        decisions = load_igov_decisions(data_dir, session)

    decision_docs = []
    for decision in decisions:
        decision_text = (decision.get("decision_text") or "").strip()
        if not decision_text:
            continue

        paragraphs = {1: decision_text}
        signals = run_checks(paragraphs, checks) if checks else {}

        signal_summary = {}
        signal_paragraphs = []
        for para_num, para_signals in signals.items():
            if para_signals:
                signal_paragraphs.append({
                    "number": para_num,
                    "text": paragraphs.get(para_num, ""),
                    "signals": para_signals,
                })
                for sig in para_signals:
                    signal_summary[sig] = signal_summary.get(sig, 0) + 1

        decision_docs.append({
            **decision,
            "paragraphs": paragraphs,
            "signals": signals,
            "signal_summary": signal_summary,
            "signal_paragraphs": signal_paragraphs,
        })

    docs_with_signals = [doc for doc in decision_docs if doc.get("signal_paragraphs")]
    total_paragraphs = sum(len(doc.get("signal_paragraphs", [])) for doc in docs_with_signals)
    session_label = decisions[0].get("session_label") if decisions else ""
    session_list = []
    seen_sessions = set()
    for doc in decisions:
        session_value = doc.get("session")
        if session_value is None:
            continue
        try:
            session_int = int(session_value)
        except (TypeError, ValueError):
            continue
        if session_int in seen_sessions:
            continue
        seen_sessions.add(session_int)
        session_list.append(session_int)
    session_list.sort(reverse=True)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = get_templates_env(checks)
    template = env.get_template("signals_igov.html")

    html = template.render(
        documents=docs_with_signals,
        checks=checks,
        total_docs=len(docs_with_signals),
        total_paragraphs=total_paragraphs,
        session=session,
        session_label=session_label,
        sessions=session_list,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    with open(output_dir / "signals-unified.html", "w") as f:
        f.write(html)
    with open(output_dir / "index.html", "w") as f:
        f.write(html)

    return {
        "total_decisions": len(decision_docs),
        "decisions_with_signals": len(docs_with_signals),
        "total_signal_paragraphs": total_paragraphs,
    }


def generate_session_unified_signals_page(
    session: int,
    all_documents: list[dict],
    checks: list,
    output_dir: Path
) -> dict:
    """
    Generate signals.html for a specific historical session using the same template as main site.

    Args:
        session: Session number (e.g., 79)
        all_documents: All processed documents (will be filtered to session)
        checks: All check definitions
        output_dir: Root output directory (will create sessions/{session}/ subdirectory)
    """
    output_dir = Path(output_dir)
    session_output_dir = output_dir / "sessions" / str(session)
    session_output_dir.mkdir(parents=True, exist_ok=True)

    # Filter to session resolutions only
    session_docs = [doc for doc in all_documents if f"/RES/{session}/" in doc["symbol"]]

    # Transform signals to signal_paragraphs format for template compatibility
    enriched_docs = []
    for doc in session_docs:
        doc_copy = doc.copy()

        # Find all paragraphs that have any signal
        signal_paras = []
        paragraphs = doc.get("paragraphs", {})
        for para_num, para_signals in doc.get("signals", {}).items():
            if para_signals:  # Has at least one signal
                # para_num is already a string key that matches the paragraphs dict
                para_text = paragraphs.get(para_num, "")
                signal_paras.append({
                    "number": para_num,
                    "text": para_text,
                    "signals": para_signals
                })

        # Sort paragraphs by number
        signal_paras.sort(key=lambda p: int(p["number"]))
        doc_copy["signal_paragraphs"] = signal_paras
        enriched_docs.append(doc_copy)

    # Filter to documents with signals (use signal_summary for linked documents)
    docs_with_signals = [doc for doc in enriched_docs if doc.get("signal_summary") or doc.get("signal_paragraphs")]

    # Ensure all documents have required fields for template compatibility
    for doc in docs_with_signals:
        if "signal_summary" not in doc:
            # Create signal summary from signal_paragraphs if it exists
            signal_paragraphs = doc.get("signal_paragraphs", {})
            signal_summary = {}
            if signal_paragraphs:
                for para_signals in signal_paragraphs.values():
                    for signal in para_signals:
                        signal_summary[signal] = signal_summary.get(signal, 0) + 1
            doc["signal_summary"] = signal_summary

    # Count signal types (only resolutions for past sessions)
    resolution_count = len(docs_with_signals)
    proposal_count = 0  # No proposals for past sessions

    # Count total paragraphs with signals
    total_paragraphs = sum(len(doc.get("signal_paragraphs", [])) for doc in docs_with_signals)

    # Get origin order for filtering
    origin_order = ["Plenary", "C1", "C2", "C3", "C4", "C5", "C6"]

    env = get_templates_env(checks)
    template = env.get_template("signals_unified.html")

    html = template.render(
        documents=docs_with_signals,
        checks=checks,
        origin_order=origin_order,
        origin_names=COMMITTEE_NAMES,
        total_docs=len(docs_with_signals),
        total_paragraphs=total_paragraphs,
        resolution_count=resolution_count,
        proposal_count=proposal_count,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    with open(session_output_dir / "signals.html", "w") as f:
        f.write(html)

    return {
        "total_documents": len(enriched_docs),
        "documents_with_signals": len(docs_with_signals),
        "total_signal_paragraphs": total_paragraphs,
    }


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


def generate_debug_pages(
    documents: list,
    checks: list,
    output_dir: Path
) -> None:
    """
    Generate all debug pages.

    Args:
        documents: All documents
        checks: All check definitions
        output_dir: Output directory (debug/ subdirectory)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = get_templates_env(checks)
    audit_data = get_linking_audit()
    undl_cache = get_undl_cache_stats()

    resolutions = [doc for doc in documents if is_resolution(doc.get("symbol", ""))]
    proposals = [doc for doc in documents if is_proposal(doc.get("symbol", ""))]

    # Count linking methods
    linked_count = 0
    by_method = {"undl": 0, "symbol_ref": 0, "fuzzy": 0}
    for symbol, audit in audit_data.items():
        if audit.get("final_method"):
            linked_count += 1
            method = audit["final_method"]
            by_method[method] = by_method.get(method, 0) + 1

    # Stats for debug index
    stats = {
        "total_docs": len(documents),
        "total_resolutions": len(resolutions),
        "total_proposals": len(proposals),
        "linked": linked_count,
        "unlinked": len(resolutions) - linked_count,
        "coverage_pct": round(linked_count / len(resolutions) * 100, 1) if resolutions else 0,
        "by_method": by_method,
        "with_title": len([d for d in documents if d.get("title") and len(d["title"]) > 5]),
        "with_paragraphs": len([d for d in documents if d.get("num_paragraphs", 0) > 0]),
        "with_refs": len([d for d in documents if d.get("symbol_references")]),
        "potential_issues": len([d for d in documents if not d.get("title") or d.get("num_paragraphs", 0) == 0]),
        "near_misses": 0,
    }

    # Count near misses
    for audit in audit_data.values():
        candidates = audit.get("pass2_fuzzy", {}).get("candidates", [])
        if candidates and not audit.get("final_linked"):
            if candidates[0]["score"] >= 70:
                stats["near_misses"] += 1

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Generate debug index
    template = env.get_template("debug/index.html")
    html = template.render(
        stats=stats,
        generated_at=generated_at,
    )
    with open(output_dir / "index.html", "w") as f:
        f.write(html)

    # Generate linking audit page
    template = env.get_template("debug/linking.html")
    html = template.render(
        audit_data=audit_data,
        undl_cache=undl_cache,
        stats={
            "total": len(resolutions),
            "linked": linked_count,
            "unlinked": len(resolutions) - linked_count,
            "coverage_pct": stats["coverage_pct"],
            "by_method": by_method,
        },
        generated_at=generated_at,
    )
    with open(output_dir / "linking.html", "w") as f:
        f.write(html)

    # Generate orphans page
    orphans = [
        {**doc, "filename": symbol_to_filename(doc["symbol"]) + ".html"}
        for doc in resolutions
        if not doc.get("linked_proposals")
    ]
    template = env.get_template("debug/orphans.html")
    html = template.render(
        orphans=orphans,
        audit_data=audit_data,
        total_resolutions=len(resolutions),
        coverage_pct=stats["coverage_pct"],
        generated_at=generated_at,
    )
    with open(output_dir / "orphans.html", "w") as f:
        f.write(html)

    # Generate fuzzy match explorer
    fuzzy_entries = []
    fuzzy_linked = 0
    near_misses = 0
    no_match = 0

    for res in resolutions:
        audit = audit_data.get(res["symbol"], {})
        fuzzy_data = audit.get("pass2_fuzzy", {})
        entry = {
            "symbol": res["symbol"],
            "filename": symbol_to_filename(res["symbol"]) + ".html",
            "title": res.get("title", ""),
            "normalized_title": fuzzy_data.get("resolution_title", normalize_title(res.get("title", ""))),
            "candidates": fuzzy_data.get("candidates", []),
            "linked": bool(audit.get("final_linked")),
            "linked_symbol": audit.get("final_linked", [None])[0] if audit.get("final_linked") else None,
        }
        fuzzy_entries.append(entry)

        if entry["linked"]:
            if audit.get("final_method") == "fuzzy":
                fuzzy_linked += 1
        elif entry["candidates"] and entry["candidates"][0]["score"] >= 70:
            near_misses += 1
        else:
            no_match += 1

    # Sort by symbol
    fuzzy_entries.sort(key=lambda x: natural_sort_key(x["symbol"]))

    template = env.get_template("debug/fuzzy.html")
    html = template.render(
        fuzzy_entries=fuzzy_entries,
        stats={
            "total_resolutions": len(resolutions),
            "total_proposals": len(proposals),
            "fuzzy_linked": by_method.get("fuzzy", 0),
            "near_misses": near_misses,
            "no_match": no_match,
        },
        generated_at=generated_at,
    )
    with open(output_dir / "fuzzy.html", "w") as f:
        f.write(html)

    # Generate extraction verification page
    extraction_docs = []
    for doc in documents:
        extraction_docs.append({
            "symbol": doc["symbol"],
            "filename": symbol_to_filename(doc["symbol"]) + ".html",
            "title": doc.get("title", ""),
            "num_paragraphs": doc.get("num_paragraphs", 0),
            "signal_summary": doc.get("signal_summary", {}),
            "symbol_references": doc.get("symbol_references", []),
            "agenda_items": doc.get("agenda_items", []),
            "un_url": doc.get("un_url", ""),
        })
    extraction_docs.sort(key=lambda x: natural_sort_key(x["symbol"]))

    template = env.get_template("debug/extraction.html")
    html = template.render(
        documents=extraction_docs,
        stats={
            "total_docs": len(documents),
            "with_title": stats["with_title"],
            "with_paragraphs": stats["with_paragraphs"],
            "with_refs": stats["with_refs"],
            "potential_issues": stats["potential_issues"],
        },
        generated_at=generated_at,
    )
    with open(output_dir / "extraction.html", "w") as f:
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

    # Create output directories
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check if we should skip detailed pages for performance
    skip_detailed_pages = os.getenv("SKIP_DETAILED_PAGES", "false").lower() == "true"

    # Only create detailed page directories if needed
    if not skip_detailed_pages:
        (output_dir / "signals").mkdir(exist_ok=True)
        (output_dir / "patterns").mkdir(exist_ok=True)
        (output_dir / "matrix").mkdir(exist_ok=True)
        (output_dir / "provenance").mkdir(exist_ok=True)

    # Generate essential pages
    generate_index_page(visible_documents, checks, patterns, output_dir)
    generate_signals_info_page(checks, output_dir)

    # Generate detailed pages (can be skipped for performance)
    if not skip_detailed_pages:
        print("Generating detailed signal pages...")
        for check in checks:
            generate_signal_page(documents, visible_documents, check, checks, output_dir / "signals")

        print("Generating pattern pages...")
        for pattern in patterns:
            generate_pattern_page(documents, visible_documents, pattern, checks, patterns, output_dir / "patterns")
            # Generate pattern+signal pages
            for check in checks:
                generate_pattern_signal_page(documents, visible_documents, pattern, check["signal"], checks, patterns, output_dir / "matrix")

        print("Generating additional analysis pages...")
        generate_provenance_page(documents, checks, output_dir / "provenance")
        generate_origin_matrix_page(documents, checks, output_dir)

    # Always generate unified pages (core functionality)
    print("Generating unified signals pages...")
    generate_unified_signals_page(documents, checks, output_dir)
    generate_unified_explorer_page(documents, checks, output_dir)

    # Generate data exports
    generate_data_json(visible_documents, checks, output_dir)
    generate_search_index(visible_documents, output_dir)

    print(f"Generated static site with {len(visible_documents)} documents in {output_dir}")


def generate_site_verbose(
    config_dir: Path,
    data_dir: Path,
    output_dir: Path,
    skip_debug: bool = False,
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
    patterns = load_patterns(config_dir / "patterns.yaml")

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

    load_duration = time.time() - load_start_time
    if on_load_end:
        on_load_end(len(documents), load_duration)

    # Generate pages
    if on_generate_start:
        on_generate_start()

    generate_start_time = time.time()

    # Create output directories
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "signals").mkdir(exist_ok=True)
    (output_dir / "patterns").mkdir(exist_ok=True)
    (output_dir / "matrix").mkdir(exist_ok=True)
    (output_dir / "provenance").mkdir(exist_ok=True)

    # Generate pages
    generate_index_page(visible_documents, checks, patterns, output_dir)
    if on_generate_page:
        on_generate_page("index", "index.html")

    generate_signals_info_page(checks, output_dir)
    if on_generate_page:
        on_generate_page("signals_info", "signals-info.html")

    for check in checks:
        generate_signal_page(documents, visible_documents, check, checks, output_dir / "signals")
        if on_generate_page:
            on_generate_page("signal", f"signals/{check['signal'].lower().replace(' ', '-')}.html")

    for pattern in patterns:
        generate_pattern_page(documents, visible_documents, pattern, checks, patterns, output_dir / "patterns")
        pattern_slug = get_pattern_slug(pattern["name"])
        if on_generate_page:
            on_generate_page("pattern", f"patterns/{pattern_slug}.html")
        # Generate pattern+signal pages
        for check in checks:
            generate_pattern_signal_page(documents, visible_documents, pattern, check["signal"], checks, patterns, output_dir / "matrix")
            signal_slug = get_signal_slug(check["signal"])
            if on_generate_page:
                on_generate_page("matrix", f"matrix/{pattern_slug}_{signal_slug}.html")

    # Generate new UI pages
    generate_provenance_page(documents, checks, output_dir / "provenance")
    if on_generate_page:
        on_generate_page("provenance", "provenance/index.html")

    generate_origin_matrix_page(documents, checks, output_dir)
    if on_generate_page:
        on_generate_page("origin_matrix", "origin_matrix.html")

    generate_unified_signals_page(documents, checks, output_dir)
    if on_generate_page:
        on_generate_page("signals_unified", "signals.html")

    generate_unified_explorer_page(documents, checks, output_dir)
    if on_generate_page:
        on_generate_page("signals_unified_explorer", "signals-unified.html")

    # Generate data exports
    generate_data_json(visible_documents, checks, output_dir)
    if on_generate_page:
        on_generate_page("data", "data.json")

    generate_search_index(visible_documents, output_dir)
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
        "total_documents": len(visible_documents),
        "documents_with_signals": len([d for d in visible_documents if d.get("signals")]),
        "document_pages": len(documents),
        "signal_pages": len(checks),
        "signal_counts": total_signal_counts,
    }


def generate_sessions_index_page(output_dir: Path):
    """Deprecated: historical sessions index page removed."""
    return
