# Mandate Pipeline

A document discovery and analysis system that automatically downloads UN General Assembly resolutions and proposals, extracts text, identifies mandate-related signals, and generates an interactive static website.

## Overview

The Mandate Pipeline automates the process of:
1. **Discovering** new UN documents from the UN ODS API
2. **Extracting** text and structure from PDFs
3. **Detecting** mandate-related signals using configurable phrase matching
4. **Linking** related documents (resolutions to proposals)
5. **Generating** a static website for browsing and analysis

## Quick Start

```bash
# Install dependencies
pip install -e .

# Run full pipeline (all five stages)
mandate build --config ./config --data ./data --output ./docs --verbose

# Or run specific stages
mandate discover --config ./config --data ./data --verbose          # Stage 1: Discovery
mandate generate --config ./config --data ./data --output ./docs   # Stages 2-5: Extraction, Detection, Linking, Generation
```

## Project Structure

```
mandate-pipeline/
├── config/                    # Configuration files
│   ├── checks.yaml           # Signal detection rules
│   └── patterns.yaml         # Document patterns to discover
├── data/                      # Persistent data
│   ├── pdfs/                 # Downloaded PDF documents
│   └── state.json            # Discovery sync state
├── docs/                      # Generated static website
├── src/mandate_pipeline/      # Core Python package
│   ├── cli.py                # Command-line interface
│   ├── discovery.py          # Stage 1: Document discovery
│   ├── downloader.py         # PDF download from UN servers
│   ├── extractor.py          # Stage 2: Text extraction
│   ├── detection.py          # Stage 3: Signal detection
│   ├── linking.py            # Stage 4: Document linkage
│   ├── generation.py         # Stage 5: Site generation
│   └── templates/            # Jinja2 HTML templates
└── tests/                     # Test suite
```

## Pipeline Architecture

The pipeline consists of five sequential stages that transform UN documents from discovery to an interactive website:

### Stage 1: Discovery (`discovery.py`)

The `discover` command finds and downloads new UN documents.

**Process:**
1. Load document patterns from `config/patterns.yaml`
2. For each pattern, generate sequential symbols (e.g., A/80/L.1, A/80/L.2, ...)
3. Check if each document exists via UN ODS API
4. Download found PDFs to `data/pdfs/`
5. Stop after 3 consecutive 404s (configurable)
6. Save progress to `data/state.json`

**Key Features:**
- **Incremental**: Only checks documents newer than last sync
- **Adaptive**: Resets miss counter on successful finds (handles numbering gaps)
- **Stateful**: Progress persisted between runs

### Stage 2: Extraction (`extractor.py`)

Extracts structured content from PDF documents.

**Process:**
- Extract full text using PyMUPDF
- Parse operative paragraphs (numbered sections)
- Extract document title
- Find agenda item references
- Identify UN symbol references

### Stage 3: Detection (`detection.py`)

Identifies mandate-related signals in document text.

**Process:**
- Match phrases from `config/checks.yaml` against paragraphs
- Case-insensitive substring matching
- Each paragraph can trigger multiple signals

### Stage 4: Linking (`linking.py`)

Builds relationships between documents (resolutions ↔ proposals).

**Process:**
1. **Classification**: Classify documents (resolution/proposal/other)
2. **Explicit Linking**: Link via symbol references found in text (100% confidence)
3. **Fuzzy Matching**: Link via title similarity (85%+ threshold)
4. **Annotation**: Mark proposals as "adopted" when linked to resolutions

### Stage 5: Generation (`generation.py`)

Creates the static website and data exports.

**Process:**
1. Load all processed documents
2. Generate HTML pages (index, documents, signals, patterns, matrix)
3. Create machine-readable exports (data.json, search-index.json)
4. Apply Jinja2 templates for consistent styling

## Data Flow

The five stages process data sequentially:

```
UN ODS API
    ↓
[Stage 1: Discovery] → data/state.json
    ↓
data/pdfs/*.pdf
    ↓
[Stage 2: Extraction] → Text, paragraphs, titles, references
    ↓
[Stage 3: Detection] → Matched phrases per paragraph
    ↓
[Stage 4: Linking] → Resolution ↔ Proposal relationships
    ↓
[Stage 5: Generation]
    ↓
docs/                 (static website)
├── index.html       (dashboard)
├── documents/       (individual pages)
├── signals/         (filter by signal)
├── patterns/        (filter by pattern)
├── matrix/          (pattern × signal)
├── data.json        (machine-readable export)
└── search-index.json
```

## Configuration

### patterns.yaml

Defines which document symbols to discover:

```yaml
patterns:
  - name: "General Assembly resolutions"
    template: "A/RES/{session}/{number}"
    session: 80
    start: 1

  - name: "General Assembly proposals"
    template: "A/{session}/L.{number}"
    session: 80
    start: 1

  - name: "C1 proposals"
    template: "A/C.{committee}/{session}/L.{number}"
    committee: 1
    session: 80
    start: 1
```

- `template`: Symbol format with `{variable}` placeholders
- `session`, `committee`: Fixed values substituted into template
- `{number}`: Auto-incrementing counter
- `start`: Initial number for this pattern

### checks.yaml

Defines signal detection rules:

```yaml
checks:
  - signal: "agenda"
    phrases:
      - "decides to include"
      - "decides to place on the provisional agenda"
      - "requests the inclusion"

  - signal: "PGA"
    phrases:
      - "President of the General Assembly"
      - "high-level meeting"

  - signal: "report"
    phrases:
      - "report to the General Assembly"
      - "submit a report"
```

- `signal`: Name of the signal (used in website sections)
- `phrases`: List of phrases to match (case-insensitive)

## CLI Commands

### mandate discover

Discover and download new documents.

```bash
mandate discover \
  --config ./config \
  --data ./data \
  --max-misses 3 \
  --verbose
```

| Option | Description |
|--------|-------------|
| `--config` | Directory containing patterns.yaml |
| `--data` | Directory for state.json and pdfs/ |
| `--max-misses` | Stop after N consecutive 404s (default: 3) |
| `--verbose` | Log each document check |

### mandate generate

Generate static site from downloaded documents.

```bash
mandate generate \
  --config ./config \
  --data ./data \
  --output ./docs \
  --clean-output \
  --verbose
```

| Option | Description |
|--------|-------------|
| `--config` | Directory containing checks.yaml and patterns.yaml |
| `--data` | Directory with pdfs/ subdirectory |
| `--output` | Output directory for static site |
| `--clean-output` | Delete existing output directory contents before generation |
| `--verbose` | Log each document processed |

### mandate build

Run discover + generate (full pipeline).

```bash
mandate build \
  --config ./config \
  --data ./data \
  --output ./docs \
  --clean-output \
  --max-misses 3 \
  --verbose
```

## State Files

### data/state.json

Tracks discovery progress:

```json
{
  "last_sync": "2026-01-20T10:30:45.123456+00:00",
  "patterns": {
    "General Assembly resolutions": {
      "highest_found": 250
    },
    "General Assembly proposals": {
      "highest_found": 185
    }
  }
}
```

### docs/data.json

Complete metadata export for external tools:

```json
{
  "generated_at": "...",
  "checks": [...],
  "documents": [...],
  "stats": {
    "total_documents": 250,
    "documents_with_signals": 120,
    "signal_counts": {"agenda": 45, "report": 78}
  }
}
```

## GitHub Actions Automation

Two workflows automate the pipeline:

### fetch-documents.yml

- **Trigger**: Daily at 6 AM UTC or manual
- **Action**: Run `mandate discover`, commit new PDFs
- **Result**: `data/pdfs/` and `data/state.json` updated

### build-site.yml

- **Trigger**: Changes to data/pdfs/, config/, or src/
- **Action**: Run `mandate generate`, deploy to GitHub Pages
- **Result**: Static website updated

**Workflow Chain:**
```
Schedule (6 AM UTC)
    ↓
fetch-documents.yml
    ↓ (on success)
linkage-analysis.yml
    ↓ (triggers)
build-site.yml
```

## Key Algorithms

### Document Discovery

```
FOR EACH pattern:
  current = state.highest_found + 1
  consecutive_misses = 0

  WHILE consecutive_misses < max_misses:
    symbol = generate_symbol(pattern, current)

    IF exists_locally(symbol):
      current += 1
      CONTINUE

    IF exists_remote(symbol):
      download(symbol)
      consecutive_misses = 0
    ELSE:
      consecutive_misses += 1

    current += 1

  state.highest_found = current - consecutive_misses - 1
```

### Signal Detection

```
FOR EACH paragraph:
  FOR EACH check:
    FOR EACH phrase IN check.phrases:
      IF phrase.lower() IN paragraph.lower():
        signals[paragraph].append(check.signal)
        BREAK  # One match per check
```

### Document Linking

```
PASS 1: Explicit References
  FOR EACH resolution:
    FOR EACH symbol_reference:
      IF symbol_reference IS proposal:
        LINK(resolution → proposal, confidence=1.0)
```

## Generated Website Structure

| Page | Purpose |
|------|---------|
| `index.html` | Dashboard with pattern × signal matrix |
| `documents/index.html` | All documents grouped by pattern |
| `documents/{symbol}.html` | Individual document detail |
| `signals/{signal}.html` | Documents with specific signal |
| `patterns/{pattern}.html` | Documents matching pattern |
| `matrix/{pattern}_{signal}.html` | Pattern × signal intersection |
| `data.json` | Machine-readable metadata |
| `search-index.json` | Client-side search index |

## Dependencies

**Core:**
- `requests` - HTTP requests to UN API
- `pymupdf` - PDF text extraction
- `pyyaml` - YAML configuration parsing
- `jinja2` - HTML template rendering

**Development:**
- `pytest` - Testing framework
- `pytest-mock` - Mocking support

**Optional (web interface):**
- `fastapi` - Web API framework
- `uvicorn` - ASGI server

## Testing

```bash
# Run all tests
pytest tests/

# Run with verbose output
pytest tests/ -v

# Run only integration tests (real API calls)
pytest tests/ -m integration

# Run with coverage
pytest tests/ --cov=src/mandate_pipeline
```

## Extending the System

### Add New Document Patterns

Edit `config/patterns.yaml`:

```yaml
patterns:
  - name: "Security Council resolutions"
    template: "S/RES/{number}"
    start: 2700
```

### Add New Signals

Edit `config/checks.yaml`:

```yaml
checks:
  - signal: "budget"
    phrases:
      - "programme budget implications"
      - "financial implications"
      - "appropriation"
```

### Custom Extraction

Extend `src/mandate_pipeline/extractor.py` (Stage 2) to parse additional data from PDFs.

### Custom Detection Rules

Add new signals in `config/checks.yaml` and extend `src/mandate_pipeline/detection.py` (Stage 3) for custom detection logic.

### Custom Linking

Extend `src/mandate_pipeline/linking.py` (Stage 4) to implement additional document relationship analysis.

### Custom Reports

Extend `src/mandate_pipeline/generation.py` (Stage 5) to generate additional HTML pages or exports.

## License

MIT License
