"""Lineage analysis and caching for document linkage data."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rapidfuzz import fuzz

from .extractor import extract_text


SYMBOL_PATTERN = re.compile(r"\b[A-Z](?:/[A-Z0-9.]+)+\b")


def symbol_to_filename(symbol: str) -> str:
    """Convert a UN symbol to a safe filename."""
    return symbol.replace("/", "_")


def filename_to_symbol(filename: str) -> str:
    """Convert a filename back to UN symbol."""
    stem = filename.replace(".pdf", "")
    return stem.replace("_", "/")


def compute_last_modified_hash(pdf_path: Path) -> str:
    """Compute a hash from the PDF's last-modified timestamp and size."""
    stat = pdf_path.stat()
    payload = f"{stat.st_mtime_ns}:{stat.st_size}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def extract_linked_symbols(text: str, symbol: str) -> list[str]:
    """Extract referenced document symbols from text."""
    matches = {normalize_symbol(match) for match in SYMBOL_PATTERN.findall(text)}
    matches.discard(normalize_symbol(symbol))
    return sorted(matches)


def load_lineage_cache(cache_path: Path) -> dict:
    """Load lineage cache from disk."""
    cache_path = Path(cache_path)
    if not cache_path.exists():
        return {"generated_at": None, "documents": {}}

    with open(cache_path) as f:
        data = json.load(f)

    if "documents" not in data:
        data["documents"] = {}
    return data


def save_lineage_cache(cache_path: Path, cache: dict) -> None:
    """Persist lineage cache to disk."""
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    cache["generated_at"] = datetime.now(timezone.utc).isoformat()
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2)


def update_lineage_cache(data_dir: Path, cache_path: Path | None = None) -> dict:
    """Update lineage cache for PDFs under the data directory."""
    data_dir = Path(data_dir)
    cache_path = cache_path or (data_dir / "lineage.json")
    cache = load_lineage_cache(cache_path)

    pdfs_dir = data_dir / "pdfs"
    documents = cache.get("documents", {})
    existing_symbols = set()
    updated = 0
    reused = 0

    if not pdfs_dir.exists():
        save_lineage_cache(cache_path, {"documents": {}})
        return {"total": 0, "updated": 0, "reused": 0, "removed": 0}

    for pdf_path in pdfs_dir.glob("*.pdf"):
        symbol = filename_to_symbol(pdf_path.stem)
        existing_symbols.add(symbol)
        last_modified_hash = compute_last_modified_hash(pdf_path)

        cached = documents.get(symbol)
        if cached and cached.get("last_modified_hash") == last_modified_hash:
            reused += 1
            continue

        text = extract_text(pdf_path)
        links = extract_linked_symbols(text, symbol)
        classification = classify_symbol(symbol)

        documents[symbol] = {
            "last_modified_hash": last_modified_hash,
            "classification": classification,
            "links": links,
        }
        updated += 1

    removed_symbols = [symbol for symbol in documents.keys() if symbol not in existing_symbols]
    for symbol in removed_symbols:
        del documents[symbol]

    cache["documents"] = documents
    save_lineage_cache(cache_path, cache)

    return {
        "total": len(existing_symbols),
        "updated": updated,
        "reused": reused,
        "removed": len(removed_symbols),
    }


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


def annotate_lineage(documents: list[dict]) -> None:
    """Annotate documents with adopted draft status and lineage metadata."""
    base_proposals = {doc["symbol"]: doc for doc in documents if is_base_proposal_doc(doc)}

    for doc in documents:
        doc["is_adopted_draft"] = False
        doc["adopted_by"] = None
        doc["lineage_proposals"] = []

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
        doc["lineage_proposals"] = [
            {"symbol": symbol, "filename": symbol_to_filename(symbol) + ".html"}
            for symbol in linked
        ]
