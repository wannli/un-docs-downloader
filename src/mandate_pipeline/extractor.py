"""Extract text from PDF documents."""

import re
from pathlib import Path

import pymupdf


def extract_text(pdf_path: Path) -> str:
    """
    Extract full text from a PDF file.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Extracted text as a string
    """
    pdf_path = Path(pdf_path)
    
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    text_parts = []
    
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            text_parts.append(page.get_text())

    return "\n".join(text_parts)


def extract_operative_paragraphs(text: str) -> dict[int, str]:
    """
    Extract operative paragraphs from UN resolution text.

    Operative paragraphs are numbered sequentially (1, 2, 3, etc.)
    and typically start with action verbs like "Calls upon", "Requests",
    "Decides", etc.

    Args:
        text: Full text of the resolution

    Returns:
        Dictionary mapping paragraph numbers to their text content
    """
    paragraphs = {}

    # Pattern: number at start of line, followed by period and text
    # The paragraph continues until the next numbered paragraph or end
    pattern = r"^\s*(\d+)\.\s+(.+?)(?=^\s*\d+\.\s+|\Z)"

    matches = re.findall(pattern, text, re.MULTILINE | re.DOTALL)

    for num_str, content in matches:
        num = int(num_str)
        # Clean up the content: normalize whitespace
        cleaned = " ".join(content.split())
        paragraphs[num] = cleaned

    return paragraphs


def extract_title(text: str) -> str:
    """
    Extract a document title using simple heuristics.

    The title is assumed to be the first non-empty line before the operative
    paragraphs or before an A/RES stamp line.

    Args:
        text: Full text of the document

    Returns:
        Extracted title string or empty string if not found
    """
    lines = text.splitlines()
    stop_indices = []

    for idx, line in enumerate(lines):
        if re.match(r"^\s*\d+\.", line):
            stop_indices.append(idx)
            break

    stop_at = min(stop_indices) if stop_indices else len(lines)

    skip_prefixes = (
        "United Nations",
        "General Assembly",
        "Security Council",
        "Distr.",
    )
    skip_regexes = [
        r"^[A-Z]{1,2}/[A-Z0-9./-]+$",
        r"^Agenda item",
        r"^Item\s+\d+",
        r"^\d{1,2}\s+\w+\s+\d{4}$",
        r"^\d{2}-\d{5}\s+\(E\).*$",
        r"^\*?\d{6,}\*?$",
        r"^Resolution adopted by",
        r"^\w+ session$",
        r"^(First|Second|Third|Fourth|Fifth|Sixth) Committee$",
        r"^A/RES",
        r"^Original:",
    ]

    first_candidate = ""
    start_at = 0

    for idx, line in enumerate(lines[:stop_at]):
        if re.search(r"draft resolution", line, re.IGNORECASE):
            start_at = idx + 1
            break

    for line in lines[start_at:stop_at]:
        candidate = line.strip()
        if not candidate:
            continue
        if candidate.startswith(skip_prefixes):
            continue
        if any(re.match(pattern, candidate) for pattern in skip_regexes):
            continue
        if re.match(r"^\d+/\d+\.\s+\S", candidate):
            return candidate
        if not first_candidate:
            first_candidate = candidate

    if first_candidate:
        return first_candidate

    return ""


def extract_agenda_items(text: str) -> list[str]:
    """
    Extract agenda item references from document text.

    Args:
        text: Full text of the document

    Returns:
        List of agenda item strings, e.g., ["Item 68", "Item 12A"]
    """
    items = []
    patterns = [
        r"\bAgenda item[s]?\s+(\d+[A-Za-z]?)\b",
        r"\bItem\s+(\d+[A-Za-z]?)\b",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            item = f"Item {match.group(1)}"
            if item not in items:
                items.append(item)

    return items


def find_symbol_references(text: str) -> list[str]:
    """
    Find references to A/.../L. symbols in document text.

    Args:
        text: Full text of the document

    Returns:
        List of referenced symbols (unique, in appearance order)
    """
    pattern = r"\bA(?:/[A-Z0-9.]+)+/L\.\d+\b"
    matches = re.finditer(pattern, text, re.IGNORECASE)
    symbols = []
    for match in matches:
        symbol = match.group(0).upper()
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols
