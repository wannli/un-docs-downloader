"""Document linking: connect resolutions to their source proposals."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# UN Digital Library API for MARC XML metadata
UNDL_SEARCH_URL = "https://digitallibrary.un.org/search"
UNDL_TIMEOUT = 30  # seconds
MARC_NS = {"marc": "http://www.loc.gov/MARC21/slim"}
CACHE_DIR = Path("data/cache/undl")

# Committee names for display
COMMITTEE_NAMES = {
    "Plenary": "Plenary (General Assembly)",
    "C1": "First Committee (Disarmament)",
    "C2": "Second Committee (Economic & Financial)",
    "C3": "Third Committee (Social, Humanitarian & Cultural)",
    "C4": "Fourth Committee (Decolonization)",
    "C5": "Fifth Committee (Administrative & Budgetary)",
    "C6": "Sixth Committee (Legal)",
    "Unknown": "Unknown Origin",
}

# Global linking audit storage
_linking_audit: dict[str, dict[str, Any]] = {}

_SESSION = None


def _get_session() -> requests.Session:
    """Get or create a reusable requests session with retries."""
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        _SESSION.mount("https://", HTTPAdapter(max_retries=retries))
    return _SESSION


def fetch_undl_metadata(symbol: str) -> dict | None:
    """
    Fetch resolution metadata from UN Digital Library.

    Queries the UNDL search API for the given symbol and parses the MARC XML
    response to extract related document symbols from tag 993.

    Includes caching and rate limiting.

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
    # 1. Check cache
    cached = _get_cached_metadata(symbol)
    if cached:
        return cached

    params = {
        "ln": "en",
        "of": "xm",  # MARC XML output format
        "p": symbol,
        "rg": "5",  # limit results
    }

    # 2. Use reused session
    session = _get_session()

    try:
        resp = session.get(UNDL_SEARCH_URL, params=params, timeout=UNDL_TIMEOUT)
        resp.raise_for_status()

        result = _parse_undl_marc_xml(resp.text, symbol)

        if result:
            _save_cached_metadata(symbol, result)

        # 3. Be polite
        time.sleep(1)

        return result

    except requests.RequestException as e:
        logger.warning("Failed to fetch UNDL metadata for %s: %s", symbol, e)
        return None


def _get_cache_path(symbol: str) -> Path:
    """Generate a safe cache file path for a symbol."""
    # Use MD5 hash to handle special characters and length
    symbol_hash = hashlib.md5(symbol.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{symbol_hash}.json"


def _get_cached_metadata(symbol: str) -> dict | None:
    """Retrieve metadata from local cache if it exists."""
    cache_path = _get_cache_path(symbol)
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read cache for %s: %s", symbol, e)
    return None


def _save_cached_metadata(symbol: str, data: dict) -> None:
    """Save metadata to local cache."""
    if not data:
        return

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = _get_cache_path(symbol)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("Failed to save cache for %s: %s", symbol, e)


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


def derive_origin_from_symbol(symbol: str) -> str:
    """
    Derive the origin committee from a proposal symbol.

    Args:
        symbol: UN document symbol (e.g., "A/C.3/80/L.42", "A/80/L.50")

    Returns:
        Origin code: "Plenary", "C1", "C2", "C3", "C4", "C5", "C6", or "Unknown"
    """
    upper = symbol.upper()
    if "/C.1/" in upper:
        return "C1"
    if "/C.2/" in upper:
        return "C2"
    if "/C.3/" in upper:
        return "C3"
    if "/C.4/" in upper:
        return "C4"
    if "/C.5/" in upper:
        return "C5"
    if "/C.6/" in upper:
        return "C6"
    if "/L." in upper:
        # A/80/L.X pattern = Plenary draft
        return "Plenary"
    return "Unknown"


def derive_resolution_origin(doc: dict) -> str:
    """
    Derive the origin committee for a resolution based on its linked proposals.

    Args:
        doc: Resolution document dict with 'linked_proposals' field

    Returns:
        Origin code: "Plenary", "C1"-"C6", or "Unknown"
    """
    if not is_resolution(doc.get("symbol", "")):
        return "Unknown"

    linked = doc.get("linked_proposals", [])
    if not linked:
        return "Unknown"

    # Use the first linked proposal's origin
    first_proposal = linked[0]
    proposal_symbol = first_proposal.get("symbol", "") if isinstance(first_proposal, dict) else first_proposal
    return derive_origin_from_symbol(proposal_symbol)


def get_linking_audit() -> dict[str, dict[str, Any]]:
    """Return the current linking audit data."""
    return _linking_audit.copy()


def clear_linking_audit() -> None:
    """Clear the linking audit data."""
    global _linking_audit
    _linking_audit = {}


def get_undl_cache_stats() -> dict[str, Any]:
    """Get statistics about the UNDL metadata cache."""
    if not CACHE_DIR.exists():
        return {"total_entries": 0, "cache_size_bytes": 0, "entries": []}

    entries = []
    total_size = 0

    for cache_file in CACHE_DIR.glob("*.json"):
        try:
            stat = cache_file.stat()
            total_size += stat.st_size
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries.append({
                "symbol": data.get("symbol", "Unknown"),
                "file": cache_file.name,
                "size_bytes": stat.st_size,
                "mtime": stat.st_mtime,
                "draft_symbols": data.get("draft_symbols", []),
                "related_symbols": data.get("related_symbols", []),
            })
        except (json.JSONDecodeError, OSError):
            continue

    return {
        "total_entries": len(entries),
        "cache_size_bytes": total_size,
        "entries": sorted(entries, key=lambda x: x.get("mtime", 0), reverse=True),
    }


def link_documents(documents: list[dict], use_undl_metadata: bool = True) -> None:
    """
    Link resolutions to proposals using explicit references.

    Pass 0 (optional): Fetch base proposal from UN Digital Library metadata.
    Pass 1: Link by symbol references found in PDF text.

    Args:
        documents: List of document dictionaries with at least 'symbol' key.
        use_undl_metadata: If True, query UN Digital Library for authoritative
            base proposal symbols before falling back to PDF text extraction.
    """
    global _linking_audit
    clear_linking_audit()

    proposals_by_symbol = {doc["symbol"]: doc for doc in documents if is_proposal(doc["symbol"])}
    proposals = list(proposals_by_symbol.values())

    for doc in documents:
        doc.setdefault("linked_resolution_symbol", None)
        doc.setdefault("linked_proposal_symbols", [])

    # Initialize audit entries for all resolutions
    for doc in documents:
        if is_resolution(doc["symbol"]):
            _linking_audit[doc["symbol"]] = {
                "symbol": doc["symbol"],
                "title": doc.get("title", ""),
                "pass0_undl": {"attempted": False, "found": False, "refs": [], "linked": []},
                "pass1_symbol_refs": {"attempted": False, "refs_in_text": [], "linked": []},
                "final_method": None,
                "final_linked": [],
                "confidence": 0,
            }

    # Pass 0: UN Digital Library metadata lookup (authoritative source)
    if use_undl_metadata:
        for doc in documents:
            if not is_resolution(doc["symbol"]):
                continue
            # Skip if already linked
            if doc.get("linked_proposal_symbols"):
                continue

            audit = _linking_audit[doc["symbol"]]
            audit["pass0_undl"]["attempted"] = True

            metadata = fetch_undl_metadata(doc["symbol"])
            if metadata is None or not metadata.get("draft_symbols"):
                continue

            draft_symbols = metadata["draft_symbols"]
            audit["pass0_undl"]["refs"] = draft_symbols
            audit["pass0_undl"]["found"] = True

            # Filter to only include proposals we have locally
            linked = [s for s in draft_symbols if s in proposals_by_symbol]
            audit["pass0_undl"]["linked"] = linked

            if linked:
                doc["linked_proposal_symbols"] = linked
                audit["final_method"] = "undl"
                audit["final_linked"] = linked
                audit["confidence"] = 100

                # Mark the proposals as linked to this resolution
                for ref in linked:
                    proposal = proposals_by_symbol.get(ref)
                    if proposal and proposal.get("linked_resolution_symbol") is None:
                        proposal["linked_resolution_symbol"] = doc["symbol"]

    # Pass 1: Symbol references from PDF text
    for doc in documents:
        if not is_resolution(doc["symbol"]):
            continue

        audit = _linking_audit[doc["symbol"]]
        references = doc.get("symbol_references", [])
        proposal_refs = [ref for ref in references if is_proposal(ref)]
        audit["pass1_symbol_refs"]["refs_in_text"] = proposal_refs

        # Skip if already linked via UNDL metadata
        if doc.get("linked_proposal_symbols"):
            continue

        audit["pass1_symbol_refs"]["attempted"] = True
        linked = [ref for ref in proposal_refs if ref in proposals_by_symbol]
        audit["pass1_symbol_refs"]["linked"] = linked

        if not linked:
            continue

        doc["linked_proposal_symbols"] = linked
        audit["final_method"] = "symbol_ref"
        audit["final_linked"] = linked
        audit["confidence"] = 100

        for ref in linked:
            proposal = proposals_by_symbol.get(ref)
            if proposal is None:
                continue
            if proposal.get("linked_resolution_symbol") is None:
                proposal["linked_resolution_symbol"] = doc["symbol"]

def annotate_linkage(documents: list[dict]) -> None:
    """Annotate documents with adopted draft status and linked proposals."""
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

    # Clean up intermediate fields
    for doc in documents:
        doc.pop("linked_resolution_symbol", None)
        doc.pop("linked_proposal_symbols", None)
