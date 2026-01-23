"""Generate per-signal email markdown reports from pipeline output."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def sanitize_filename(value: str) -> str:
    """Create a filesystem-safe filename."""
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)
    return safe.strip("-").lower() or "signal"


def write_email_preview(
    output_dir: Path,
    signal: str,
    subject: str,
    markdown_body: str,
) -> Path:
    """Write an email preview file to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{sanitize_filename(signal)}-{timestamp}.md"
    preview_path = output_dir / filename
    preview_path.write_text(
        "\n".join(
            [
                f"# {subject}",
                "",
                markdown_body,
            ]
        ),
        encoding="utf-8",
    )
    return preview_path


def append_summary_entry(
    signal: str,
    subject: str,
    preview_path: Optional[Path],
    markdown_body: Optional[str],
) -> None:
    """Append a link to the GitHub Actions summary, if available."""
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return
    with open(summary_file, "a", encoding="utf-8") as handle:
        handle.write(f"## {signal}\n\n")
        handle.write(f"**{subject}**\n\n")
        if preview_path:
            handle.write(f"Preview: `{preview_path}`\n\n")
        if markdown_body:
            handle.write("<details>\n<summary>Markdown report</summary>\n\n")
            handle.write(markdown_body)
            handle.write("\n\n</details>\n\n")


def load_data(path: Path) -> dict:
    """Load pipeline data.json from disk."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_recipients(raw: str) -> dict[str, list[str]]:
    """Parse recipients mapping from JSON."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("SIGNAL_EMAIL_RECIPIENTS must be valid JSON") from exc

    if isinstance(data, list):
        return {"default": [str(item).strip() for item in data if str(item).strip()]}

    if isinstance(data, dict):
        normalized: dict[str, list[str]] = {}
        for key, value in data.items():
            if isinstance(value, str):
                emails = [item.strip() for item in value.split(",") if item.strip()]
            elif isinstance(value, list):
                emails = [str(item).strip() for item in value if str(item).strip()]
            else:
                emails = []
            if emails:
                normalized[str(key)] = emails
        return normalized

    raise ValueError("SIGNAL_EMAIL_RECIPIENTS must be a JSON object or list")


def collect_resolutions_by_signal(data: dict) -> dict[str, list[dict]]:
    """Collect resolutions grouped by signal."""
    grouped: dict[str, list[dict]] = {}
    for doc in data.get("documents", []):
        if doc.get("doc_type") != "resolution":
            continue
        for signal in doc.get("signal_summary", {}):
            grouped.setdefault(signal, []).append(doc)
    return grouped


def collect_symbols_by_signal(grouped: dict[str, list[dict]]) -> dict[str, set[str]]:
    """Collect symbol sets for each signal."""
    return {
        signal: {doc.get("symbol") for doc in docs if doc.get("symbol")}
        for signal, docs in grouped.items()
    }


def format_paragraphs_markdown(paragraphs: dict) -> list[str]:
    """Format numbered paragraphs for markdown output."""
    if not paragraphs:
        return ["_No operative paragraphs found._"]
    keys = list(paragraphs.keys())

    def sort_key(value: object) -> tuple[int, str]:
        try:
            return (0, f"{int(value):06d}")
        except (TypeError, ValueError):
            return (1, str(value))

    lines = []
    for key in sorted(keys, key=sort_key):
        text = paragraphs.get(key)
        if text:
            lines.append(f"- **{key}.** {text}")
    return lines or ["_No operative paragraphs found._"]


def build_email_markdown(
    signal: str,
    docs: list[dict],
    new_symbols: set[str],
    generated_at: str,
) -> tuple[str, str]:
    """Build subject and markdown body for an email-ready report."""
    new_docs = [doc for doc in docs if doc.get("symbol") in new_symbols]
    old_docs = [doc for doc in docs if doc.get("symbol") not in new_symbols]
    ordered_docs = new_docs + old_docs

    subject = f"Mandate Pipeline: {signal} ({len(new_docs)} new)"

    markdown_lines = [
        f"Signal: **{signal}**",
        f"Generated at {generated_at}.",
        "",
    ]

    for doc in ordered_docs:
        symbol = doc.get("symbol", "Unknown symbol")
        title = doc.get("title") or "Untitled"
        url = doc.get("un_url") or ""
        if doc.get("symbol") in new_symbols:
            markdown_lines.append(f"## {symbol} — {title} (**NEW**)")
        else:
            markdown_lines.append(f"## {symbol} — {title}")
        if url:
            markdown_lines.append(f"- UN ODS: {url}")
        markdown_lines.append("- Resolution text (operative paragraphs):")
        markdown_lines.extend(format_paragraphs_markdown(doc.get("paragraphs", {})))
        markdown_lines.append("")

    if not ordered_docs:
        markdown_lines.append("No resolutions found for this signal.")

    markdown_body = "\n".join(markdown_lines).strip()
    return subject, markdown_body


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Generate per-signal email markdown reports.")
    parser.add_argument(
        "--current",
        type=Path,
        required=True,
        help="Path to current data.json",
    )
    parser.add_argument(
        "--previous",
        type=Path,
        required=False,
        help="Path to previous data.json (optional)",
    )
    parser.add_argument(
        "--preview-dir",
        type=Path,
        required=False,
        help="Directory to write email previews (default: ./email-previews)",
    )
    args = parser.parse_args()

    recipients_raw = os.getenv("SIGNAL_EMAIL_RECIPIENTS")
    recipients_map = parse_recipients(recipients_raw) if recipients_raw else {}
    preview_dir = args.preview_dir or Path(os.getenv("EMAIL_REPORT_PREVIEW_DIR", "./email-previews"))

    current_data = load_data(args.current)
    current_grouped = collect_resolutions_by_signal(current_data)
    current_symbols = collect_symbols_by_signal(current_grouped)

    previous_symbols: dict[str, set[str]] = {}
    if args.previous and args.previous.exists():
        previous_data = load_data(args.previous)
        previous_grouped = collect_resolutions_by_signal(previous_data)
        previous_symbols = collect_symbols_by_signal(previous_grouped)

    generated_at = current_data.get("generated_at", "unknown time")

    append_summary_entry(
        "Summary",
        f"Markdown previews written to {preview_dir}",
        None,
        None,
    )

    for signal, docs in current_grouped.items():
        if recipients_map:
            recipients = recipients_map.get(signal) or recipients_map.get("default", [])
            if not recipients:
                print(f"Skipping signal '{signal}': no recipients configured")
                continue

        new_symbols = current_symbols.get(signal, set()) - previous_symbols.get(signal, set())
        subject, markdown_body = build_email_markdown(signal, docs, new_symbols, generated_at)
        preview_path = write_email_preview(preview_dir, signal, subject, markdown_body)
        append_summary_entry(signal, subject, preview_path, markdown_body)
        print(f"Wrote {preview_path}")


if __name__ == "__main__":
    main()
