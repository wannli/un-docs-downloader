"""Document linking: connect resolutions to their source proposals."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import requests
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# UN Digital Library API for MARC XML metadata
UNDL_SEARCH_URL = "https://digitallibrary.un.org/search"
UNDL_TIMEOUT = 30  # seconds
MARC_NS = {"marc": "http://www.loc.gov/MARC21/slim"}


def fetch_undl_metadata(symbol: str) -> dict | None:
    """
    Fetch resolution metadata from UN Digital Library.

    Queries the UNDL search API for the given symbol and parses the MARC XML
    response to extract related document symbols from tag 993.

    Args:
        symbol: UN resolution symbol (e.g., "A/RES/80/142")

    Returns:
        Dictionary with metadata if found, None otherwise:
        {
            "symbol": str,
            "related_symbols": list[str],  # all tag 993 references
            "draft_symbols": list[str],    # only L. documents
            "base_proposal": str | None,   # first L. document
        }
    """
    params = {
        "ln": "en",
        "of": "xm",  # MARC XML output format
        "p": symbol,
        "rg": "5",  # limit results
    }

    try:
        resp = requests.get(UNDL_SEARCH_URL, params=params, timeout=UNDL_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Failed to fetch UNDL metadata for %s: %s", symbol, e)
        return None

    return _parse_undl_marc_xml(resp.text, symbol)


def _parse_undl_marc_xml(xml_text: str, target_symbol: str) -> dict | None:
    """
    Parse MARC XML response and extract related symbols.

    Args:
        xml_text: Raw XML response from UNDL
        target_symbol: The resolution symbol we're looking for

    Returns:
        Parsed metadata dictionary or None if not found
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("Failed to parse UNDL XML for %s: %s", target_symbol, e)
        return None

    # Normalize target for comparison
    target_upper = target_symbol.upper()

    for record in root.findall(".//marc:record", MARC_NS):
        # Check tag 191 subfield 'a' for the document symbol
        tag_191 = record.find(
            ".//marc:datafield[@tag='191']/marc:subfield[@code='a']", MARC_NS
        )
        if tag_191 is None or not tag_191.text:
            continue

        record_symbol = tag_191.text.strip().upper()
        if record_symbol != target_upper:
            continue

        # Found matching record - extract tag 993 cross-references
        related_symbols = []
        for tag_993 in record.findall(
            ".//marc:datafield[@tag='993']/marc:subfield[@code='a']", MARC_NS
        ):
            if tag_993.text:
                related_symbols.append(tag_993.text.strip())

        # Filter for L. documents (draft proposals)
        draft_symbols = [s for s in related_symbols if re.search(r"/L\.\d+", s)]

        return {
            "symbol": target_symbol,
            "related_symbols": related_symbols,
            "draft_symbols": draft_symbols,
            "base_proposal": draft_symbols[0] if draft_symbols else None,
        }

    return None


def symbol_to_filename(symbol: str) -> str:
    """Convert a UN symbol to a safe filename."""
    return symbol.replace("/", "_")


def filename_to_symbol(filename: str) -> str:
    """Convert a filename back to UN symbol."""
    stem = filename.replace(".pdf", "")
    return stem.replace("_", "/")


def classify_symbol(symbol: str) -> str:
    """Classify a document symbol into a coarse category."""
    upper_symbol = symbol.upper()
    if "/RES/" in upper_symbol:
        return "resolution"
    if re.search(r"/L\.\d+", upper_symbol):
        return "proposal"
    return "other"


def normalize_symbol(symbol: str) -> str:
    """Normalize a document symbol extracted from text."""
    return symbol.strip().upper()


def normalize_title(title: str | None) -> str:
    """Normalize a title for fuzzy matching."""
    if not title:
        return ""
    # Strip resolution/decision number prefix like "80/60." or "80/60 "
    title = re.sub(r"^\d+/\d+[.\s]+", "", title)
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def is_resolution(symbol: str) -> bool:
    """Return True if symbol looks like a resolution."""
    return "/RES/" in symbol


def is_proposal(symbol: str) -> bool:
    """Return True if symbol looks like a draft/proposal (L. symbol)."""
    return "/L." in symbol


def is_excluded_draft_symbol(symbol: str) -> bool:
    """Return True if symbol is a revision/addendum/corrigendum draft."""
    upper_symbol = symbol.upper()
    return any(token in upper_symbol for token in ("/REV.", "/ADD.", "/CORR."))


def is_base_proposal_doc(doc: dict) -> bool:
    """Return True if doc is a base draft proposal (not a revision/amendment)."""
    symbol = doc.get("symbol", "")
    if doc.get("doc_type") != "proposal":
        return False
    if is_excluded_draft_symbol(symbol):
        return False
    return is_proposal(symbol)


def link_documents(documents: list[dict], use_undl_metadata: bool = True) -> None:
    """
    Link resolutions to proposals using explicit references and fuzzy matching.

    Pass 0 (optional): Fetch base proposal from UN Digital Library metadata.
    Pass 1: Link by symbol references found in PDF text.
    Pass 2: Link by normalized title similarity and agenda overlap.

    Args:
        documents: List of document dictionaries with at least 'symbol' key.
        use_undl_metadata: If True, query UN Digital Library for authoritative
            base proposal symbols before falling back to PDF text extraction.
    """
    proposals_by_symbol = {doc["symbol"]: doc for doc in documents if is_proposal(doc["symbol"])}
    proposals = list(proposals_by_symbol.values())

    for doc in documents:
        doc.setdefault("linked_resolution_symbol", None)
        doc.setdefault("linked_proposal_symbols", [])
        doc.setdefault("link_method", None)
        doc.setdefault("link_confidence", None)

    # Pass 0: UN Digital Library metadata lookup (authoritative source)
    if use_undl_metadata:
        for doc in documents:
            if not is_resolution(doc["symbol"]):
                continue
            # Skip if already linked
            if doc.get("linked_proposal_symbols"):
                continue

            metadata = fetch_undl_metadata(doc["symbol"])
            if metadata is None or not metadata.get("draft_symbols"):
                continue

            draft_symbols = metadata["draft_symbols"]
            # Filter to only include proposals we have locally
            linked = [s for s in draft_symbols if s in proposals_by_symbol]

            if linked:
                doc["linked_proposal_symbols"] = linked
                doc["link_method"] = "undl_metadata"
                doc["link_confidence"] = 1.0
                if doc.get("base_proposal_symbol") is None:
                    doc["base_proposal_symbol"] = linked[0]

                # Mark the proposals as linked to this resolution
                for ref in linked:
                    proposal = proposals_by_symbol.get(ref)
                    if proposal and proposal.get("linked_resolution_symbol") is None:
                        proposal["linked_resolution_symbol"] = doc["symbol"]
                        proposal["link_method"] = "undl_metadata"
                        proposal["link_confidence"] = 1.0
            elif draft_symbols:
                # Store the base proposal even if we don't have the PDF locally
                # This helps identify which drafts we should consider downloading
                doc["base_proposal_symbol"] = draft_symbols[0]
                doc["link_method"] = "undl_metadata"
                doc["link_confidence"] = 1.0
                logger.info(
                    "UNDL metadata found draft %s for %s (not in local collection)",
                    draft_symbols[0],
                    doc["symbol"],
                )

    # Pass 1: Symbol references from PDF text
    for doc in documents:
        if not is_resolution(doc["symbol"]):
            continue
        # Skip if already linked via UNDL metadata
        if doc.get("linked_proposal_symbols"):
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

    # Pass 2: Fuzzy title matching with agenda overlap
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


def annotate_linkage(documents: list[dict]) -> None:
    """Annotate documents with adopted draft status and lineage metadata."""
    base_proposals = {doc["symbol"]: doc for doc in documents if is_base_proposal_doc(doc)}

    for doc in documents:
        doc["is_adopted_draft"] = False
        doc["adopted_by"] = None
        doc["linked_proposals"] = []

    for proposal in base_proposals.values():
        linked_resolution = proposal.get("linked_resolution_symbol")
        if linked_resolution:
            proposal["is_adopted_draft"] = True
            proposal["adopted_by"] = linked_resolution

    for doc in documents:
        if not is_resolution(doc.get("symbol", "")):
            continue
        linked = [
            symbol for symbol in doc.get("linked_proposal_symbols", [])
            if symbol in base_proposals
        ]
        doc["linked_proposals"] = [
            {"symbol": symbol, "filename": symbol_to_filename(symbol) + ".html"}
            for symbol in linked
        ]
