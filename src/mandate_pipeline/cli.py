"""Command-line interface for Mandate Pipeline."""

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from .discovery import sync_all_patterns_verbose, load_sync_state
from .generation import generate_site_verbose
from .detection import load_checks


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

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "discover":
        cmd_discover(args)
    elif args.command == "generate":
        cmd_generate(args)
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
