"""IGov decision sync pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import yaml

IGOV_API_BASE = "https://igov.un.org/igov/api"
DEFAULT_SERIES_STARTS = [401, 501]


@dataclass(frozen=True)
class IGovSyncResult:
    session: int
    session_label: str
    total_fetched: int
    total_filtered: int
    new_decisions: list[str]
    updated_decisions: list[str]


def load_igov_config(config_dir: Path) -> dict[str, Any]:
    """Load IGov config if present."""
    config_path = Path(config_dir) / "igov.yaml"
    if not config_path.exists():
        return {}

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    return config.get("igov", config)


def default_session_label(session: int) -> str:
    """Return the default IGov session label for General Assembly."""
    if 10 <= session % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(session % 10, "th")
    return f"{session}{suffix} session of the General Assembly"


def normalize_decision_number(decision_number: str) -> int | None:
    """Extract the numeric decision number from a decision label."""
    if not decision_number:
        return None
    parts = decision_number.split("/")
    if len(parts) < 2:
        return None
    match = re.search(r"\d+", parts[-1])
    if not match:
        return None
    return int(match.group(0))


def decision_in_series(number: int | None, series_starts: list[int]) -> bool:
    """Return True if decision number is within configured series ranges."""
    if number is None:
        return False
    if not series_starts:
        return True

    starts = sorted(series_starts)
    for index, start in enumerate(starts):
        next_start = starts[index + 1] if index + 1 < len(starts) else None
        if number >= start and (next_start is None or number < next_start):
            return True
    return False


def decision_filename(decision_number: str) -> str:
    """Create a safe filename for a decision number."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", decision_number).strip("_")
    return f"{cleaned}.json"


def decision_hash(decision: dict[str, Any]) -> str:
    """Create a stable hash of a decision payload."""
    payload = json.dumps(decision, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_state(state_path: Path) -> dict[str, Any]:
    """Load the IGov sync state file."""
    if not state_path.exists():
        return {"decisions": {}}
    with open(state_path) as f:
        return json.load(f)


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    """Persist the IGov sync state file."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def fetch_decisions(session_label: str, api_base: str = IGOV_API_BASE) -> list[dict[str, Any]]:
    """Fetch IGov decisions for a session label."""
    safe_label = quote(session_label, safe="")
    url = f"{api_base}/decision/getbysession/{safe_label}"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.json()


def sync_igov_decisions(
    session: int,
    data_dir: Path,
    series_starts: list[int] | None = None,
    session_label: str | None = None,
    api_base: str = IGOV_API_BASE,
) -> IGovSyncResult:
    """Sync IGov decisions for a session and detect new/updated entries."""
    series_starts = series_starts or DEFAULT_SERIES_STARTS
    session_label = session_label or default_session_label(session)

    decisions = fetch_decisions(session_label, api_base=api_base)

    igov_dir = Path(data_dir) / "igov"
    decisions_dir = igov_dir / "decisions" / str(session)
    decisions_dir.mkdir(parents=True, exist_ok=True)

    state_path = igov_dir / "state" / f"{session}.json"
    state = load_state(state_path)
    prior_session_state = state.get("decisions", {})

    new_decisions: list[str] = []
    updated_decisions: list[str] = []
    next_session_state: dict[str, dict[str, str]] = {}

    filtered_decisions = []
    for decision in decisions:
        decision_number = str(decision.get("ED_DecisionNumber", "")).strip()
        number_value = normalize_decision_number(decision_number)
        if not decision_in_series(number_value, series_starts):
            continue
        filtered_decisions.append(decision)

        payload_hash = decision_hash(decision)
        prior_hash = prior_session_state.get(decision_number, {}).get("hash")

        if prior_hash is None:
            new_decisions.append(decision_number)
        elif prior_hash != payload_hash:
            updated_decisions.append(decision_number)

        if prior_hash != payload_hash or not (decisions_dir / decision_filename(decision_number)).exists():
            output_path = decisions_dir / decision_filename(decision_number)
            with open(output_path, "w") as f:
                json.dump(decision, f, indent=2, ensure_ascii=True)

        next_session_state[decision_number] = {
            "hash": payload_hash,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    state["session"] = session
    state["session_label"] = session_label
    state["decisions"] = next_session_state
    state["last_sync"] = datetime.now(timezone.utc).isoformat()
    save_state(state_path, state)

    return IGovSyncResult(
        session=session,
        session_label=session_label,
        total_fetched=len(decisions),
        total_filtered=len(filtered_decisions),
        new_decisions=new_decisions,
        updated_decisions=updated_decisions,
    )
