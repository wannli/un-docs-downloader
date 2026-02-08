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
        cleaned = _clean_paragraph_text(cleaned)
        paragraphs[num] = cleaned

    return paragraphs


# Matches trailing plenary meeting info, e.g.:
#   "54th plenary meeting 2 December 2025"
#   "55th (resumed) plenary meeting 24 December 2024"
_PLENARY_SUFFIX_RE = re.compile(
    r"\s*\d+(?:st|nd|rd|th)\s+(?:\(resumed\)\s+)?plenary\s+meeting\s+"
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{4}\s*$"
)

# Matches footnote + page-header blocks injected at PDF page boundaries.
# Pattern: _{3,} <footnote refs> ... <doc title> <symbol> <page/total> <doc-id>
# The doc-id (e.g. 25-20110) and optional page/total (e.g. 3/3) are the
# reliable end markers of the injected block.
_FOOTNOTE_PAGE_RE = re.compile(
    r"\s*_{3,}.+?\d{2}-\d{4,5}(?:\s+\d+/\d+)?",
    re.DOTALL
)

# Matches bare page-header blocks (no footnotes) injected at page boundaries.
# Can start with symbol OR title words, but always ends with the UN document ID (XX-XXXXX).
_PAGE_HEADER_RE = re.compile(
    r"\s*(?:A/(?:RES|C\.\d+|DEC)/\d+/\S+|[A-Z][a-z]+).+?\d{2}-\d{4,5}(?:\s+\d+/\d+)?",
    re.DOTALL
)

# Matches footnote blocks at end of text (no continuation after)
_FOOTNOTE_TAIL_RE = re.compile(r"\s*_{3,}\s*.+$")


def _clean_paragraph_text(text: str) -> str:
    """Remove PDF extraction artifacts from paragraph text.

    Strips:
    - Mid-text footnote + page header blocks (footnotes at page bottom
      followed by next page's header, injected between real content)
    - Bare page header blocks (symbol + title + page/total + doc-id)
    - Trailing footnote blocks at end of paragraph
    - Trailing plenary meeting info (e.g. "54th plenary meeting 2 December 2025")
    """
    # First remove mid-text footnote+header blocks (have doc-id end marker)
    text = _FOOTNOTE_PAGE_RE.sub(" ", text)
    # Remove bare page header blocks (symbol anchored, no footnotes)
    text = _PAGE_HEADER_RE.sub(" ", text)
    # Then remove any remaining trailing footnote block
    text = _FOOTNOTE_TAIL_RE.sub("", text)
    # Remove plenary meeting suffix
    text = _PLENARY_SUFFIX_RE.sub("", text)
    # Collapse any double spaces from removals
    text = re.sub(r"  +", " ", text)
    return text.rstrip()


def extract_lettered_paragraphs(text: str) -> dict[str, str]:
    """
    Extract lettered paragraphs from UN draft decisions.

    Draft decisions use lettered paragraphs (a), (b), (c) instead of
    numbered paragraphs 1., 2., 3.

    Args:
        text: Full text of the draft decision

    Returns:
        Dictionary mapping paragraph letters to their text content
    """
    paragraphs = {}

    # Pattern: (a), (b), (c), etc. at start of line
    # The paragraph continues until the next lettered paragraph or end
    pattern = r"^\s*\(([a-z])\)\s+(.+?)(?=^\s*\([a-z]\)\s+|\Z)"

    matches = re.findall(pattern, text, re.MULTILINE | re.DOTALL)

    for letter, content in matches:
        # Clean up the content: normalize whitespace
        cleaned = " ".join(content.split())
        cleaned = _clean_paragraph_text(cleaned)
        paragraphs[letter] = cleaned

    return paragraphs


def extract_title(text: str) -> str:
    """
    Extract a document title using simple heuristics.

    For resolutions: title is after "Resolution adopted by" with format "80/1. Title"
    For proposals: title is after "draft resolution" line, may span multiple lines.

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
        "Distr.",
    )
    skip_regexes = [
        r"^United Nations$",
        r"^General Assembly$",
        r"^Security Council$",
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
        r"^\[on the report of",
        r"^\[without reference to",
        # Skip facilitator/submitter lines (end with country in parentheses)
        r"^.*\([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+of\s+[A-Z][a-z]+)?\s*\)\s*$",
        # Skip "on the basis of informal consultations" lines
        r".*on the basis of informal consultations",
        # Skip lines referencing other draft resolutions
        r"^.*resolution\s+A/C\.\d+/\d+/L\.\d+",
    ]

    # Patterns that indicate end of title (start of document body)
    title_end_patterns = [
        r"^The General Assembly",
        r"^The Security Council",
        r"^Recalling",
        r"^Reaffirming",
        r"^Noting",
        r"^Recognizing",
        r"^Welcoming",
        r"^Expressing",
        r"^Bearing in mind",
        r"^Having",
        r"^Mindful",
        r"^Concerned",
        r"^Convinced",
        r"^Guided by",
        r"^Taking note",
        r"^Pursuant to",
    ]

    def is_skip_line(candidate: str) -> bool:
        if candidate.startswith(skip_prefixes):
            return True
        if any(re.match(pattern, candidate) for pattern in skip_regexes):
            return True
        return False

    def is_title_end(candidate: str) -> bool:
        return any(re.match(pattern, candidate) for pattern in title_end_patterns)

    # For resolutions: find title after "Resolution adopted by" line
    # The title format is "80/1. Title..." and may span multiple lines
    resolution_start = None
    for idx, line in enumerate(lines[:stop_at]):
        if re.search(r"Resolution adopted by", line, re.IGNORECASE):
            resolution_start = idx + 1
            break

    if resolution_start is not None:
        # Look for resolution number format (e.g., "80/60. Title...")
        res_title_parts = []
        collecting_res_title = False
        for line in lines[resolution_start:stop_at]:
            candidate = line.strip()

            if re.match(r"^\d+/\d+\.\s+\S", candidate):
                res_title_parts.append(candidate)
                collecting_res_title = True
                continue

            if collecting_res_title:
                # Stop at empty line or body start
                if not candidate or is_title_end(candidate):
                    break
                # Continue collecting title lines
                res_title_parts.append(candidate)

        if res_title_parts:
            return " ".join(res_title_parts)

    # For proposals: find title after "draft resolution" or "draft decision" line
    start_at = 0
    for idx, line in enumerate(lines[:stop_at]):
        if re.search(r"draft (resolution|decision)", line, re.IGNORECASE):
            start_at = idx + 1
            break

    # Collect title parts (may span multiple lines)
    title_parts = []
    collecting = False

    for line in lines[start_at:stop_at]:
        candidate = line.strip()

        # Skip empty lines before title starts
        if not candidate and not collecting:
            continue

        # Check for resolution number format (e.g., "80/60. Title...")
        if re.match(r"^\d+/\d+\.\s+\S", candidate):
            return candidate

        # Skip header lines
        if is_skip_line(candidate):
            continue

        # Stop if we hit the document body
        if is_title_end(candidate):
            break

        # Empty line after title started means title is complete
        if not candidate and collecting:
            break

        # Found a title line
        if candidate:
            title_parts.append(candidate)
            collecting = True

    if title_parts:
        return " ".join(title_parts)

    # Special case: outcome documents where title follows "Adopts the following outcome document"
    # Structure: "Adopts the following outcome document...:" then blank lines, then actual title
    outcome_start = None
    for idx, line in enumerate(lines):
        if re.search(r"Adopts the following outcome document", line, re.IGNORECASE):
            outcome_start = idx
            break

    if outcome_start is not None:
        # First, skip past the "Adopts..." sentence (ends with colon)
        colon_found = False
        title_start = outcome_start
        for idx, line in enumerate(lines[outcome_start:], start=outcome_start):
            if ":" in line:
                colon_found = True
                title_start = idx + 1
                break

        if colon_found:
            outcome_title_parts = []
            collecting_outcome = False
            for line in lines[title_start:]:
                candidate = line.strip()

                # Skip empty lines before title
                if not candidate and not collecting_outcome:
                    continue

                # Stop at preambular markers (We, the Ministers... or Recalling...)
                if re.match(r"^(We,|Recalling|Reaffirming|Noting)", candidate):
                    break

                # Empty line after collecting means done
                if not candidate and collecting_outcome:
                    break

                if candidate:
                    outcome_title_parts.append(candidate)
                    collecting_outcome = True

            if outcome_title_parts:
                return " ".join(outcome_title_parts)

    return ""


def extract_amendment_text(text: str) -> dict[int, str]:
    """
    Extract text content from amendment documents.

    Amendments don't have standard numbered operative paragraphs.
    This function extracts the body text after the header and before
    any footer markers, returning it as a single paragraph for signal detection.

    Args:
        text: Full text of the amendment document

    Returns:
        Dictionary with paragraph 1 containing the body text, or empty dict if no content
    """
    lines = text.splitlines()

    # Patterns that indicate end of header / start of body
    body_start_patterns = [
        r"^The General Assembly",
        r"^The Security Council",
        r"^Recalling",
        r"^Reaffirming",
        r"^Noting",
        r"^Recognizing",
        r"^Welcoming",
        r"^Expressing",
        r"^Bearing in mind",
        r"^Having",
        r"^Mindful",
        r"^Concerned",
        r"^Convinced",
        r"^Guided by",
        r"^Taking note",
        r"^Pursuant to",
        r"^In operative paragraph",
        r"^In paragraph",
        r"^Insert",
        r"^Replace",
        r"^Delete",
        r"^Add",
        r"^After",
        r"^Before",
    ]

    # Patterns that indicate footer / end of body
    footer_patterns = [
        r"^\d{2}-\d{5}",  # Document ID like 24-12345
        r"^\*\d{6,}\*",  # Barcode pattern
        r"^GE\.\d{2}-\d+",  # Geneva ID
    ]

    # Header patterns to skip
    header_patterns = [
        r"^United Nations$",
        r"^General Assembly$",
        r"^Security Council$",
        r"^[A-Z]{1,2}/[A-Z0-9./-]+$",
        r"^Agenda item",
        r"^Item\s+\d+",
        r"^\d{1,2}\s+\w+\s+\d{4}$",
        r"^Distr\.",
        r"^Original:",
        r"^\w+ session$",
        r"^(First|Second|Third|Fourth|Fifth|Sixth) Committee$",
    ]

    def is_header_line(line: str) -> bool:
        return any(re.match(p, line) for p in header_patterns)

    def is_body_start(line: str) -> bool:
        return any(re.match(p, line, re.IGNORECASE) for p in body_start_patterns)

    def is_footer_line(line: str) -> bool:
        return any(re.match(p, line) for p in footer_patterns)

    # Find body start
    body_start_idx = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if is_header_line(stripped):
            body_start_idx = idx + 1
            continue
        if is_body_start(stripped):
            body_start_idx = idx
            break

    # Find body end (footer start)
    body_end_idx = len(lines)
    for idx in range(len(lines) - 1, body_start_idx, -1):
        stripped = lines[idx].strip()
        if not stripped:
            continue
        if is_footer_line(stripped):
            body_end_idx = idx
        else:
            break

    # Extract body text
    body_lines = []
    for line in lines[body_start_idx:body_end_idx]:
        stripped = line.strip()
        if stripped:
            body_lines.append(stripped)

    if not body_lines:
        return {}

    # Join and clean the body text
    body_text = " ".join(body_lines)
    body_text = " ".join(body_text.split())  # Normalize whitespace
    body_text = _clean_paragraph_text(body_text)

    if len(body_text) < 20:  # Too short to be meaningful
        return {}

    return {1: body_text}


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
