from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_REPORT_SNAPSHOT_DIR = Path("data/report_snapshots")
_SAFE_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


def load_report_snapshot(
    key: str,
    max_age_seconds: int,
    directory: Path = DEFAULT_REPORT_SNAPSHOT_DIR,
    now: datetime | None = None,
) -> str | None:
    path = _snapshot_path(key, directory)
    if not path.exists() or max_age_seconds <= 0:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        generated_at = datetime.fromisoformat(str(payload["generated_at"]))
        text = str(payload["text"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if (now or datetime.now()) - generated_at > timedelta(seconds=max_age_seconds):
        return None
    return text


def save_report_snapshot(
    key: str,
    text: str,
    directory: Path = DEFAULT_REPORT_SNAPSHOT_DIR,
    now: datetime | None = None,
) -> Path:
    path = _snapshot_path(key, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = {
        "key": key,
        "generated_at": (now or datetime.now()).isoformat(timespec="seconds"),
        "text": text,
    }
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def get_or_build_report_snapshot(
    key: str,
    builder: Callable[[], str],
    max_age_seconds: int,
    directory: Path = DEFAULT_REPORT_SNAPSHOT_DIR,
) -> str:
    cached = load_report_snapshot(key, max_age_seconds, directory)
    if cached is not None:
        return cached
    text = builder()
    save_report_snapshot(key, text, directory)
    return text


def _snapshot_path(key: str, directory: Path) -> Path:
    if not _SAFE_KEY.fullmatch(key):
        raise ValueError(f"Gecersiz rapor snapshot anahtari: {key!r}")
    return Path(directory) / f"{key}.json"
