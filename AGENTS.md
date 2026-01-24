# Agent Instructions

The `docs/` directory contains generated static site output used by the pipeline. It **must remain tracked** in git because the pipeline expects it to exist in the repository.

When making code changes:
- Do **not** edit files under `docs/` unless the user explicitly asks for a regeneration.
- Avoid staging or committing `docs/` changes that are incidental to code edits (e.g., from running the generator locally).
- Keep changes focused on the source code and templates that *produce* the static site output.

## Testing Workflow

When making changes to the mandate pipeline project:

1. **Test locally first** - Make sure changes work correctly on your local machine before pushing
2. **Push the code** - Once local testing passes, commit and push to the repository
3. **Run GitHub runner** - Trigger the GitHub Actions workflow to recreate the site
4. **Monitor with browser tools** - Use `browser_get_tabs` to see what's happening during the pipeline run and verify the site recreation completed successfully

## Collaboration Flow

When working changes end-to-end with this project:

1. **Review diffs** - Check `git status`, `git diff`, and recent `git log` before committing.
2. **Commit and push** - Create a concise commit message, push, and rebase if the remote is ahead (do not ask for confirmation before rebasing).
3. **Trigger site generation** - Run `gh workflow run generate.yml` after pushing.
4. **Verify workflow status** - Use `gh run list -w generate.yml -L 1` and `gh run view <id>` to confirm completion.
5. **Monitor via browser** - Keep the workflow page open and use `browser_get_tabs` to track progress.
6. **Poll for completion** - Check `gh run view <id>` every 30s until it finishes.
7. **Refresh the site tab** - Once the run completes, refresh the site browser tab to load the latest output.

## Workflow Architecture

The pipeline uses a **granular, event-driven workflow architecture** with 6 independent GitHub Actions workflows:

### Main Pipeline Workflows (Stages 1-5)
1. **`discover.yml`** - Stage 1: Document Discovery
   - Triggers: Hourly schedule + manual historical sessions
   - Downloads new UN documents and commits PDFs to `data/pdfs/`
   - Triggers downstream extraction workflow

2. **`extract.yml`** - Stage 2: Text Extraction
   - Triggers: New files in `data/pdfs/`
   - Parallel processing of PDFs to extract text/metadata
   - Commits extracted data to `data/extracted/`

3. **`detect.yml`** - Stage 3: Signal Detection
   - Triggers: New files in `data/extracted/` OR changes to `config/checks.yaml`
   - Runs mandate signal detection on extracted documents
   - Commits detection results to `data/detected/`

4. **`link.yml`** - Stage 4: Document Linking
   - Triggers: New files in `data/detected/`
   - Builds relationships between resolutions and proposals
   - Commits linkage data to `data/linked/`

5. **`generate.yml`** - Stage 5: Site Generation
   - Triggers: New files in `data/linked/`
   - Generates static website and commits to `docs/` folder
   - Site served directly from main branch

### Special Purpose Workflow
6. **`build-session.yml`** - Historical Session Builder
   - Manual trigger for complete historical UN sessions
   - Processes entire past sessions (download → extract → detect → link → generate)
   - Creates session-specific pages in `docs/sessions/`

### Key Features
- **Event-driven**: Each stage triggers the next automatically
- **Parallel processing**: Multiple jobs can run simultaneously where safe
- **Incremental updates**: Only processes changed documents
- **Direct commits**: All workflows commit results directly to main branch
- **Performance focused**: Minimizes redundant work through smart triggering
