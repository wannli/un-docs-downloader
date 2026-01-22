"""FastAPI web interface for Mandate Pipeline."""

import asyncio
import json
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from .downloader import download_document
from .extractor import extract_text, extract_operative_paragraphs
from .detection import load_checks, run_checks
from .discovery import load_patterns, generate_symbols, document_exists

app = FastAPI(title="Mandate Pipeline", description="Download and analyze UN documents")

# Templates
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# Default paths - use the project root (where checks.yaml and patterns.yaml are)
DEFAULT_CONFIG_DIR = Path(__file__).parent.parent.parent.parent
DEFAULT_OUTPUT_DIR = Path("/tmp/un-docs")

# Resolve to absolute path
if not (DEFAULT_CONFIG_DIR / "checks.yaml").exists():
    # Try current working directory as fallback
    DEFAULT_CONFIG_DIR = Path.cwd()

# In-memory state for running jobs
jobs = {}


def get_checks_path() -> Path:
    return DEFAULT_CONFIG_DIR / "checks.yaml"


def get_patterns_path() -> Path:
    return DEFAULT_CONFIG_DIR / "patterns.yaml"


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with dashboard."""
    checks = []
    patterns = []
    
    checks_path = get_checks_path()
    if checks_path.exists():
        checks = load_checks(checks_path)
    
    patterns_path = get_patterns_path()
    if patterns_path.exists():
        patterns = load_patterns(patterns_path)
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "checks": checks,
        "patterns": patterns,
        "jobs": jobs,
    })


@app.get("/checks", response_class=HTMLResponse)
async def checks_page(request: Request):
    """View and edit checks configuration."""
    checks_path = get_checks_path()
    checks_yaml = ""
    checks = []
    
    if checks_path.exists():
        checks_yaml = checks_path.read_text()
        checks = load_checks(checks_path)
    
    return templates.TemplateResponse("checks.html", {
        "request": request,
        "checks": checks,
        "checks_yaml": checks_yaml,
    })


@app.post("/checks")
async def save_checks(request: Request, checks_yaml: str = Form(...)):
    """Save checks configuration."""
    checks_path = get_checks_path()
    
    # Validate YAML
    try:
        yaml.safe_load(checks_yaml)
    except yaml.YAMLError as e:
        return templates.TemplateResponse("checks.html", {
            "request": request,
            "checks": [],
            "checks_yaml": checks_yaml,
            "error": f"Invalid YAML: {e}",
        })
    
    checks_path.write_text(checks_yaml)
    checks = load_checks(checks_path)
    
    return templates.TemplateResponse("checks.html", {
        "request": request,
        "checks": checks,
        "checks_yaml": checks_yaml,
        "success": "Checks saved successfully!",
    })


@app.get("/patterns", response_class=HTMLResponse)
async def patterns_page(request: Request):
    """View and edit patterns configuration."""
    patterns_path = get_patterns_path()
    patterns_yaml = ""
    patterns = []
    
    if patterns_path.exists():
        patterns_yaml = patterns_path.read_text()
        patterns = load_patterns(patterns_path)
    
    return templates.TemplateResponse("patterns.html", {
        "request": request,
        "patterns": patterns,
        "patterns_yaml": patterns_yaml,
    })


@app.post("/patterns")
async def save_patterns(request: Request, patterns_yaml: str = Form(...)):
    """Save patterns configuration."""
    patterns_path = get_patterns_path()
    
    # Validate YAML
    try:
        yaml.safe_load(patterns_yaml)
    except yaml.YAMLError as e:
        return templates.TemplateResponse("patterns.html", {
            "request": request,
            "patterns": [],
            "patterns_yaml": patterns_yaml,
            "error": f"Invalid YAML: {e}",
        })
    
    patterns_path.write_text(patterns_yaml)
    patterns = load_patterns(patterns_path)
    
    return templates.TemplateResponse("patterns.html", {
        "request": request,
        "patterns": patterns,
        "patterns_yaml": patterns_yaml,
        "success": "Patterns saved successfully!",
    })


@app.get("/run", response_class=HTMLResponse)
async def run_page(request: Request):
    """Run pipeline page."""
    patterns = []
    patterns_path = get_patterns_path()
    if patterns_path.exists():
        patterns = load_patterns(patterns_path)
    
    return templates.TemplateResponse("run.html", {
        "request": request,
        "patterns": patterns,
    })


@app.get("/api/run/{pattern_index}")
async def run_pipeline_stream(pattern_index: int, max_misses: int = 3):
    """Run pipeline and stream results via Server-Sent Events."""
    patterns_path = get_patterns_path()
    checks_path = get_checks_path()
    
    if not patterns_path.exists():
        return {"error": "No patterns configured"}
    
    patterns = load_patterns(patterns_path)
    if pattern_index >= len(patterns):
        return {"error": "Invalid pattern index"}
    
    pattern = patterns[pattern_index]
    checks = load_checks(checks_path) if checks_path.exists() else []
    
    output_dir = DEFAULT_OUTPUT_DIR / pattern["name"].replace(" ", "_")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    async def generate():
        consecutive_misses = 0
        found_count = 0
        
        for symbol in generate_symbols(pattern):
            # Check if document exists
            if document_exists(symbol):
                consecutive_misses = 0
                found_count += 1
                
                yield f"data: {json.dumps({'type': 'found', 'symbol': symbol})}\n\n"
                
                try:
                    # Download
                    pdf_path = download_document(symbol, output_dir=output_dir)
                    yield f"data: {json.dumps({'type': 'downloaded', 'symbol': symbol, 'size': pdf_path.stat().st_size})}\n\n"
                    
                    # Extract
                    text = extract_text(pdf_path)
                    paragraphs = extract_operative_paragraphs(text)
                    yield f"data: {json.dumps({'type': 'extracted', 'symbol': symbol, 'paragraphs': len(paragraphs)})}\n\n"
                    
                    # Run checks
                    if checks:
                        results = run_checks(paragraphs, checks)
                        if results:
                            yield f"data: {json.dumps({'type': 'signals', 'symbol': symbol, 'results': {str(k): v for k, v in results.items()}})}\n\n"
                    
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'error', 'symbol': symbol, 'error': str(e)})}\n\n"
                
                # Small delay to not overwhelm
                await asyncio.sleep(0.1)
            else:
                consecutive_misses += 1
                yield f"data: {json.dumps({'type': 'miss', 'symbol': symbol, 'consecutive': consecutive_misses})}\n\n"
                
                if consecutive_misses >= max_misses:
                    yield f"data: {json.dumps({'type': 'complete', 'found': found_count})}\n\n"
                    return
        
        yield f"data: {json.dumps({'type': 'complete', 'found': found_count})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


@app.get("/api/preview/{pattern_index}")
async def preview_pattern(pattern_index: int, count: int = 10):
    """Preview symbols that would be generated by a pattern."""
    patterns_path = get_patterns_path()
    if not patterns_path.exists():
        return {"error": "No patterns configured"}
    
    patterns = load_patterns(patterns_path)
    if pattern_index >= len(patterns):
        return {"error": "Invalid pattern index"}
    
    pattern = patterns[pattern_index]
    symbols = list(generate_symbols(pattern, count=count))
    
    return {"pattern": pattern["name"], "symbols": symbols}


@app.get("/documents", response_class=HTMLResponse)
async def documents_list(request: Request):
    """List all downloaded documents with signal summaries."""
    import re
    
    documents = []
    
    # Load checks once
    checks_path = get_checks_path()
    checks = load_checks(checks_path) if checks_path.exists() else []
    
    # Create a mapping from signal name to check info
    signal_info = {check["signal"]: check for check in checks}
    
    # Scan output directories for PDFs
    if DEFAULT_OUTPUT_DIR.exists():
        for subdir in DEFAULT_OUTPUT_DIR.iterdir():
            if subdir.is_dir():
                for pdf_file in subdir.glob("*.pdf"):
                    # Get symbol from filename
                    symbol = pdf_file.stem.replace("_", "/")
                    
                    # Extract and analyze document
                    try:
                        text = extract_text(pdf_file)
                        paragraphs = extract_operative_paragraphs(text)
                        signals = run_checks(paragraphs, checks) if checks else {}
                        
                        # Count signals by type and store paragraph details
                        signal_counts = {}
                        signal_paras = {}  # Which paragraphs have each signal (with text)
                        for para_num, sigs in signals.items():
                            for sig in sigs:
                                signal_counts[sig] = signal_counts.get(sig, 0) + 1
                                if sig not in signal_paras:
                                    signal_paras[sig] = []
                                signal_paras[sig].append({
                                    "num": para_num,
                                    "text": paragraphs.get(para_num, "")
                                })
                        
                        # Count paragraphs with signals
                        paras_with_signals = len(signals)
                        
                    except Exception:
                        paragraphs = {}
                        signals = {}
                        signal_counts = {}
                        signal_paras = {}
                        paras_with_signals = 0
                    
                    documents.append({
                        "symbol": symbol,
                        "filename": pdf_file.name,
                        "path": str(pdf_file),
                        "size": pdf_file.stat().st_size,
                        "folder": subdir.name,
                        "num_paragraphs": len(paragraphs),
                        "signal_counts": signal_counts,
                        "signal_paras": signal_paras,
                        "paras_with_signals": paras_with_signals,
                        "total_signals": sum(signal_counts.values()),
                    })
    
    # Sort by symbol - extract all numbers for proper sorting
    def sort_key(doc):
        # Extract all numbers from symbol for sorting
        # e.g., "A/80/L.42" -> (80, 42), "A/C.1/80/L.5" -> (1, 80, 5)
        numbers = re.findall(r'\d+', doc["symbol"])
        return [int(n) for n in numbers] if numbers else [0]
    
    documents.sort(key=sort_key)
    
    # Summary stats
    total_docs = len(documents)
    docs_with_signals = len([d for d in documents if d["signal_counts"]])
    
    # Aggregate signal stats across all documents
    total_signal_counts = {}
    for doc in documents:
        for sig, count in doc["signal_counts"].items():
            total_signal_counts[sig] = total_signal_counts.get(sig, 0) + count
    
    return templates.TemplateResponse("documents.html", {
        "request": request,
        "documents": documents,
        "total_docs": total_docs,
        "docs_with_signals": docs_with_signals,
        "checks": checks,
        "total_signal_counts": total_signal_counts,
    })


@app.get("/documents/{folder}/{filename}", response_class=HTMLResponse)
async def document_detail(request: Request, folder: str, filename: str):
    """View a specific document with paragraphs and signals."""
    pdf_path = DEFAULT_OUTPUT_DIR / folder / filename
    
    if not pdf_path.exists():
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Document not found: {filename}",
        })
    
    # Get symbol from filename
    symbol = pdf_path.stem.replace("_", "/")
    
    # Extract text and paragraphs
    text = extract_text(pdf_path)
    paragraphs = extract_operative_paragraphs(text)
    
    # Load and run checks
    checks_path = get_checks_path()
    checks = load_checks(checks_path) if checks_path.exists() else []
    signals = run_checks(paragraphs, checks) if checks else {}
    
    # Build paragraph data with signals
    paragraph_data = []
    for num in sorted(paragraphs.keys()):
        paragraph_data.append({
            "number": num,
            "text": paragraphs[num],
            "signals": signals.get(num, []),
        })
    
    return templates.TemplateResponse("document_detail.html", {
        "request": request,
        "symbol": symbol,
        "filename": filename,
        "folder": folder,
        "pdf_path": str(pdf_path),
        "paragraphs": paragraph_data,
        "total_paragraphs": len(paragraphs),
        "total_signals": sum(len(s) for s in signals.values()),
        "checks": checks,
    })


@app.get("/pdf/{folder}/{filename}")
async def serve_pdf(folder: str, filename: str):
    """Serve a PDF file."""
    pdf_path = DEFAULT_OUTPUT_DIR / folder / filename
    
    if not pdf_path.exists():
        return {"error": "File not found"}
    
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=filename,
    )


def run_server(host: str = "127.0.0.1", port: int = 8000):
    """Run the web server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
