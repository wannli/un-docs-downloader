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
│   ├── patterns.yaml         # Document patterns to discover
│   └── igov.yaml             # IGov decision configuration
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
│   ├── igov.py               # IGov decision synchronization
│   └── templates/            # Jinja2 HTML templates
│       └── static/           # Static site templates (Tailwind CSS)
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
2. Enrich documents with signal paragraphs and metadata
3. Generate the interactive signal browser (`index.html`)
4. Generate signal documentation (`signals-info.html`)
5. Generate IGov decision pages (`igov/`)
6. Optionally generate detailed pages (per-signal, per-pattern, matrix, provenance)
7. Create machine-readable exports (`data.json`, `search-index.json`)
8. Apply Jinja2 templates with Tailwind CSS for consistent styling

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
docs/                      (static website)
├── index.html             (interactive signal browser)
├── signals-info.html      (signal documentation)
├── igov/                  (IGov decision pages)
├── signals/               (per-signal detail pages)
├── patterns/              (per-pattern filtered pages)
├── matrix/                (pattern × signal combinations)
├── provenance/            (resolution origin analysis)
├── data.json              (machine-readable export)
└── search-index.json      (client-side search index)
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

### igov.yaml

Defines defaults for the IGov decisions pipeline:

```yaml
igov:
  session: 80
  series_starts:
    - 401
    - 501
```

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
| `--max-documents` | Limit number of documents to process (for testing/development) |

#### Testing with limited documents

When developing or testing changes to the pipeline, you can speed up generation by processing only a subset of documents:

```bash
mandate generate \
  --config ./config \
  --data ./data \
  --output ./docs \
  --max-documents 10 \
  --verbose
```

This processes only the first 10 documents, making iteration much faster during development.

### mandate igov-sync

Sync IGov General Assembly decisions into a separate data store.

```bash
mandate igov-sync \
  --session 80 \
  --config ./config \
  --data ./data \
  --verbose
```

| Option | Description |
|--------|-------------|
| `--session` | General Assembly session number (defaults to config) |
| `--session-label` | Override IGov session label string |
| `--series-start` | Decision number series start (repeatable) |
| `--config` | Directory containing igov.yaml |
| `--data` | Base data directory (stores in data/igov/) |
| `--verbose` | Log new/updated decisions |

### mandate igov-signals

Generate a standalone signal browser for IGov decisions (proof of concept).

```bash
mandate igov-signals \
  --session 80 \
  --config ./config \
  --data ./data \
  --output ./docs/igov
```

| Option | Description |
|--------|-------------|
| `--session` | General Assembly session number (defaults to config) |
| `--config` | Directory containing checks.yaml and igov.yaml |
| `--data` | Base data directory (reads from data/igov/) |
| `--output` | Output directory for the IGov signal browser |

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

The pipeline uses a granular, event-driven workflow architecture with multiple independent workflows:

### discover.yml

- **Trigger**: Hourly schedule + manual dispatch
- **Action**: Run `mandate discover`, download new PDFs, commit to `data/pdfs/`
- **Result**: New documents discovered and downloaded

### generate.yml

- **Trigger**: Changes to data/linked/, config/, or src/
- **Action**: Generate static site and commit to `docs/`
- **Result**: Static website updated

### build-session.yml

- **Trigger**: Manual dispatch for complete historical UN sessions
- **Action**: Process entire past sessions (download → extract → detect → link → generate)
- **Result**: Session-specific pages in `docs/sessions/`

**Workflow Chain:**
```
Schedule (hourly)
    ↓
discover.yml → extract.yml → detect.yml → link.yml → generate.yml
```

### Testing Mode for Faster Iteration

For development and testing, you can speed up the generate workflow by setting the `MAX_DOCUMENTS` repository variable:

1. Go to repository Settings → Secrets and variables → Actions → Variables
2. Create a new variable named `MAX_DOCUMENTS`
3. Set the value to a small number (e.g., `10`, `50`, `100`)
4. The workflow will now process only that many documents

**Example:**
- `MAX_DOCUMENTS=10` - Process only 10 documents (very fast for testing)
- `MAX_DOCUMENTS=100` - Process 100 documents (good for development)
- Empty or unset - Process all documents (production mode)

To return to production mode, simply delete the variable or leave it empty.

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

PASS 2: Fuzzy Title Matching
  FOR EACH unlinked resolution:
    FOR EACH proposal:
      IF fuzzy_match(title) >= 85%:
        confidence = similarity + (0.05 IF agenda_overlap)
        LINK(resolution → proposal, confidence)
```

## Generated Website Structure

### Public Pages

| Page | Purpose |
|------|---------|
| `index.html` | Interactive signal browser with search, filtering, and document expansion |
| `signals-info.html` | Documentation of signal types, trigger phrases, and detection methodology |
| `igov/` | IGov decision pages (redirects to main browser with decision type filter) |
| `data.json` | Machine-readable JSON export of all documents and signals |

### Internal/Detailed Pages (optional, skippable via `SKIP_DETAILED_PAGES`)

| Page | Purpose |
|------|---------|
| `signals/{signal}.html` | Documents filtered by specific signal type |
| `patterns/{pattern}.html` | Documents matching a specific discovery pattern |
| `matrix/{pattern}_{signal}.html` | Pattern × signal intersection view |
| `provenance/index.html` | Resolution origin analysis by committee |
| `search-index.json` | Client-side search index |

## Dependencies

**Core:**
- `requests` - HTTP requests to UN API
- `pymupdf` - PDF text extraction
- `pyyaml` - YAML configuration parsing
- `jinja2` - HTML template rendering
- `rapidfuzz` - Fuzzy string matching

**Development:**
- `pytest` - Testing framework
- `pytest-mock` - Mocking support

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

## Code Review Findings

A comprehensive code review was conducted to identify legacy issues, inconsistencies, and improvement opportunities across the codebase and static page generation. Below is a summary of findings and actions taken.

### Issues Resolved

1. **Dead template blocks removed**: 17 child templates defined a `{% block nav_signals %}` block that was never used by `base.html`. Additionally, documents and debug templates defined 6 orphan blocks (`nav_documents`, `nav_debug`, `nav_linking`, `nav_orphans`, `nav_fuzzy`, `nav_extraction`) that had no corresponding use in the base template header. All have been removed.

2. **Redundant nav overrides cleaned up**: Root-level templates (`signals_unified_explorer.html`, `signals_info.html`, etc.) were overriding nav blocks with values identical to `base.html` defaults. These redundant overrides were removed.

3. **Deprecated functions removed**: Three deprecated/dead functions were removed from `generation.py`:
   - `generate_index_page()` — empty stub (returned immediately)
   - `generate_sessions_index_page()` — empty stub
   - `generate_unified_signals_page()` — generated `signals.html` but was never called from `generate_site()`

4. **Duplicate output eliminated**: `index.html` and `signals-unified.html` were identical copies. The duplicate `signals-unified.html` is no longer generated; `index.html` is the canonical entry point.

5. **Unused CDN dependency removed**: `lunr.js` was imported in `base.html` but never used by any template. Client-side search uses manual string matching instead. The unused import was removed to improve page load time.

6. **Stale IGov redirect fixed**: The IGov redirect page pointed to `../signals-unified.html` which is no longer generated. Updated to `../?type=decision`.

7. **README outdated sections updated**: Generated Website Structure table, Data Flow diagram, Stage 5 description, and GitHub Actions section were updated to reflect the current state of the project.

### Known Issues (tracked as GitHub issues)

The following items were identified during the review but are tracked as separate issues for future work:

- Signal color definitions are hardcoded in multiple locations (templates and `generation.py`)
- Filter UI patterns differ between the main explorer (pill buttons with JS data loading) and the older `signals_unified.html` template (HTML multiselect with server-rendered documents)
- The `signals_unified.html` template is only used by `generate_session_unified_signals_page()` for historical sessions, while `signals_unified_explorer.html` is used for the main page — two different rendering approaches for similar content
- `search-index.json` is generated but not consumed by any client-side code
- The `generate_site_verbose()` function largely duplicates `generate_site()` with callback additions, presenting a maintenance burden
- `generation.py` is over 1900 lines long and could benefit from being split into smaller modules

## License

MIT License
