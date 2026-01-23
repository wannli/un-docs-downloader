"""Generate and send per-signal email reports from pipeline output."""

import argparse
import json
import os
import smtplib
from datetime import datetime, timezone
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, Optional

import requests


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: Optional[str]
    password: Optional[str]
    sender: str
    use_ssl: bool
    starttls: bool


@dataclass(frozen=True)
class MailgunConfig:
    api_key: str
    domain: str
    sender: str
    base_url: str


def is_truthy(value: Optional[str]) -> bool:
    """Return True for common truthy strings."""
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def sanitize_filename(value: str) -> str:
    """Create a filesystem-safe filename."""
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)
    return safe.strip("-").lower() or "signal"


def write_email_preview(
    output_dir: Path,
    signal: str,
    subject: str,
    html_body: str,
    text_body: str,
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
                "## Text",
                "",
                "```",
                text_body,
                "```",
                "",
                "## HTML",
                "",
                "```html",
                html_body,
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return preview_path


def append_summary_entry(signal: str, subject: str, preview_path: Optional[Path]) -> None:
    """Append a link to the GitHub Actions summary, if available."""
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return
    with open(summary_file, "a", encoding="utf-8") as handle:
        handle.write(f"- **{signal}**: {subject}")
        if preview_path:
            handle.write(f" (preview: `{preview_path}`)")
        handle.write("\n")


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


def build_email(
    signal: str,
    docs: list[dict],
    new_symbols: set[str],
    generated_at: str,
) -> tuple[str, str, str]:
    """Build subject, HTML body, and text body for an email."""
    new_docs = [doc for doc in docs if doc.get("symbol") in new_symbols]
    old_docs = [doc for doc in docs if doc.get("symbol") not in new_symbols]
    ordered_docs = new_docs + old_docs

    subject = f"Mandate Pipeline: {signal} ({len(new_docs)} new)"

    html_lines = [
        f"<h2>Signal: {signal}</h2>",
        f"<p>Generated at {generated_at}.</p>",
        "<ul>",
    ]

    text_lines = [
        f"Signal: {signal}",
        f"Generated at {generated_at}",
        "",
    ]

    for doc in ordered_docs:
        symbol = doc.get("symbol", "Unknown symbol")
        title = doc.get("title") or "Untitled"
        url = doc.get("un_url") or ""
        line_text = f"- {symbol} — {title}"
        if url:
            line_text += f" ({url})"

        if doc.get("symbol") in new_symbols:
            html_lines.append(
                f"  <li><strong>{symbol} — {title}</strong>"
                f"{f' (<a href=\"{url}\">link</a>)' if url else ''}</li>"
            )
            text_lines.append(f"*NEW* {line_text}")
        else:
            html_lines.append(
                f"  <li>{symbol} — {title}"
                f"{f' (<a href=\"{url}\">link</a>)' if url else ''}</li>"
            )
            text_lines.append(line_text)

    html_lines.append("</ul>")

    if not ordered_docs:
        html_lines.append("<p>No resolutions found for this signal.</p>")
        text_lines.append("No resolutions found for this signal.")

    html_body = "\n".join(html_lines)
    text_body = "\n".join(text_lines)
    return subject, html_body, text_body


def send_email(
    smtp_config: SmtpConfig,
    recipients: Iterable[str],
    subject: str,
    html_body: str,
    text_body: str,
) -> None:
    """Send an email using SMTP."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_config.sender
    message["To"] = ", ".join(recipients)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    if smtp_config.use_ssl:
        server = smtplib.SMTP_SSL(smtp_config.host, smtp_config.port)
    else:
        server = smtplib.SMTP(smtp_config.host, smtp_config.port)

    try:
        if smtp_config.starttls and not smtp_config.use_ssl:
            server.starttls()
        if smtp_config.username and smtp_config.password:
            server.login(smtp_config.username, smtp_config.password)
        server.send_message(message)
    finally:
        server.quit()


def send_mailgun_email(
    mailgun_config: MailgunConfig,
    recipients: Iterable[str],
    subject: str,
    html_body: str,
    text_body: str,
) -> None:
    """Send an email using the Mailgun API."""
    url = f"{mailgun_config.base_url}/{mailgun_config.domain}/messages"
    response = requests.post(
        url,
        auth=("api", mailgun_config.api_key),
        data={
            "from": mailgun_config.sender,
            "to": ", ".join(recipients),
            "subject": subject,
            "text": text_body,
            "html": html_body,
        },
        timeout=30,
    )
    response.raise_for_status()


def load_mailgun_config() -> Optional[MailgunConfig]:
    """Load Mailgun configuration from environment variables."""
    api_key = os.getenv("MAILGUN_API_KEY")
    domain = os.getenv("MAILGUN_DOMAIN")
    sender = os.getenv("MAILGUN_FROM") or os.getenv("SMTP_FROM")
    if not api_key or not domain:
        return None
    if not sender:
        raise ValueError("MAILGUN_FROM or SMTP_FROM must be set for Mailgun")
    base_url = os.getenv("MAILGUN_BASE_URL", "https://api.mailgun.net/v3")
    return MailgunConfig(
        api_key=api_key,
        domain=domain,
        sender=sender,
        base_url=base_url,
    )


def load_smtp_config() -> SmtpConfig:
    """Load SMTP configuration from environment variables."""
    host = os.getenv("SMTP_HOST")
    sender = os.getenv("SMTP_FROM")
    if not host or not sender:
        raise ValueError("SMTP_HOST and SMTP_FROM must be set for SMTP delivery")

    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    use_ssl = os.getenv("SMTP_USE_SSL", "false").lower() in {"1", "true", "yes"}
    starttls = os.getenv("SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"}

    return SmtpConfig(
        host=host,
        port=port,
        username=username,
        password=password,
        sender=sender,
        use_ssl=use_ssl,
        starttls=starttls,
    )


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Send per-signal email reports.")
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate email previews instead of sending email.",
    )
    args = parser.parse_args()

    recipients_raw = os.getenv("SIGNAL_EMAIL_RECIPIENTS")
    if not recipients_raw:
        raise ValueError("SIGNAL_EMAIL_RECIPIENTS must be set")

    recipients_map = parse_recipients(recipients_raw)
    mailgun_config = load_mailgun_config()
    smtp_config = None if mailgun_config else load_smtp_config()
    dry_run = args.dry_run or is_truthy(os.getenv("EMAIL_REPORT_DRY_RUN"))
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

    if dry_run:
        append_summary_entry("Summary", f"Dry run enabled; previews in {preview_dir}", None)

    for signal, docs in current_grouped.items():
        recipients = recipients_map.get(signal) or recipients_map.get("default", [])
        if not recipients:
            print(f"Skipping signal '{signal}': no recipients configured")
            continue

        new_symbols = current_symbols.get(signal, set()) - previous_symbols.get(signal, set())
        subject, html_body, text_body = build_email(signal, docs, new_symbols, generated_at)
        if dry_run:
            preview_path = write_email_preview(preview_dir, signal, subject, html_body, text_body)
            append_summary_entry(signal, subject, preview_path)
            print(f"Dry run: wrote {preview_path}")
            continue

        if mailgun_config:
            send_mailgun_email(mailgun_config, recipients, subject, html_body, text_body)
        else:
            if smtp_config is None:
                raise ValueError("SMTP configuration is missing")
            send_email(smtp_config, recipients, subject, html_body, text_body)
        append_summary_entry(signal, subject, None)
        print(f"Sent {signal} report to {', '.join(recipients)}")


if __name__ == "__main__":
    main()
