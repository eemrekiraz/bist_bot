from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .adapters import KapFinancialFeed, KapJsonFeed, KapUniverseFeed, YahooFinanceFeed
from .adapters.http import HttpClient
from .config import load_settings
from .db import connect, init_db
from .macro_news import refresh_macro_news
from .public_research import ISTANBUL, last_completed_session, publish_public_snapshot
from .repositories import MarketRepository
from .source_health import record_source_failure, record_source_success
from .symbol_source_health import (
    record_symbol_source_failure, record_symbol_source_success, symbol_source_attempt_allowed,
)

@dataclass(frozen=True)
class FinancialUniverseScanResult:
    requested: int
    updated: int
    empty: int
    failed: int
    next_cursor: int

    def to_text(self) -> str:
        return (
            "Finansal evren taramasi\n"
            f"Istenen: {self.requested} | Guncellenen: {self.updated} | "
            f"Rapor yok: {self.empty} | Hata: {self.failed}\n"
            f"Sonraki imlec: {self.next_cursor}"
        )


def financial_universe_scan(
    batch_size: int | None = None,
    *,
    time_budget_seconds: int | None = None,
) -> FinancialUniverseScanResult:
    settings = load_settings()
    init_db()
    with connect() as connection:
        repository = MarketRepository(connection)
        symbols = repository.universe_symbols()
        if not symbols:
            print("Financial universe scan skipped: empty universe.")
            return FinancialUniverseScanResult(0, 0, 0, 0, 0)
        state_key = "financial_universe_cursor"
        state = connection.execute(
            "SELECT state_value FROM sync_state WHERE state_key = ?",
            (state_key,),
        ).fetchone()
        cursor = int(state["state_value"]) if state else 0
        requested_batch_size = batch_size or settings.financial_batch_size
        covered_rows = connection.execute(
            "SELECT DISTINCT symbol FROM financial_snapshots"
        ).fetchall()
        covered_symbols = {str(row["symbol"]) for row in covered_rows}
        empty_after = (date.today() - timedelta(days=30)).isoformat()
        empty_rows = connection.execute(
            """
            SELECT SUBSTR(state_key, ?) AS symbol
            FROM sync_state
            WHERE state_key LIKE 'financial_universe_status:%'
              AND state_value = 'EMPTY'
              AND updated_at >= ?
            """,
            (len("financial_universe_status:") + 1, empty_after),
        ).fetchall()
        recently_empty = {str(row["symbol"]) for row in empty_rows}
        missing_symbols = [
            symbol
            for symbol in symbols
            if symbol not in covered_symbols and symbol not in recently_empty
        ]
        refresh_symbols = [symbol for symbol in symbols if symbol in covered_symbols]
        scan_symbols = missing_symbols or refresh_symbols
        if not scan_symbols:
            print("Financial universe scan: all symbols recently checked.")
            return FinancialUniverseScanResult(0, 0, 0, 0, cursor)
        batch = (
            scan_symbols[: min(requested_batch_size, len(scan_symbols))]
            if missing_symbols
            else [
                scan_symbols[(cursor + offset) % len(scan_symbols)]
                for offset in range(min(requested_batch_size, len(scan_symbols)))
            ]
        )
        permalink_by_symbol = {
            str(row["symbol"]): str(row["permalink"] or "")
            for row in connection.execute(
                "SELECT symbol, permalink FROM company_universe"
            ).fetchall()
        }

    updated = 0
    empty = 0
    failed = 0
    processed = 0
    deadline = time.monotonic() + time_budget_seconds if time_budget_seconds else None
    if deadline is None:
        feed = KapFinancialFeed(request_delay_seconds=0.6)
    else:
        feed = KapFinancialFeed(
            client=HttpClient(timeout_seconds=8, max_retries=0), request_delay_seconds=0.6,
        )
    for symbol in batch:
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            snapshots = feed.read_snapshots(
                symbol,
                permalink_by_symbol.get(symbol, ""),
            )
        except Exception as error:
            failed += 1
            processed += 1
            print(f"Financial universe fetch failed for {symbol}: {error}")
            if "HTTP 429" in str(error):
                print("Financial universe paused by KAP rate limit.")
                break
            time.sleep(0.6)
            continue
        if snapshots:
            with connect() as connection:
                MarketRepository(connection).upsert_financial_snapshots(snapshots)
                _record_financial_universe_status(connection, symbol, "READY")
            updated += 1
        else:
            with connect() as connection:
                _record_financial_universe_status(connection, symbol, "EMPTY")
            empty += 1
        processed += 1
        time.sleep(0.6)

    next_cursor = (
        0
        if missing_symbols
        else (cursor + processed) % len(scan_symbols)
    )
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO sync_state (state_key, state_value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(state_key) DO UPDATE SET
                state_value = excluded.state_value,
                updated_at = excluded.updated_at
            """,
            (state_key, str(next_cursor)),
        )
    result = FinancialUniverseScanResult(
        requested=len(batch),
        updated=updated,
        empty=empty,
        failed=failed,
        next_cursor=next_cursor,
    )
    print(result.to_text())
    return result


def _record_financial_universe_status(
    connection: object,
    symbol: str,
    status: str,
) -> None:
    connection.execute(
        """
        INSERT INTO sync_state (state_key, state_value, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(state_key) DO UPDATE SET
            state_value = excluded.state_value,
            updated_at = excluded.updated_at
        """,
        (f"financial_universe_status:{symbol}", status),
    )


def public_news_refresh(*, client: HttpClient | None = None) -> None:
    settings = load_settings()
    init_db()
    try:
        items = KapJsonFeed(
            settings.kap_feed_url, client=client or HttpClient(timeout_seconds=10, max_retries=1)
        ).read_market_news(datetime.now(ISTANBUL).date())
    except Exception as error:
        with connect() as connection:
            record_source_failure(connection, "KAP_NEWS", error)
        print(f"Public KAP refresh failed: {error}")
    else:
        with connect() as connection:
            repository = MarketRepository(connection)
            listed = set(repository.universe_symbols())
            company_items = [
                item for item in items
                if item.symbol != "GENEL" and (not listed or item.symbol in listed)
                and not repository.news_item_exists(item)
            ]
            stored = repository.insert_news_items(company_items)
            if items:
                record_source_success(connection, "KAP_NEWS")
        print(f"Public KAP refresh: {stored} new records.")
    try:
        result = refresh_macro_news(client=client)
        print(f"Public macro refresh: {result.stored} new records.")
    finally:
        publish_public_snapshot()


def public_close_refresh(*, price_budget_seconds: int | None = None) -> None:
    settings = load_settings()
    init_db()
    completed_day = last_completed_session(datetime.now(ISTANBUL))
    client = HttpClient(timeout_seconds=8, max_retries=0)
    try:
        companies = KapUniverseFeed(client=client).read_companies()
        if companies:
            with connect() as connection:
                MarketRepository(connection).upsert_companies(companies)
    except Exception as error:
        print(f"Public universe refresh failed: {error}")
    with connect() as connection:
        symbols = MarketRepository(connection).universe_symbols()
        latest_days = {
            str(row["symbol"]): str(row["day"]) for row in connection.execute(
                """
                SELECT symbol, MAX(day) AS day FROM price_bars
                WHERE day <= ? AND raw_close > 0 GROUP BY symbol
                """,
                (completed_day.isoformat(),),
            ).fetchall()
        }
    deadline = time.monotonic() + price_budget_seconds if price_budget_seconds else None
    feed = YahooFinanceFeed(client=client, base_url=settings.yahoo_chart_base_url)
    missed = 0
    for symbol in sorted(symbols, key=lambda item: latest_days.get(item, "")):
        if deadline is not None and time.monotonic() >= deadline:
            print("Public price refresh reached its time budget.")
            break
        if latest_days.get(symbol) == completed_day.isoformat():
            continue
        with connect() as connection:
            if not symbol_source_attempt_allowed(connection, "YAHOO", symbol):
                continue
        try:
            bars = [
                bar for bar in feed.read_price_bars(symbol, days=220)
                if bar.day <= completed_day
            ]
            if not bars or bars[-1].day != completed_day:
                continue
        except Exception as error:
            with connect() as connection:
                record_symbol_source_failure(connection, "YAHOO", symbol, error)
            missed += 1
            if missed >= 8 or "HTTP 429" in str(error):
                print("Public price refresh paused after repeated errors or rate limit.")
                break
        else:
            with connect() as connection:
                MarketRepository(connection).upsert_refreshed_price_bars(bars)
                record_symbol_source_success(connection, "YAHOO", symbol)
            missed = 0
        finally:
            time.sleep(0.5)
    publish_public_snapshot()
    if symbols:
        if deadline is None:
            financial_universe_scan()
        else:
            financial_universe_scan(batch_size=24, time_budget_seconds=240)
        publish_public_snapshot()

def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "public-cloud-refresh":
        public_close_refresh(price_budget_seconds=720)
    elif command == "public-cloud-news":
        public_news_refresh(client=HttpClient(timeout_seconds=8, max_retries=0))
    else:
        raise SystemExit("Use public-cloud-refresh or public-cloud-news.")


if __name__ == "__main__":
    main()
