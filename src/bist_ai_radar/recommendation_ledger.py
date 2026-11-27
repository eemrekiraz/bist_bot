"""Append-only, hash-chained ledger of published portfolio recommendations.

Every entry is written once, at the time the recommendation is published, and
never edited. Each line stores the SHA-256 of the previous line, so any later
edit, deletion or reordering is detected by ``verify_ledger``. Entries that
would be recorded long after the snapshot they come from are refused: a
recommendation reconstructed after the fact must never look like one that was
recorded in real time.

The ledger is a plain directory of JSON Lines files so it can be copied to any
durable store without conversion.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .public_research import (
    ISTANBUL,
    MAIN_SECTORS,
    METHOD_NAME,
    METHOD_VERSION,
    PORTFOLIO_LABELS,
    eligible_candidates,
    last_completed_session,
    sector_key,
    select_portfolio,
)

LEDGER_FILE = "recommendations.jsonl"
SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64
# A snapshot older than this is not recorded: it would no longer be a
# real-time record of what the bot published.
MAX_RECORDING_DELAY = timedelta(hours=6)


class LedgerError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecordResult:
    added: int
    skipped_existing: int
    total: int


def _canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _entry_hash(body: dict) -> str:
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def read_ledger(directory: Path) -> list[dict]:
    """Return all entries after verifying the hash chain."""
    path = Path(directory) / LEDGER_FILE
    if not path.exists():
        return []
    entries: list[dict] = []
    previous = GENESIS_HASH
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise LedgerError(f"Line {number}: empty line in ledger.")
        try:
            entry = json.loads(line)
        except ValueError as error:
            raise LedgerError(f"Line {number}: not valid JSON.") from error
        stored_hash = entry.pop("entry_hash", None)
        if entry.get("prev_hash") != previous:
            raise LedgerError(f"Line {number}: chain broken (previous hash mismatch).")
        if stored_hash != _entry_hash(entry):
            raise LedgerError(f"Line {number}: entry content was modified.")
        if entry["entry_id"] in seen:
            raise LedgerError(f"Line {number}: duplicate entry id.")
        seen.add(entry["entry_id"])
        entry["entry_hash"] = stored_hash
        entries.append(entry)
        previous = stored_hash
    return entries


def verify_ledger(directory: Path) -> int:
    return len(read_ledger(directory))


def build_entries(snapshot: dict, profiles: tuple[str, ...] = tuple(PORTFOLIO_LABELS)) -> list[dict]:
    """Recommendation bodies for the portfolios exactly as the bot shows them."""
    published_at = datetime.fromisoformat(snapshot["updated"])
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=ISTANBUL)
    companies = snapshot["companies"]
    candidates = eligible_candidates(companies, published_at)
    cutoff = last_completed_session(published_at).isoformat()
    entries = []
    for profile in profiles:
        for rank, company in enumerate(select_portfolio(candidates, profile), start=1):
            if not company.get("close"):
                continue
            group = sector_key(company["sector"])
            peers = sorted(
                item["symbol"] for item in companies
                if sector_key(item["sector"]) == group and item["day"] == company["day"]
            )
            entries.append({
                "schema": SCHEMA_VERSION,
                "entry_id": f"{published_at.date().isoformat()}:{profile}:{company['symbol']}",
                "published_at": published_at.isoformat(timespec="minutes"),
                "data_cutoff": cutoff,
                "symbol": company["symbol"],
                "title": company.get("title", ""),
                "main_sector": group,
                "main_sector_label": MAIN_SECTORS[group][0] if group else "",
                "original_sector": company["sector"],
                "sector_peers": peers,
                "close_day": company["day"],
                "close_price": float(company["close"]),
                "financial_period": company.get("period", ""),
                "profile": profile,
                "rank": rank,
                "score": round(float(company["scores"][profile]), 6),
                "reasons": list(company.get("reasons", [])),
                "risk": company.get("risk", ""),
                "method": METHOD_NAME,
                "method_version": METHOD_VERSION,
            })
    return entries


def record_snapshot(directory: Path, snapshot: dict, now: datetime | None = None) -> RecordResult:
    """Append the snapshot's recommendations; existing entries are never touched."""
    recorded_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    published_at = datetime.fromisoformat(snapshot["updated"])
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=ISTANBUL)
    delay = recorded_at - published_at
    if delay < -timedelta(minutes=5):
        raise LedgerError("Snapshot time is in the future; refusing to record.")
    if delay > MAX_RECORDING_DELAY:
        raise LedgerError(
            "Snapshot is too old to be recorded as a real-time recommendation; refusing to backfill."
        )
    directory = Path(directory)
    existing = read_ledger(directory)
    known = {entry["entry_id"] for entry in existing}
    previous = existing[-1]["entry_hash"] if existing else GENESIS_HASH
    lines = []
    skipped = 0
    for body in build_entries(snapshot):
        if body["entry_id"] in known:
            skipped += 1
            continue
        body = {**body, "recorded_at": recorded_at.isoformat(timespec="seconds"), "prev_hash": previous}
        digest = _entry_hash(body)
        lines.append(_canonical({**body, "entry_hash": digest}))
        known.add(body["entry_id"])
        previous = digest
    if lines:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / LEDGER_FILE).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        read_ledger(directory)
    return RecordResult(added=len(lines), skipped_existing=skipped, total=len(existing) + len(lines))
