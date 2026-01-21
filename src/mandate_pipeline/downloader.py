"""Download documents from the UN Official Document System."""

from pathlib import Path

import requests


def symbol_to_filename(symbol: str) -> str:
    """Convert a UN symbol to a safe filename."""
    return symbol.replace("/", "_") + ".pdf"


def file_exists_for_symbol(symbol: str, output_dir: Path) -> bool:
    """
    Check if a PDF file already exists locally for this symbol.

    Args:
        symbol: UN document symbol (e.g., "A/RES/77/1")
        output_dir: Directory where PDFs are stored

    Returns:
        True if file exists locally, False otherwise
    """
    output_path = Path(output_dir) / symbol_to_filename(symbol)
    return output_path.exists() and output_path.stat().st_size > 0


def download_document(symbol: str, output_dir: Path, language: str = "en", skip_existing: bool = True) -> Path:
    """
    Download a UN document by its symbol and save it locally.

    Args:
        symbol: UN document symbol (e.g., "A/RES/77/1")
        output_dir: Directory to save the downloaded file
        language: Language code (default: "en")
        skip_existing: If True, skip download if file already exists (default: True)

    Returns:
        Path to the downloaded file
    """
    output_path = Path(output_dir) / symbol_to_filename(symbol)

    # Skip if file already exists
    if skip_existing and output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    # Build the download URL (API endpoint that redirects to PDF)
    url = build_download_url(symbol, language)

    # Download the file, following redirects
    response = requests.get(url, allow_redirects=True)
    response.raise_for_status()

    # Save the file
    output_path.write_bytes(response.content)

    return output_path


def build_download_url(symbol: str, language: str = "en") -> str:
    """
    Build the download URL for a UN document.

    Args:
        symbol: UN document symbol (e.g., "A/RES/77/1")
        language: Language code (default: "en")

    Returns:
        URL to download the document PDF
    """
    # Use the UN documents API which redirects to the actual PDF
    return f"https://documents.un.org/api/symbol/access?s={symbol}&l={language}&t=pdf"
