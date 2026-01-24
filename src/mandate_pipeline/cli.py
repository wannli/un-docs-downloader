"""Command-line interface for Mandate Pipeline."""

import argparse
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .discovery import sync_all_patterns_verbose, load_sync_state, sync_session_resolutions
from .generation import generate_site_verbose, generate_session_unified_signals_page, generate_sessions_index_page
from .detection import load_checks, run_checks
from .extractor import (
    extract_text,
    extract_operative_paragraphs,
    extract_title,
    extract_agenda_items,
    find_symbol_references,
)
from .linking import derive_resolution_origin
from .generation import get_un_document_url


def is_github_actions() -> bool:
    """Check if running in GitHub Actions."""
    return os.environ.get("GITHUB_ACTIONS") == "true"


def gh_group_start(name: str) -> None:
    """Start a collapsible group in GitHub Actions logs."""
    if is_github_actions():
        print(f"::group::{name}")
    else:
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")


def gh_group_end() -> None:
    """End a collapsible group in GitHub Actions logs."""
    if is_github_actions():
        print("::endgroup::")


def gh_warning(message: str) -> None:
    """Print a warning annotation in GitHub Actions."""
    if is_github_actions():
        print(f"::warning::{message}")
    else:
        print(f"WARNING: {message}")


def gh_error(message: str) -> None:
    """Print an error annotation in GitHub Actions."""
    if is_github_actions():
        print(f"::error::{message}")
    else:
        print(f"ERROR: {message}")


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    else:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}m {secs:.0f}s"


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mandate",
        description="Mandate Pipeline - UN document downloader and analyzer",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging (logs each document)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Discover command
    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover and download new documents",
    )
    discover_parser.add_argument(
        "--config",
        type=Path,
        default=Path("./config"),
        help="Path to config directory (default: ./config)",
    )
    discover_parser.add_argument(
        "--data",
        type=Path,
        default=Path("./data"),
        help="Path to data directory (default: ./data)",
    )
    discover_parser.add_argument(
        "--max-misses",
        type=int,
        default=3,
        help="Stop after N consecutive 404s (default: 3)",
    )
    discover_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    # Generate command
    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate static site from downloaded documents",
    )
    generate_parser.add_argument(
        "--config",
        type=Path,
        default=Path("./config"),
        help="Path to config directory (default: ./config)",
    )
    generate_parser.add_argument(
        "--data",
        type=Path,
        default=Path("./data"),
        help="Path to data directory (default: ./data)",
    )
    generate_parser.add_argument(
        "--output",
        type=Path,
        default=Path("./docs"),
        help="Path to output directory (default: ./docs)",
    )
    generate_parser.add_argument(
        "--clean-output",
        action="store_true",
        help="Delete existing output directory contents before generation",
    )
    generate_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    generate_parser.add_argument(
        "--skip-debug",
        action="store_true",
        help="Skip generating debug pages (faster builds)",
    )

    # Download session resolutions command
    download_session_parser = subparsers.add_parser(
        "download-session",
        help="Download all resolutions from a specific UN General Assembly session",
    )
    download_session_parser.add_argument(
        "--session",
        type=int,
        required=True,
        help="UN General Assembly session number (e.g., 79, 78, 77)",
    )
    download_session_parser.add_argument(
        "--config",
        type=Path,
        default=Path("./config"),
        help="Path to config directory (default: ./config)",
    )
    download_session_parser.add_argument(
        "--data",
        type=Path,
        default=Path("./data"),
        help="Path to data directory (default: ./data)",
    )
    download_session_parser.add_argument(
        "--max-misses",
        type=int,
        default=5,
        help="Stop after N consecutive 404s (default: 5)",
    )
    download_session_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    # Process session command
    process_session_parser = subparsers.add_parser(
        "process-session",
        help="Process extracted text and run signal detection for a session",
    )
    process_session_parser.add_argument(
        "--session",
        type=int,
        required=True,
        help="UN General Assembly session number (e.g., 79, 78, 77)",
    )
    process_session_parser.add_argument(
        "--config",
        type=Path,
        default=Path("./config"),
        help="Path to config directory (default: ./config)",
    )
    process_session_parser.add_argument(
        "--data",
        type=Path,
        default=Path("./data"),
        help="Path to data directory (default: ./data)",
    )
    process_session_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    # Generate session command
    generate_session_parser = subparsers.add_parser(
        "generate-session",
        help="Generate static site pages for a specific session",
    )
    generate_session_parser.add_argument(
        "--session",
        type=int,
        required=True,
        help="UN General Assembly session number (e.g., 79, 78, 77)",
    )
    generate_session_parser.add_argument(
        "--config",
        type=Path,
        default=Path("./config"),
        help="Path to config directory (default: ./config)",
    )
    generate_session_parser.add_argument(
        "--data",
        type=Path,
        default=Path("./data"),
        help="Path to data directory (default: ./data)",
    )
    generate_session_parser.add_argument(
        "--output",
        type=Path,
        default=Path("./docs"),
        help="Path to output directory (default: ./docs)",
    )
    generate_session_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    # Build session command (download + process + generate)
    build_session_parser = subparsers.add_parser(
        "build-session",
        help="Download, process, and generate pages for a specific session",
    )
    build_session_parser.add_argument(
        "--session",
        type=int,
        required=True,
        help="UN General Assembly session number (e.g., 79, 78, 77)",
    )
    build_session_parser.add_argument(
        "--config",
        type=Path,
        default=Path("./config"),
        help="Path to config directory (default: ./config)",
    )
    build_session_parser.add_argument(
        "--data",
        type=Path,
        default=Path("./data"),
        help="Path to data directory (default: ./data)",
    )
    build_session_parser.add_argument(
        "--output",
        type=Path,
        default=Path("./docs"),
        help="Path to output directory (default: ./docs)",
    )
    build_session_parser.add_argument(
        "--max-misses",
        type=int,
        default=5,
        help="Stop after N consecutive 404s (default: 5)",
    )
    build_session_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    # Download resolutions command (deprecated - keeping for compatibility)
    download_parser = subparsers.add_parser(
        "download-resolutions",
        help="Download all resolutions from a specific UN General Assembly session",
    )
    download_parser.add_argument(
        "--session",
        type=int,
        required=True,
        help="UN General Assembly session number (e.g., 79, 78, 77)",
    )
    download_parser.add_argument(
        "--config",
        type=Path,
        default=Path("./config"),
        help="Path to config directory (default: ./config)",
    )
    download_parser.add_argument(
        "--data",
        type=Path,
        default=Path("./data"),
        help="Path to data directory (default: ./data)",
    )
    download_parser.add_argument(
        "--max-misses",
        type=int,
        default=5,
        help="Stop after N consecutive 404s (default: 5)",
    )
    download_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    # Build command (discover + generate)
    build_parser = subparsers.add_parser(
        "build",
        help="Discover new documents and generate static site",
    )
    build_parser.add_argument(
        "--config",
        type=Path,
        default=Path("./config"),
        help="Path to config directory (default: ./config)",
    )
    build_parser.add_argument(
        "--data",
        type=Path,
        default=Path("./data"),
        help="Path to data directory (default: ./data)",
    )
    build_parser.add_argument(
        "--output",
        type=Path,
        default=Path("./docs"),
        help="Path to output directory (default: ./docs)",
    )
    build_parser.add_argument(
        "--clean-output",
        action="store_true",
        help="Delete existing output directory contents before generation",
    )
    build_parser.add_argument(
        "--max-misses",
        type=int,
        default=3,
        help="Stop after N consecutive 404s (default: 3)",
    )
    build_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    build_parser.add_argument(
        "--skip-debug",
        action="store_true",
        help="Skip generating debug pages (faster builds)",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "discover":
        cmd_discover(args)
    elif args.command == "generate":
        cmd_generate(args)
    elif args.command == "download-session":
        cmd_download_session(args)
    elif args.command == "process-session":
        cmd_process_session(args)
    elif args.command == "generate-session":
        cmd_generate_session(args)
    elif args.command == "build-session":
        cmd_build_session(args)
    elif args.command == "download-resolutions":
        # Deprecated command - redirect to download-session
        gh_warning("Command 'download-resolutions' is deprecated. Use 'download-session' instead.")
        cmd_download_session(args)
    elif args.command == "build":
        cmd_build(args)


def cmd_discover(args):
    """Run the discover command."""
    verbose = args.verbose or is_github_actions()
    
    gh_group_start("Discovery Configuration")
    print(f"Config directory: {args.config}")
    print(f"Data directory: {args.data}")
    print(f"Max consecutive misses: {args.max_misses}")
    print(f"Verbose: {verbose}")
    
    # Show current state
    state_file = args.data / "state.json"
    if state_file.exists():
        state = load_sync_state(state_file)
        print(f"\nCurrent state:")
        for pattern_name, pattern_state in state.get("patterns", {}).items():
            highest = pattern_state.get("highest_found", "none")
            print(f"  {pattern_name}: highest_found = {highest}")
    else:
        print("\nNo state file yet (first run)")
    
    # Count existing PDFs
    pdfs_dir = args.data / "pdfs"
    if pdfs_dir.exists():
        pdf_count = len(list(pdfs_dir.glob("**/*.pdf")))
        print(f"\nExisting cached PDFs: {pdf_count}")
    gh_group_end()
    
    # Run discovery with verbose callback
    start_time = time.time()
    
    def on_check(symbol: str, exists: bool, consecutive_misses: int):
        if exists:
            print(f"  [CHECK] {symbol} ... FOUND")
        else:
            print(f"  [CHECK] {symbol} ... 404 (miss {consecutive_misses}/{args.max_misses})")
    
    def on_download(symbol: str, path: Path, size: int, duration: float):
        print(f"  [DOWNLOAD] {symbol} -> {format_size(size)} in {format_duration(duration)}")
    
    def on_error(symbol: str, error: str):
        gh_error(f"Failed to download {symbol}: {error}")
    
    def on_pattern_start(pattern_name: str, start_number: int):
        gh_group_start(f"Pattern: {pattern_name}")
        print(f"Starting from number: {start_number}")
    
    def on_pattern_end(pattern_name: str, new_count: int, duration: float):
        print(f"\nPattern complete: {new_count} new documents in {format_duration(duration)}")
        gh_group_end()
    
    results = sync_all_patterns_verbose(
        config_dir=args.config,
        data_dir=args.data,
        max_consecutive_misses=args.max_misses,
        on_check=on_check if verbose else None,
        on_download=on_download if verbose else None,
        on_error=on_error,
        on_pattern_start=on_pattern_start if verbose else None,
        on_pattern_end=on_pattern_end if verbose else None,
    )
    
    total_duration = time.time() - start_time
    
    # Summary
    gh_group_start("Discovery Summary")
    total_new = 0
    for pattern_name, new_docs in results.items():
        count = len(new_docs)
        total_new += count
        if count > 0:
            print(f"  {pattern_name}: {count} new documents")
        else:
            print(f"  {pattern_name}: no new documents")
    
    print(f"\nTotal: {total_new} new documents downloaded")
    print(f"Duration: {format_duration(total_duration)}")
    gh_group_end()
    
    return results, total_new, total_duration


def cmd_generate(args):
    """Run the generate command."""
    verbose = args.verbose or is_github_actions()
    
    gh_group_start("Generation Configuration")
    print(f"Config directory: {args.config}")
    print(f"Data directory: {args.data}")
    print(f"Output directory: {args.output}")
    print(f"Clean output: {args.clean_output}")
    print(f"Verbose: {verbose}")
    gh_group_end()

    if args.clean_output and args.output.exists():
        gh_group_start("Cleaning Output")
        print(f"Removing existing output directory: {args.output}")
        shutil.rmtree(args.output)
        args.output.mkdir(parents=True, exist_ok=True)
        gh_group_end()
    
    # Run generation with verbose callback
    start_time = time.time()
    errors = []
    
    def on_load_start():
        if verbose:
            gh_group_start("Loading Documents")
    
    def on_load_document(symbol: str, num_paragraphs: int, signals: dict, duration: float):
        signal_names = list(signals.keys()) if signals else []
        signal_str = ", ".join(signal_names) if signal_names else "none"
        print(f"  [LOAD] {symbol}: {num_paragraphs} paragraphs, signals: {signal_str} ({format_duration(duration)})")
    
    def on_load_error(path: str, error: str):
        gh_error(f"Failed to load {path}: {error}")
        errors.append({"path": path, "error": error})
    
    def on_load_end(total: int, duration: float):
        print(f"\nLoaded {total} documents in {format_duration(duration)}")
        if verbose:
            gh_group_end()
    
    def on_generate_start():
        if verbose:
            gh_group_start("Generating Pages")
    
    def on_generate_page(page_type: str, name: str):
        print(f"  [GENERATE] {page_type}: {name}")
    
    def on_generate_end(duration: float):
        print(f"\nGeneration complete in {format_duration(duration)}")
        if verbose:
            gh_group_end()
    
    stats = generate_site_verbose(
        config_dir=args.config,
        data_dir=args.data,
        output_dir=args.output,
        skip_debug=getattr(args, 'skip_debug', False),
        on_load_start=on_load_start if verbose else None,
        on_load_document=on_load_document if verbose else None,
        on_load_error=on_load_error,
        on_load_end=on_load_end if verbose else None,
        on_generate_start=on_generate_start if verbose else None,
        on_generate_page=on_generate_page if verbose else None,
        on_generate_end=on_generate_end if verbose else None,
    )
    
    total_duration = time.time() - start_time
    
    # Summary
    gh_group_start("Generation Summary")
    print(f"Total documents: {stats['total_documents']}")
    print(f"Documents with signals: {stats['documents_with_signals']}")
    print(f"Document pages generated: {stats['document_pages']}")
    print(f"Signal pages generated: {stats['signal_pages']}")
    print(f"Errors: {len(errors)}")
    print(f"\nSignal counts:")
    for signal, count in stats.get('signal_counts', {}).items():
        print(f"  {signal}: {count}")
    print(f"\nTotal duration: {format_duration(total_duration)}")
    gh_group_end()
    
    return stats, errors, total_duration


def cmd_download_resolutions(args):
    """Run the download resolutions command."""
    verbose = args.verbose or is_github_actions()
    
    gh_group_start("Session Resolutions Download")
    print(f"Session number: {args.session}")
    print(f"Data directory: {args.data}")
    print(f"Max consecutive misses: {args.max_misses}")
    print(f"Verbose: {verbose}")
    
    # Count existing PDFs
    pdfs_dir = args.data / "pdfs"
    if pdfs_dir.exists():
        pdf_count = len(list(pdfs_dir.glob("**/*.pdf")))
        print(f"\nExisting cached PDFs: {pdf_count}")
    gh_group_end()
    
    # Run download with verbose callback
    start_time = time.time()
    
    def on_check(symbol: str, exists: bool, consecutive_misses: int):
        if exists:
            print(f"  [CHECK] {symbol} ... FOUND")
        else:
            print(f"  [CHECK] {symbol} ... 404 (miss {consecutive_misses}/{args.max_misses})")
    
    def on_download(symbol: str, path: Path, size: int, duration: float):
        print(f"  [DOWNLOAD] {symbol} -> {format_size(size)} in {format_duration(duration)}")
    
    def on_error(symbol: str, error: str):
        gh_error(f"Failed to download {symbol}: {error}")
    
    results = sync_session_resolutions(
        session=args.session,
        data_dir=args.data,
        max_consecutive_misses=args.max_misses,
        on_check=on_check if verbose else None,
        on_download=on_download if verbose else None,
        on_error=on_error,
    )
    
    total_duration = time.time() - start_time
    
    # Summary
    gh_group_start("Download Summary")
    new_docs = results.get("session_resolutions", [])
    total_new = len(new_docs)
    
    print(f"Session {args.session} resolutions: {total_new} new documents downloaded")
    print(f"Duration: {format_duration(total_duration)}")
    
    if total_new > 0 and verbose:
        print(f"\nNew documents:")
        for doc in new_docs[:10]:  # Show first 10
            print(f"  {doc}")
        if total_new > 10:
            print(f"  ... and {total_new - 10} more")
    
    gh_group_end()
    
    return results, total_new, total_duration


def cmd_build(args):
    """Run the build command (discover + generate)."""
    verbose = args.verbose or is_github_actions()
    
    print("=" * 60)
    print("  MANDATE PIPELINE BUILD")
    print("=" * 60)
    print()
    
    # Phase 1: Discovery
    print("PHASE 1: DOCUMENT DISCOVERY")
    print("-" * 40)
    
    discover_args = argparse.Namespace(
        config=args.config,
        data=args.data,
        max_misses=args.max_misses,
        verbose=verbose,
    )
    discover_results, new_docs_count, discover_duration = cmd_discover(discover_args)
    
    print()
    print("PHASE 2: STATIC SITE GENERATION")
    print("-" * 40)
    
    # Phase 2: Generation
    generate_args = argparse.Namespace(
        config=args.config,
        data=args.data,
        output=args.output,
        clean_output=args.clean_output,
        verbose=verbose,
    )
    gen_stats, gen_errors, generate_duration = cmd_generate(generate_args)
    
    # Final summary
    print()
    print("=" * 60)
    print("  BUILD COMPLETE")
    print("=" * 60)
    print(f"New documents discovered: {new_docs_count}")
    print(f"Total documents in site: {gen_stats['total_documents']}")
    print(f"Discovery duration: {format_duration(discover_duration)}")
    print(f"Generation duration: {format_duration(generate_duration)}")
    print(f"Total duration: {format_duration(discover_duration + generate_duration)}")
    
    if gen_errors:
        print(f"\nWarning: {len(gen_errors)} errors occurred during generation")
    
    # Write GitHub Actions job summary
    if is_github_actions():
        write_job_summary(
            discover_results=discover_results,
            new_docs_count=new_docs_count,
            discover_duration=discover_duration,
            gen_stats=gen_stats,
            gen_errors=gen_errors,
            generate_duration=generate_duration,
        )
    
    return 0 if not gen_errors else 1


def cmd_download_session(args):
    """Run the download session command."""
    verbose = args.verbose or is_github_actions()

    gh_group_start("Session Resolutions Download")
    print(f"Session number: {args.session}")
    print(f"Data directory: {args.data}")
    print(f"Max consecutive misses: {args.max_misses}")
    print(f"Verbose: {verbose}")

    # Count existing PDFs
    pdfs_dir = args.data / "pdfs"
    if pdfs_dir.exists():
        pdf_count = len(list(pdfs_dir.glob("**/*.pdf")))
        print(f"\nExisting cached PDFs: {pdf_count}")
    gh_group_end()

    # Run download with verbose callback
    start_time = time.time()

    def on_check(symbol: str, exists: bool, consecutive_misses: int):
        if exists:
            print(f"  [CHECK] {symbol} ... FOUND")
        else:
            print(f"  [CHECK] {symbol} ... 404 (miss {consecutive_misses}/{args.max_misses})")

    def on_download(symbol: str, path: Path, size: int, duration: float):
        print(f"  [DOWNLOAD] {symbol} -> {format_size(size)} in {format_duration(duration)}")

    def on_error(symbol: str, error: str):
        gh_error(f"Failed to download {symbol}: {error}")

    results = sync_session_resolutions(
        session=args.session,
        data_dir=args.data,
        max_consecutive_misses=args.max_misses,
        on_check=on_check if verbose else None,
        on_download=on_download if verbose else None,
        on_error=on_error,
    )

    total_duration = time.time() - start_time

    # Summary
    gh_group_start("Download Summary")
    new_docs = results.get("session_resolutions", [])
    total_new = len(new_docs)

    print(f"Session {args.session} resolutions: {total_new} new documents downloaded")
    print(f"Duration: {format_duration(total_duration)}")

    if total_new > 0 and verbose:
        print(f"\nNew documents:")
        for doc in new_docs[:10]:  # Show first 10
            print(f"  {doc}")
        if total_new > 10:
            print(f"  ... and {total_new - 10} more")

    gh_group_end()

    return results, total_new, total_duration


def cmd_process_session(args):
    """Run the process session command (extraction + detection)."""
    verbose = args.verbose or is_github_actions()

    gh_group_start("Session Processing")
    print(f"Session number: {args.session}")
    print(f"Config directory: {args.config}")
    print(f"Data directory: {args.data}")
    print(f"Verbose: {verbose}")

    # Load checks
    checks = load_checks(args.config / "checks.yaml")
    print(f"Loaded {len(checks)} signal definitions")

    # Find session PDFs
    pdfs_dir = args.data / "pdfs"
    session_pattern = f"A_RES_{args.session}_*.pdf"
    session_pdfs = list(pdfs_dir.glob(session_pattern))

    if not session_pdfs:
        gh_error(f"No PDFs found for session {args.session} in {pdfs_dir}")
        return [], 0, 0

    print(f"Found {len(session_pdfs)} PDFs for session {args.session}")

    # Process documents
    documents = []
    start_time = time.time()

    def on_load_document(symbol: str, num_paragraphs: int, signals: dict, duration: float):
        signal_names = list(signals.keys()) if signals else []
        signal_str = ", ".join(signal_names) if signal_names else "none"
        print(f"  [LOAD] {symbol}: {num_paragraphs} paragraphs, signals: {signal_str} ({format_duration(duration)})")

    def on_load_error(path: str, error: str):
        gh_error(f"Failed to load {path}: {error}")

    # Load all session documents
    for pdf_path in session_pdfs:
        filename = pdf_path.name
        symbol = filename.replace("_", "/").replace(".pdf", "")

        try:
            # Extract text
            text = extract_text(pdf_path)

            # Extract structured data
            paragraphs = extract_operative_paragraphs(text)
            title = extract_title(text)
            agenda_items = extract_agenda_items(text)
            symbol_refs = find_symbol_references(text)

            # Run signal detection
            signals = run_checks(paragraphs, checks)

            # Create signal summary (for template compatibility)
            signal_summary = {}
            if signals:
                for para_signals in signals.values():
                    for signal in para_signals:
                        signal_summary[signal] = signal_summary.get(signal, 0) + 1

            # Classify document
            doc_type = "resolution"  # All session documents are resolutions

            # Derive origin (will be "Unknown" for historical sessions)
            origin = derive_resolution_origin({
                "symbol": symbol,
                "linked_proposal_symbols": []  # No proposals to link to
            })

            # Build document dict
            doc = {
                "symbol": symbol,
                "filename": filename,
                "title": title,
                "text": text,
                "paragraphs": paragraphs,
                "signals": signals,
                "signal_summary": signal_summary,
                "doc_type": doc_type,
                "origin": origin,
                "agenda_items": agenda_items,
                "symbol_references": symbol_refs,
                "un_url": get_un_document_url(symbol),
                "is_adopted_draft": False,  # No proposals to link to
                "adopted_by": None,
                "linked_proposals": [],
            }

            documents.append(doc)

            if verbose:
                signal_count = len(signals)
                signal_names = list(signals.keys())
                signal_str = ", ".join(str(name) for name in signal_names) if signal_names else "none"
                print(f"  [PROCESS] {symbol}: {len(paragraphs)} paragraphs, {signal_count} signals ({signal_str})")

        except Exception as e:
            gh_error(f"Failed to process {filename}: {e}")

    total_duration = time.time() - start_time

    # Summary
    gh_group_start("Processing Summary")
    docs_with_signals = [d for d in documents if d.get("signal_paragraphs")]
    total_signals = sum(len(d.get("signal_paragraphs", {})) for d in documents)

    print(f"Processed {len(documents)} documents")
    print(f"Documents with signals: {len(docs_with_signals)}")
    print(f"Total signal paragraphs: {total_signals}")
    print(f"Duration: {format_duration(total_duration)}")

    gh_group_end()

    return documents, len(documents), total_duration


def cmd_generate_session(args):
    """Run the generate session command."""
    verbose = args.verbose or is_github_actions()

    gh_group_start("Session Generation")
    print(f"Session number: {args.session}")
    print(f"Config directory: {args.config}")
    print(f"Data directory: {args.data}")
    print(f"Output directory: {args.output}")
    print(f"Verbose: {verbose}")

    # Load checks
    checks = load_checks(args.config / "checks.yaml")

    # Process session documents
    documents, doc_count, process_duration = cmd_process_session(args)

    if doc_count == 0:
        gh_error(f"No documents found for session {args.session}")
        return {}, 0

    # Generate session signal browser
    start_time = time.time()
    gen_stats = generate_session_unified_signals_page(args.session, documents, checks, args.output)
    generate_duration = time.time() - start_time

    # Generate session dashboard
    generate_session_dashboard(args.session, documents, args.output)

    # Generate data export
    generate_session_data_json(documents, checks, args.session, args.output)

    # Regenerate sessions index page
    generate_sessions_index_page(args.output)

    # Summary
    gh_group_start("Generation Summary")
    print(f"Session {args.session}: {gen_stats['total_documents']} documents processed")
    print(f"Documents with signals: {gen_stats['documents_with_signals']}")
    print(f"Total signal paragraphs: {gen_stats['total_signal_paragraphs']}")
    print(f"Processing duration: {format_duration(process_duration)}")
    print(f"Generation duration: {format_duration(generate_duration)}")
    print(f"Total duration: {format_duration(process_duration + generate_duration)}")

    gh_group_end()

    return {
        "session": args.session,
        "total_documents": gen_stats['total_documents'],
        "documents_with_signals": gen_stats['documents_with_signals'],
        "total_signals": gen_stats['total_signal_paragraphs'],
    }, process_duration + generate_duration


def cmd_build_session(args):
    """Run the build session command (download + process + generate)."""
    verbose = args.verbose or is_github_actions()

    print("=" * 60)
    print(f"  SESSION {args.session} BUILD PIPELINE")
    print("=" * 60)
    print()

    # Phase 1: Download
    print(f"PHASE 1: DOWNLOAD SESSION {args.session} RESOLUTIONS")
    print("-" * 50)

    download_args = argparse.Namespace(
        session=args.session,
        config=args.config,
        data=args.data,
        max_misses=args.max_misses,
        verbose=verbose,
    )
    download_results, download_count, download_duration = cmd_download_session(download_args)

    print()

    # Check if we have any PDFs for this session to process
    pdfs_dir = args.data / "pdfs"
    session_pattern = f"A_RES_{args.session}_*.pdf"
    session_pdfs = list(pdfs_dir.glob(session_pattern))

    if not session_pdfs:
        print(f"No PDFs found for session {args.session} after download attempt")
        return 0

    # Phase 2: Generate
    print(f"PHASE 2: GENERATE SESSION {args.session} PAGES")
    print("-" * 50)

    generate_args = argparse.Namespace(
        session=args.session,
        config=args.config,
        data=args.data,
        output=args.output,
        verbose=verbose,
    )
    gen_stats, generate_duration = cmd_generate_session(generate_args)

    # Final summary
    print()
    print("=" * 60)
    print(f"  SESSION {args.session} BUILD COMPLETE")
    print("=" * 60)
    print(f"New resolutions downloaded: {download_count}")
    print(f"Documents processed: {gen_stats.get('total_documents', 0)}")
    print(f"Documents with signals: {gen_stats.get('documents_with_signals', 0)}")
    print(f"Download duration: {format_duration(download_duration)}")
    print(f"Processing/generation duration: {format_duration(generate_duration)}")
    print(f"Total duration: {format_duration(download_duration + generate_duration)}")

    return 0


def generate_session_index_page(sessions_data: dict, output_dir: Path):
    """Generate the sessions index page showing all available sessions."""
    # This will be implemented when we add the sessions index template
    pass


def generate_session_dashboard(session: int, documents: list[dict], output_dir: Path):
    """Generate a simple dashboard page for the session."""
    session_dir = output_dir / "sessions" / str(session)
    session_dir.mkdir(parents=True, exist_ok=True)

    # Simple HTML dashboard
    total_resolutions = len(documents)
    with_signals = len([d for d in documents if d.get('signal_paragraphs')])
    signal_paragraphs = sum(len(d.get('signal_paragraphs', {})) for d in documents)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Session {session} - Mandate Pipeline</title>
    <link href="../../static/base.css" rel="stylesheet">
</head>
<body>
    <div class="min-h-screen bg-gray-50">
        <nav class="bg-un-blue text-white shadow-lg">
            <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div class="flex justify-between h-16">
                    <div class="flex items-center">
                        <a href="../index.html" class="text-white hover:text-gray-200 px-3 py-2 rounded-md text-sm font-medium">
                            ← Historical Sessions
                        </a>
                    </div>
                    <div class="flex items-center">
                        <a href="../../index.html" class="text-white hover:text-gray-200 px-3 py-2 rounded-md text-sm font-medium">
                            Main Site
                        </a>
                    </div>
                </div>
            </div>
        </nav>

        <main class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
            <div class="px-4 py-6 sm:px-0">
                <div class="mb-8">
                    <h1 class="text-3xl font-bold text-gray-900 tracking-tight">Session {session} Dashboard</h1>
                    <p class="mt-2 text-muted">Signal analysis for UN General Assembly Session {session}</p>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                    <div class="bg-white overflow-hidden shadow rounded-lg">
                        <div class="p-5">
                            <div class="flex items-center">
                                <div class="flex-shrink-0">
                                    <svg class="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                                    </svg>
                                </div>
                                <div class="ml-5 w-0 flex-1">
                                    <dl>
                                        <dt class="text-sm font-medium text-gray-500 truncate">Total Resolutions</dt>
                                        <dd class="text-lg font-medium text-gray-900">{total_resolutions}</dd>
                                    </dl>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="bg-white overflow-hidden shadow rounded-lg">
                        <div class="p-5">
                            <div class="flex items-center">
                                <div class="flex-shrink-0">
                                    <svg class="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
                                    </svg>
                                </div>
                                <div class="ml-5 w-0 flex-1">
                                    <dl>
                                        <dt class="text-sm font-medium text-gray-500 truncate">With Signals</dt>
                                        <dd class="text-lg font-medium text-gray-900">{with_signals}</dd>
                                    </dl>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="bg-white overflow-hidden shadow rounded-lg">
                        <div class="p-5">
                            <div class="flex items-center">
                                <div class="flex-shrink-0">
                                    <svg class="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 4V2a1 1 0 011-1h4a1 1 0 011 1v2m4 0H8l.5 16h7L16 4z"></path>
                                    </svg>
                                </div>
                                <div class="ml-5 w-0 flex-1">
                                    <dl>
                                        <dt class="text-sm font-medium text-gray-500 truncate">Signal Paragraphs</dt>
                                        <dd class="text-lg font-medium text-gray-900">{signal_paragraphs}</dd>
                                    </dl>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="bg-white shadow rounded-lg">
                    <div class="px-4 py-5 sm:p-6">
                        <h3 class="text-lg leading-6 font-medium text-gray-900 mb-4">Signal Browser</h3>
                        <p class="text-sm text-gray-500 mb-4">
                            Explore all signals detected in Session {session} resolutions.
                        </p>
                        <a href="signals.html" class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-un-blue hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-un-blue">
                            Browse Signals
                        </a>
                    </div>
                </div>
            </div>
        </main>
    </div>
</body>
</html>"""

    with open(session_dir / "index.html", "w") as f:
        f.write(html)


def generate_session_data_json(documents: list[dict], checks: list, session: int, output_dir: Path):
    """Generate JSON data export for the session."""
    session_dir = output_dir / "sessions" / str(session)
    session_dir.mkdir(parents=True, exist_ok=True)

    # Calculate signal counts
    signal_counts = {}
    for doc in documents:
        for signal in doc.get("signal_paragraphs", {}):
            signal_counts[signal] = signal_counts.get(signal, 0) + 1

    data = {
        "session": session,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "checks": checks,
        "documents": documents,
        "stats": {
            "total_documents": len(documents),
            "documents_with_signals": len([d for d in documents if d.get("signal_paragraphs")]),
            "signal_counts": signal_counts,
        }
    }

    import json
    with open(session_dir / "data.json", "w") as f:
        json.dump(data, f, indent=2)


def write_job_summary(
    discover_results: dict,
    new_docs_count: int,
    discover_duration: float,
    gen_stats: dict,
    gen_errors: list,
    generate_duration: float,
):
    """Write a markdown summary for GitHub Actions."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return
    
    with open(summary_file, "a") as f:
        f.write("## Build Summary\n\n")
        
        # Documents table
        f.write("### Documents\n\n")
        f.write("| Metric | Count |\n")
        f.write("|--------|-------|\n")
        f.write(f"| New Documents Discovered | {new_docs_count} |\n")
        f.write(f"| Total Documents | {gen_stats['total_documents']} |\n")
        f.write(f"| Documents with Signals | {gen_stats['documents_with_signals']} |\n")
        f.write(f"| Document Pages Generated | {gen_stats['document_pages']} |\n")
        f.write(f"| Signal Pages Generated | {gen_stats['signal_pages']} |\n")
        f.write("\n")
        
        # Signals table
        f.write("### Signals Detected\n\n")
        f.write("| Signal | Occurrences |\n")
        f.write("|--------|-------------|\n")
        for signal, count in gen_stats.get('signal_counts', {}).items():
            f.write(f"| {signal} | {count} |\n")
        f.write("\n")
        
        # New documents by pattern
        if new_docs_count > 0:
            f.write("### New Documents by Pattern\n\n")
            for pattern_name, docs in discover_results.items():
                if docs:
                    f.write(f"**{pattern_name}** ({len(docs)} new)\n")
                    for doc in docs[:10]:  # Limit to 10 per pattern
                        f.write(f"- {doc}\n")
                    if len(docs) > 10:
                        f.write(f"- ... and {len(docs) - 10} more\n")
                    f.write("\n")
        
        # Timing table
        f.write("### Timing\n\n")
        f.write("| Phase | Duration |\n")
        f.write("|-------|----------|\n")
        f.write(f"| Discovery | {format_duration(discover_duration)} |\n")
        f.write(f"| Generation | {format_duration(generate_duration)} |\n")
        f.write(f"| **Total** | {format_duration(discover_duration + generate_duration)} |\n")
        f.write("\n")
        
        # Errors
        if gen_errors:
            f.write("### Errors\n\n")
            f.write(f"**{len(gen_errors)} errors occurred:**\n\n")
            for err in gen_errors[:10]:
                f.write(f"- `{err['path']}`: {err['error']}\n")
            if len(gen_errors) > 10:
                f.write(f"- ... and {len(gen_errors) - 10} more\n")


if __name__ == "__main__":
    main()
