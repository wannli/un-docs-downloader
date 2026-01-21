"""Lineage analysis and caching for document linkage data."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .extractor import extract_text


SYMBOL_PATTERN = re.compile(r"\b[A-Z](?:/[A-Z0-9.]+)+\b")


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
