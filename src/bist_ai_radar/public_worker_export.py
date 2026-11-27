from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from .market_calendar import market_session
from .public_research import (
    ISTANBUL,
    PORTFOLIO_LABELS,
    SNAPSHOT_KEY,
    SNAPSHOT_MAX_AGE,
    SYMBOL_PATTERN,
    _format_sector_directory,
    _oldest_price_day,
    _sector_names,
    build_public_help,
    render_public_report,
    sector_report_pages,
    sector_aliases,
    snapshot_status,
)
from .report_snapshot import load_report_snapshot


def _next_close(now: datetime) -> datetime:
    day = now.date()
    while True:
        close_time = market_session(day).close_time
        if close_time is not None:
            close = datetime.combine(day, close_time, tzinfo=ISTANBUL)
            if close > now:
                return close
        day += timedelta(days=1)


def export_worker_reports(directory: Path, snapshot: dict, as_of: datetime) -> int:
    directory.mkdir(parents=True, exist_ok=False)
    companies = snapshot["companies"]
    sectors = _sector_names(companies)
    header = f"Son tarama {snapshot['updated'].replace('T', ' ')}"
    oldest = _oldest_price_day(as_of).isoformat()
    candidates = [item for item in companies if item["eligible"] and item["day"] >= oldest]

    def write(path: str, payload: object) -> None:
        target = directory / f"{path}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    sector_assets = {}
    for index, (key, label) in enumerate([("", ""), *sectors.items()]):
        pages = sector_report_pages(companies, candidates, label, header)
        sector_assets[key] = {"id": index, "label": label, "pages": len(pages)}
        for page, message in enumerate(pages, start=1):
            write(f"sector/{index}/{page}", message)
    for profile in PORTFOLIO_LABELS:
        write(f"portfolio/{profile}", render_public_report(snapshot, "portfoy", profile, as_of))
    write("macro", render_public_report(snapshot, "haber", "", as_of))
    for company in companies:
        symbol = company["symbol"]
        if SYMBOL_PATTERN.fullmatch(symbol):
            write(f"company/{symbol}", {
                "report": render_public_report(snapshot, "tara", symbol, as_of),
                "news": render_public_report(snapshot, "haber", symbol, as_of),
            })

    write("index", {
        "help": build_public_help(_format_sector_directory(sectors), interactive=True),
        "status": snapshot_status(snapshot, as_of),
        "sectors": sector_assets,
        "sectorAliases": sector_aliases(companies),
        "priceExpires": _next_close(as_of).isoformat(),
        "newsExpires": (as_of + timedelta(days=2)).isoformat(),
    })
    return len(companies)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    raw = load_report_snapshot(SNAPSHOT_KEY, SNAPSHOT_MAX_AGE)
    if raw is None:
        raise SystemExit("A fresh public research snapshot is required.")
    snapshot = json.loads(raw)
    if not snapshot["companies"]:
        raise SystemExit("The market universe is empty. Keeping the current Worker deployment.")
    as_of = datetime.fromisoformat(snapshot["updated"])
    count = export_worker_reports(args.directory, snapshot, as_of)
    print(f"Exported Telegram reports for {count} companies.")


if __name__ == "__main__":
    main()
