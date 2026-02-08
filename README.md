# Mandate Pipeline

A document discovery and analysis system that automatically downloads UN General Assembly resolutions and proposals, extracts text, identifies mandate-related signals, and generates an interactive static website.

## 🚀 Deployment

- **Production**: [GitHub Pages](https://wannli.github.io/mandate-pipeline/) (auto-deployed from `master`)
- **PR Previews**: [Vercel](https://vercel.com) (see [VERCEL.md](VERCEL.md) for setup)

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
- **Manual Control**: All workflows support `workflow_dispatch` for manual triggering of specific stages.

### Stage 2: Extraction (`extractor.py`)

Extracts structured content from PDF documents and performs deep cleaning to remove extraction noise.

**Process:**
- Extract full text using PyMUPDF
- Parse operative paragraphs (numbered sections) and lettered paragraphs (a, b, c)
- **Advanced Text Cleaning**: Uses targeted regex to strip PDF extraction artifacts mid-paragraph:
  - Footnote blocks followed by next-page headers
  - Bare page headers (symbol, title, UN doc ID)
  - Trailing plenary meeting meta-information
- Extract document title (multi-line aware)
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
- **Trigger**: Hourly schedule + manual dispatch (`workflow_dispatch`)
- **Action**: Run `mandate discover`, download new PDFs, commit to `data/pdfs/`
- **Result**: New documents discovered and downloaded

### extract.yml, detect.yml, link.yml
- **Trigger**: New files in relevant `data/` subdirectories + manual dispatch (`workflow_dispatch`)
- **Action**: Process documents through extraction, signal detection, and linkage
- **Result**: Structured JSON data committed to the repository

### generate.yml
- **Trigger**: Changes to data/linked/, config/, or src/ + manual dispatch (`workflow_dispatch`)
- **Action**: Generate static site and commit to `docs/`
- **Result**: Static website updated and deployed to GitHub Pages

### build-session.yml

- **Trigger**: Manual dispatch for complete historical UN sessions
- **Action**: Process entire past sessions (download → extract → detect → link → generate)
- **Result**: Session-specific pages in `docs/sessions/`

**Workflow Chain:**
```
Schedule (hourly)
    ↓
discover.yml → extract.yml → detect.yml → link.yml → generate.yml → GitHub Pages
```

## Vercel Deployment (PR Previews)

For PR previews and faster iteration, this repository can be deployed to Vercel:

- **Setup**: See [VERCEL.md](VERCEL.md) for complete instructions
- **Build Time**: ~30-60 seconds (vs 5-10 minutes for full pipeline)
- **How It Works**: Vercel reads pre-processed data from `data/linked/` and generates the static site on-demand
- **PR Previews**: Every PR gets an automatic preview deployment URL

The data pipeline (discover → extract → detect → link) remains in GitHub Actions, while Vercel handles fast static site generation for previews.

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

### Template-to-Page Mappings

The static website is generated using Jinja2 templates located in `src/mandate_pipeline/templates/static/`. Below is a complete mapping of templates to their output files:

| Template File | Output File(s) | Generated By Function | Description |
|---------------|---------------|----------------------|-------------|
| `signals_unified_explorer.html` | `index.html` | `generate_unified_explorer_page()` | Main interactive signal browser (root page) |
| `signals_info.html` | `signals-info.html` | `generate_signals_info_page()` | Signal documentation and detection methodology |
| `base.html` | *(inherited)* | *(base template)* | Base template providing header, nav, footer for all pages |

**Notes:**
- All templates extend `base.html` which provides consistent header, navigation, and footer.
- Templates use Tailwind CSS for styling with UN branding colors.
- Only index.html and signals-info.html are generated; all detailed pages have been removed.

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

6. **IGov page generation restored**: The IGov page was generating a redirect instead of rendering the actual `signals_igov.html` template. Restored proper page generation to `igov/signals.html`, and updated all nav links to point to `/igov/signals.html`.

7. **README outdated sections updated**: Generated Website Structure table, Data Flow diagram, Stage 5 description, and GitHub Actions section were updated to reflect the current state of the project.

8. **Navigation consistency standardized**: All templates now use absolute paths from `base.html` (e.g., `/igov/signals.html`, `/signals-info.html`). Child templates no longer need to override nav blocks, eliminating path calculation errors across directory depths.

9. **Merge conflicts resolved**: Merged master branch, resolving 18 template conflicts. Adopted master's absolute path navigation and new `nav_resolutions` link while preserving our cleanup and fixes.

10. **Enhanced Mobile Filter UX**: Replaced the previous nested mobile filter dropdown with a full-screen modal. This provides larger touch targets, natural vertical scrolling, and a clearer grouping of filter options (Session, Target, Signal, Type).

11. **Optimized Splash Screen**: The opening animation now plays only once per user session (using `localStorage`). Subsequent visits or page refreshes automatically skip the splash screen for a faster experience.

12. **Improved Type Filtering**: The "Type" filter now correctly groups `amendment` documents under the `proposal` category, reflecting their role as draft document variations.

13. **UI Cleanup**: Removed the redundant "Decision" label from document cards for IGov decisions, showing only the canonical symbol (e.g., `A/DEC/78/556`) to reduce visual noise.

14. **Global Data Re-cleaning**: Performed a global pass over all 2,694+ documents to apply the latest `_clean_paragraph_text` improvements, successfully stripping thousands of PDF extraction artifacts (page headers and footnotes) that were previously leaking into the operative content.

### Recommended Follow-up Issues

The following improvements were identified during the review. Each is documented below as a standalone actionable issue.

**Issue 1: Centralize signal color definitions into a single source of truth**

Signal colors (e.g., `bg-blue-100 text-blue-800` for "agenda") are hardcoded in `generation.py` (`generate_signals_info_page`) and `signals_unified_explorer.html` (`getSignalHighlightClass`). Changes to signal types or colors require updates in multiple places. Extract signal colors into `checks.yaml` or a shared Jinja2 macro/partial.

**Issue 2: Remove unused `search-index.json` generation**

`generate_search_index()` produces `search-index.json` but no client-side code consumes it. The `lunr.js` library was imported but never wired up, and has now been removed. Either remove `search-index.json` generation entirely or implement client-side search using it.

**Issue 3: Consolidate `generate_site()` and `generate_site_verbose()` into a single function**

These two functions in `generation.py` have significant code overlap. `generate_site_verbose()` adds parallel PDF extraction and progress callbacks. Refactor into a single function with optional callback parameters and a `parallel` flag to eliminate the duplication and maintenance burden.

**Issue 4: Split `generation.py` into smaller modules**

`generation.py` contains multiple functions spanning page generation, document enrichment, data export, and template rendering. Consider splitting into: `generation/pages.py` (page generators), `generation/data.py` (JSON exports), `generation/enrichment.py` (document processing), `generation/templates.py` (template utilities).

## License

MIT License
