"""Command line jobs for the recommendation ledger.

    record          append today's published portfolios to the ledger
    evaluate        compute matured outcomes and write a summary
    training-check  assess training need; notify only the administrator once

None of these commands trains a model or schedules training.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .adapters.http import HttpClient
from .db import connect, init_db
from .public_research import SNAPSHOT_KEY, SNAPSHOT_MAX_AGE
from .recommendation_ledger import read_ledger, record_snapshot
from .recommendation_outcomes import BENCHMARK_SYMBOL, HORIZONS, evaluate_ledger, summarize
from .report_snapshot import load_report_snapshot
from .repositories import MarketRepository
from .training_need import Assessment, assess, load_policy

NOTICE_FILE = "training_notices.jsonl"
SUMMARY_FILE = "evaluation-latest.json"
HISTORY_LIMIT = max(HORIZONS) + 160


def load_bars(entries: list[dict]) -> dict:
    symbols = {BENCHMARK_SYMBOL}
    for entry in entries:
        symbols.add(entry["symbol"])
        symbols.update(entry.get("sector_peers", []))
    init_db()
    with connect() as connection:
        repository = MarketRepository(connection)
        return {symbol: repository.latest_bars(symbol, limit=HISTORY_LIMIT) for symbol in symbols}


def run_evaluation(directory: Path, bars_by_symbol: dict | None = None) -> tuple[list[dict], list, dict]:
    entries = read_ledger(directory)
    bars = bars_by_symbol if bars_by_symbol is not None else load_bars(entries)
    outcomes = evaluate_ledger(entries, bars)
    matured_ids = {item.entry_id for item in outcomes}
    summary = summarize(outcomes, pending=sum(entry["entry_id"] not in matured_ids for entry in entries))
    return entries, outcomes, summary


def _percent(value: float | None) -> str:
    return "—" if value is None else f"%{value * 100:.1f}".replace(".", ",")


def render_notice(assessment: Assessment) -> str:
    evidence = assessment.evidence
    lines = [
        "YÖNETİM • Eğitim ihtiyacı",
        "",
        "Gerekçe:",
        *[f"• {reason.text}" for reason in assessment.reasons],
        "",
        "Veri özeti:",
        f"• Öneri defteri: {evidence.get('ledger_entries', 0)} kayıt",
        f"• Olgun sonuç ({evidence.get('horizon')} seans): {evidence.get('matured_compared', 0)}",
        f"• BIST'i geçen oran: {_percent(evidence.get('beat_benchmark'))}",
        f"• BIST'e göre ortalama fark: {_percent(evidence.get('mean_excess_vs_benchmark'))}",
        f"• Piyasa rejimleri: {', '.join(evidence.get('regimes') or []) or '—'}",
        f"• Canlı yöntem sürümü: {evidence.get('method_version')}",
        "",
        "Eğitim başlatılmadı. Başlatmak için yerel bilgisayarda açık talimat gerekir.",
    ]
    return "\n".join(lines)


def _sent_fingerprints(directory: Path) -> set[str]:
    path = Path(directory) / NOTICE_FILE
    if not path.exists():
        return set()
    return {
        json.loads(line)["fingerprint"]
        for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    }


def send_admin_message(text: str, *, client: HttpClient | None = None) -> None:
    """Send to the single administrator chat configured as a secret."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise RuntimeError("Administrator Telegram secrets are not configured.")
    http = client or HttpClient(timeout_seconds=15, max_retries=1)
    try:
        response = http.post_json(
            f"https://api.telegram.org/bot{token}/sendMessage",
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )
    except Exception:
        # The request URL contains the bot token; never let it reach the logs.
        raise RuntimeError("Administrator notice could not be delivered.") from None
    if not isinstance(response, dict) or not response.get("ok"):
        raise RuntimeError("Telegram rejected the administrator notice.")


def notify_if_needed(
    directory: Path, assessment: Assessment, *, send: bool, sender=send_admin_message,
    now: datetime | None = None,
) -> str:
    if not assessment.needed:
        return "no_need"
    fingerprint = assessment.fingerprint()
    if fingerprint in _sent_fingerprints(directory):
        return "already_notified"
    if not send:
        return "would_notify"
    sender(render_notice(assessment))
    record = {
        "fingerprint": fingerprint,
        "sent_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "reasons": [reason.code for reason in assessment.reasons],
    }
    Path(directory).mkdir(parents=True, exist_ok=True)
    with (Path(directory) / NOTICE_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return "notified"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m bist_ai_radar.recommendation_jobs")
    parser.add_argument("command", choices=("record", "evaluate", "training-check"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--send", action="store_true", help="send the administrator notice (training-check)")
    args = parser.parse_args(argv)

    if args.command == "record":
        raw = load_report_snapshot(SNAPSHOT_KEY, SNAPSHOT_MAX_AGE)
        if raw is None:
            raise SystemExit("A fresh public research snapshot is required.")
        result = record_snapshot(args.directory, json.loads(raw))
        print(f"Ledger: {result.added} new, {result.skipped_existing} already recorded, {result.total} total.")
        return

    entries, outcomes, summary = run_evaluation(args.directory)
    if args.command == "evaluate":
        args.directory.mkdir(parents=True, exist_ok=True)
        (args.directory / SUMMARY_FILE).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(f"Evaluated {len(entries)} entries; {len(outcomes)} matured outcomes; {summary['pending_entries']} pending.")
        return

    assessment = assess(entries, outcomes, load_policy(args.directory))
    status = notify_if_needed(args.directory, assessment, send=args.send)
    print(f"Training need: {assessment.status}; notice: {status}. No training was started.")


if __name__ == "__main__":
    main()
