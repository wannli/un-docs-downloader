# Mandate Pipeline

from .downloader import download_document
from .extractor import extract_text, extract_operative_paragraphs, extract_lettered_paragraphs
from .detection import load_checks, run_checks
from .discovery import load_patterns, generate_symbols, discover_documents

__all__ = [
    "download_document",
    "extract_text",
    "extract_operative_paragraphs",
    "extract_lettered_paragraphs",
    "load_checks",
    "run_checks",
    "load_patterns",
    "generate_symbols",
    "discover_documents",
]
