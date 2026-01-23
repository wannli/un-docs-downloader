# Agent Instructions

The `docs/` directory contains generated static site output used by the pipeline. It **must remain tracked** in git because the pipeline expects it to exist in the repository.

When making code changes:
- Do **not** edit files under `docs/` unless the user explicitly asks for a regeneration.
- Avoid staging or committing `docs/` changes that are incidental to code edits (e.g., from running the generator locally).
- Keep changes focused on the source code and templates that *produce* the static site output.
