"""Check system for detecting signals in UN resolution paragraphs."""

from pathlib import Path

import yaml


def parse_checks_yaml(yaml_content) -> list[dict]:
    """
    Parse check definitions from YAML content string or stream.

    Args:
        yaml_content: String or stream containing YAML configuration

    Returns:
        List of check definitions
    """
    if not yaml_content:
        return []

    config = yaml.safe_load(yaml_content)
    if not config:
        return []

    return config.get("checks", [])


def load_checks(config_path: Path) -> list[dict]:
    """
    Load check definitions from a YAML file.

    Args:
        config_path: Path to the YAML configuration file

    Returns:
        List of check definitions, each containing:
        - signal: Signal name (used for display and matching)
        - phrases: List of phrases to search for
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        return parse_checks_yaml(f)


def run_checks(paragraphs: dict[int, str], checks: list[dict]) -> dict[int, list[str]]:
    """
    Run checks against operative paragraphs and find matching signals.

    Args:
        paragraphs: Dictionary mapping paragraph numbers to text
        checks: List of check definitions from load_checks()

    Returns:
        Dictionary mapping paragraph numbers to lists of matched signals
    """
    results = {}

    for para_num, para_text in paragraphs.items():
        para_lower = para_text.lower()
        matched_signals = []

        for check in checks:
            phrases = check.get("phrases", [])
            signal = check.get("signal", "unknown")

            for phrase in phrases:
                if phrase.lower() in para_lower:
                    matched_signals.append(signal)
                    break  # Only add signal once per check

        if matched_signals:
            results[para_num] = matched_signals

    return results
