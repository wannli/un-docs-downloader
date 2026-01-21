"""Static site generator for Mandate Pipeline."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .checks import load_checks, run_checks
from rapidfuzz import fuzz

from .extractor import (
    extract_text,
    extract_operative_paragraphs,
    extract_title,
    extract_agenda_items,
    find_symbol_references,
)
from .pipeline import load_patterns
from .lineage import load_lineage_cache


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


def infer_base_proposal_symbol(symbol: str, doc_type: str, text: str) -> str | None:
    """Infer the base proposal symbol for proposals or amendments."""
    # Heuristic trade-offs:
    # - We scan a short front-matter window to keep it fast, but
    #   amendments can reference targets later in the document.
    # - The regex is conservative, so unknown formats fall back to None.
    # - We now capture optional /Rev.X suffixes found in draft symbols.
    if doc_type == "proposal":
        return symbol
    if doc_type == "amendment":
        front_matter = text.split("\f", 2)[0:2]
        front_matter_text = "\f".join(front_matter)[:4000]
        symbol_match = re.search(
            r"\bA/\d+/(?:L\.\d+|C\.\d+/\d+/L\.\d+|C\.\d+/L\.\d+)(?:/Rev\.\d+)?\b",
            front_matter_text,
        )
        if symbol_match:
            return symbol_match.group(0)
    return None


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

    lineage_cache = load_lineage_cache(data_dir / "lineage.json")
    lineage_documents = lineage_cache.get("documents", {})

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
            base_proposal_symbol = infer_base_proposal_symbol(symbol, doc_type, text)

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
                "base_proposal_symbol": base_proposal_symbol,
                "paragraphs": paragraphs,
                "title": title,
                "agenda_items": agenda_items,
                "symbol_references": symbol_references,
                "doc_type": doc_type,
                "base_proposal_symbol": base_proposal_symbol,
                "signals": signals,
                "signal_summary": signal_summary,
                "lineage": lineage_documents.get(symbol, {}),
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


def normalize_title(title: str) -> str:
    """Normalize a title for fuzzy matching."""
    # Strip resolution/decision number prefix like "80/60." or "80/60 "
    title = re.sub(r"^\d+/\d+[.\s]+", "", title)
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def is_resolution(symbol: str) -> bool:
    """Return True if symbol looks like a resolution."""
    return "/RES/" in symbol


def is_proposal(symbol: str) -> bool:
    """Return True if symbol looks like a draft/proposal (L. symbol)."""
    return "/L." in symbol


def link_documents(documents: list[dict]) -> None:
    """
    Link resolutions to proposals using explicit references and fuzzy matching.

    First pass: link by symbol references.
    Second pass: link by normalized title similarity and agenda overlap.
    """
    proposals_by_symbol = {doc["symbol"]: doc for doc in documents if is_proposal(doc["symbol"])}
    proposals = list(proposals_by_symbol.values())

    for doc in documents:
        doc.setdefault("linked_resolution_symbol", None)
        doc.setdefault("linked_proposal_symbols", [])
        doc.setdefault("link_method", None)
        doc.setdefault("link_confidence", None)

    for doc in documents:
        if not is_resolution(doc["symbol"]):
            continue
        references = doc.get("symbol_references", [])
        linked = [ref for ref in references if ref in proposals_by_symbol]
        if not linked:
            continue
        doc["linked_proposal_symbols"] = linked
        doc["link_method"] = "symbol_reference"
        doc["link_confidence"] = 1.0
        if doc.get("base_proposal_symbol") is None:
            doc["base_proposal_symbol"] = linked[0]
        for ref in linked:
            proposal = proposals_by_symbol.get(ref)
            if proposal is None:
                continue
            if proposal.get("linked_resolution_symbol") is None:
                proposal["linked_resolution_symbol"] = doc["symbol"]
                proposal["link_method"] = "symbol_reference"
                proposal["link_confidence"] = 1.0

    for doc in documents:
        if not is_resolution(doc["symbol"]):
            continue
        if doc.get("linked_proposal_symbols"):
            continue

        title = normalize_title(doc.get("title", ""))
        if not title:
            continue
        agenda_items = set(doc.get("agenda_items") or [])

        best_match = None
        best_score = 0.0
        best_confidence = 0.0

        for proposal in proposals:
            if proposal.get("linked_resolution_symbol") not in (None, doc["symbol"]):
                continue

            proposal_title = normalize_title(proposal.get("title", ""))
            if not proposal_title:
                continue

            proposal_agenda = set(proposal.get("agenda_items") or [])
            if agenda_items and proposal_agenda and not agenda_items.intersection(proposal_agenda):
                continue

            similarity = fuzz.ratio(title, proposal_title)
            if similarity < 85:
                continue

            confidence = similarity / 100.0
            if agenda_items and proposal_agenda:
                confidence = min(confidence + 0.05, 1.0)

            if similarity > best_score:
                best_score = similarity
                best_match = proposal
                best_confidence = confidence

        if best_match:
            doc["linked_proposal_symbols"] = [best_match["symbol"]]
            doc["link_method"] = "title_agenda_fuzzy"
            doc["link_confidence"] = best_confidence
            if doc.get("base_proposal_symbol") is None:
                doc["base_proposal_symbol"] = best_match["symbol"]

            if best_match.get("linked_resolution_symbol") is None:
                best_match["linked_resolution_symbol"] = doc["symbol"]
                best_match["link_method"] = "title_agenda_fuzzy"
                best_match["link_confidence"] = best_confidence


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


def get_templates_env(checks: list = None) -> Environment:
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


def generate_signal_page(documents: list, check: dict, checks: list, output_dir: Path) -> None:
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

    env = get_templates_env(checks)
    template = env.get_template("pattern.html")

    pattern_name = pattern["name"]
    docs_by_pattern = group_documents_by_pattern(documents, patterns)
    pattern_docs = docs_by_pattern.get(pattern_name, [])

    # Calculate signal counts for this pattern
    pattern_signal_counts = {}
    for doc in pattern_docs:
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
        total_docs=len(enriched_docs),
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
    pattern_docs = docs_by_pattern.get(pattern_name, [])
    
    # Filter to only docs with this signal and add signal_paragraphs
    filtered_docs = []
    total_paragraphs = 0
    
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
    
    # Sort documents naturally by symbol
    filtered_docs.sort(key=lambda d: natural_sort_key(d["symbol"]))

    html = template.render(
        pattern=pattern,
        pattern_slug=pattern_slug,
        signal=signal,
        documents=filtered_docs,
        total_paragraphs=total_paragraphs,
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
    link_documents(documents)

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
        generate_signal_page(documents, check, checks, output_dir / "signals")

    for pattern in patterns:
        generate_pattern_page(documents, pattern, checks, patterns, output_dir / "patterns")
        # Generate pattern+signal pages
        for check in checks:
            generate_pattern_signal_page(documents, pattern, check["signal"], checks, patterns, output_dir / "matrix")

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
    lineage_cache = load_lineage_cache(data_dir / "lineage.json")
    lineage_documents = lineage_cache.get("documents", {})

    if pdfs_dir.exists():
        for pdf_file in pdfs_dir.glob("*.pdf"):
            doc_start_time = time.time()
            symbol = filename_to_symbol(pdf_file.stem)

            try:
                text = extract_text(pdf_file)
                paragraphs = extract_operative_paragraphs(text)
                title = extract_title(text)
                agenda_items = extract_agenda_items(text)
                symbol_references = find_symbol_references(text)
                doc_type = classify_doc_type(symbol, text)
                base_proposal_symbol = infer_base_proposal_symbol(symbol, doc_type, text)
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
                    "base_proposal_symbol": base_proposal_symbol,
                    "paragraphs": paragraphs,
                    "title": title,
                    "agenda_items": agenda_items,
                    "symbol_references": symbol_references,
                    "doc_type": doc_type,
                    "base_proposal_symbol": base_proposal_symbol,
                    "signals": signals,
                    "signal_summary": signal_summary,
                    "lineage": lineage_documents.get(symbol, {}),
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

    link_documents(documents)

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
        generate_signal_page(documents, check, checks, output_dir / "signals")
        if on_generate_page:
            on_generate_page("signal", f"signals/{check['signal'].lower().replace(' ', '-')}.html")

    for pattern in patterns:
        generate_pattern_page(documents, pattern, checks, patterns, output_dir / "patterns")
        pattern_slug = get_pattern_slug(pattern["name"])
        if on_generate_page:
            on_generate_page("pattern", f"patterns/{pattern_slug}.html")
        # Generate pattern+signal pages
        for check in checks:
            generate_pattern_signal_page(documents, pattern, check["signal"], checks, patterns, output_dir / "matrix")
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
