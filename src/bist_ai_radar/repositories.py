from __future__ import annotations

import sqlite3
from datetime import date, datetime

from .models import (
    CompanyProfile,
    FinancialSnapshot,
    MacroNewsItem,
    NewsItem,
    PriceBar,
)
from .research_facts import CompanyResearchFact, extract_company_research_facts


class MarketRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def upsert_price_bars(self, bars: list[PriceBar]) -> int:
        self.connection.executemany(
            """
            INSERT INTO price_bars (
                symbol, day, open, high, low, close, volume,
                raw_open, raw_high, raw_low, raw_close, source, fetched_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, day) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                raw_open = COALESCE(excluded.raw_open, price_bars.raw_open),
                raw_high = COALESCE(excluded.raw_high, price_bars.raw_high),
                raw_low = COALESCE(excluded.raw_low, price_bars.raw_low),
                raw_close = COALESCE(excluded.raw_close, price_bars.raw_close),
                source = CASE
                    WHEN excluded.source <> '' THEN excluded.source
                    ELSE price_bars.source
                END,
                fetched_at = excluded.fetched_at
            """,
            [
                (
                    bar.symbol,
                    bar.day.isoformat(),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.raw_open,
                    bar.raw_high,
                    bar.raw_low,
                    bar.raw_close,
                    bar.source,
                    datetime.now().isoformat(timespec="seconds"),
                )
                for bar in bars
            ],
        )
        return len(bars)

    def upsert_refreshed_price_bars(self, bars: list[PriceBar]) -> int:
        windows: dict[str, tuple[str, str]] = {}
        for bar in bars:
            current = windows.get(bar.symbol)
            day = bar.day.isoformat()
            if current is None:
                windows[bar.symbol] = (day, day)
            else:
                windows[bar.symbol] = (min(current[0], day), max(current[1], day))
        for symbol, (start_day, end_day) in windows.items():
            self.connection.execute(
                """
                DELETE FROM price_bars
                WHERE symbol = ?
                  AND day BETWEEN ? AND ?
                  AND COALESCE(source, '') = ''
                  AND raw_close IS NULL
                """,
                (symbol, start_day, end_day),
            )
        return self.upsert_price_bars(bars)

    def insert_news_items(self, items: list[NewsItem]) -> int:
        cursor = self.connection.executemany(
            """
            INSERT OR IGNORE INTO news_items (
                symbol, published_at, source, title, body, disclosure_index, source_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.symbol,
                    item.published_at.isoformat(),
                    item.source,
                    item.title,
                    item.body,
                    item.disclosure_index,
                    item.source_url,
                )
                for item in items
            ],
        )
        inserted_news = max(0, int(cursor.rowcount))
        facts = [
            fact
            for item in items
            for fact in extract_company_research_facts(item)
        ]
        if facts:
            self.upsert_company_research_facts(facts)
        return inserted_news

    def upsert_company_research_facts(
        self,
        facts: list[CompanyResearchFact],
    ) -> None:
        self.connection.executemany(
            """
            INSERT OR IGNORE INTO company_research_facts (
                symbol, fact_type, published_at, disclosure_index, value_text,
                numeric_value, unit, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    fact.symbol,
                    fact.fact_type,
                    fact.published_at,
                    fact.disclosure_index,
                    fact.value_text,
                    fact.numeric_value,
                    fact.unit,
                    fact.source_url,
                )
                for fact in facts
            ],
        )

    def latest_company_research_facts(
        self,
        symbol: str,
        limit: int = 5,
    ) -> list[CompanyResearchFact]:
        rows = self.connection.execute(
            """
            SELECT symbol, fact_type, published_at, disclosure_index, value_text,
                   numeric_value, unit, source_url
            FROM company_research_facts
            WHERE symbol = ?
            ORDER BY published_at DESC, id DESC
            LIMIT ?
            """,
            (symbol.upper(), max(1, limit)),
        ).fetchall()
        return [
            CompanyResearchFact(
                symbol=str(row["symbol"]),
                fact_type=str(row["fact_type"]),
                published_at=str(row["published_at"]),
                disclosure_index=(
                    int(row["disclosure_index"])
                    if row["disclosure_index"] is not None
                    else None
                ),
                value_text=str(row["value_text"]),
                numeric_value=self._optional_float(row["numeric_value"]),
                unit=str(row["unit"] or ""),
                source_url=str(row["source_url"] or ""),
            )
            for row in rows
        ]

    def news_item_exists(self, item: NewsItem) -> bool:
        row = self.connection.execute(
            """
            SELECT 1
            FROM news_items
            WHERE symbol = ? AND published_at = ? AND source = ? AND title = ?
            LIMIT 1
            """,
            (item.symbol, item.published_at.isoformat(), item.source, item.title),
        ).fetchone()
        return row is not None

    def claim_alert(self, alert_key: str) -> bool:
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO alert_events (alert_key, created_at)
            VALUES (?, ?)
            """,
            (alert_key, datetime.now().isoformat(timespec="seconds")),
        )
        return cursor.rowcount == 1

    def latest_bars(self, symbol: str, limit: int = 120) -> list[PriceBar]:
        rows = self.connection.execute(
            """
            SELECT symbol, day, open, high, low, close, volume,
                   raw_open, raw_high, raw_low, raw_close, source
            FROM price_bars
            WHERE symbol = ?
            ORDER BY day DESC
            LIMIT ?
            """,
            (symbol.upper(), limit),
        ).fetchall()
        return [
            PriceBar(
                symbol=row["symbol"],
                day=datetime.fromisoformat(row["day"]).date(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
                raw_open=self._optional_float(row["raw_open"]),
                raw_high=self._optional_float(row["raw_high"]),
                raw_low=self._optional_float(row["raw_low"]),
                raw_close=self._optional_float(row["raw_close"]),
                source=str(row["source"] or ""),
            )
            for row in reversed(rows)
        ]

    def symbols(self) -> list[str]:
        rows = self.connection.execute(
            "SELECT DISTINCT symbol FROM price_bars ORDER BY symbol"
        ).fetchall()
        return [str(row["symbol"]) for row in rows]

    def upsert_financial_snapshots(self, snapshots: list[FinancialSnapshot]) -> int:
        self.connection.executemany(
            """
            INSERT INTO financial_snapshots (
                symbol, period, currency_scale, current_assets, total_assets,
                current_liabilities, total_liabilities, equity, paid_capital,
                revenue, gross_profit, operating_profit, net_income, updated_at
                , operating_cash_flow, capital_expenditures, cash_and_equivalents,
                dividends_paid
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, period) DO UPDATE SET
                currency_scale = excluded.currency_scale,
                current_assets = excluded.current_assets,
                total_assets = excluded.total_assets,
                current_liabilities = excluded.current_liabilities,
                total_liabilities = excluded.total_liabilities,
                equity = excluded.equity,
                paid_capital = excluded.paid_capital,
                revenue = excluded.revenue,
                gross_profit = excluded.gross_profit,
                operating_profit = excluded.operating_profit,
                net_income = excluded.net_income,
                operating_cash_flow = excluded.operating_cash_flow,
                capital_expenditures = excluded.capital_expenditures,
                cash_and_equivalents = excluded.cash_and_equivalents,
                dividends_paid = excluded.dividends_paid,
                updated_at = excluded.updated_at
            """,
            [
                (
                    item.symbol,
                    item.period,
                    item.currency_scale,
                    item.current_assets,
                    item.total_assets,
                    item.current_liabilities,
                    item.total_liabilities,
                    item.equity,
                    item.paid_capital,
                    item.revenue,
                    item.gross_profit,
                    item.operating_profit,
                    item.net_income,
                    datetime.now().isoformat(timespec="seconds"),
                    item.operating_cash_flow,
                    item.capital_expenditures,
                    item.cash_and_equivalents,
                    item.dividends_paid,
                )
                for item in snapshots
            ],
        )
        return len(snapshots)

    def financial_snapshots(self, symbol: str) -> list[FinancialSnapshot]:
        rows = self.connection.execute(
            """
            SELECT symbol, period, currency_scale, current_assets, total_assets,
                   current_liabilities, total_liabilities, equity, paid_capital,
                   revenue, gross_profit, operating_profit, net_income
                   , operating_cash_flow, capital_expenditures,
                   cash_and_equivalents, dividends_paid
            FROM financial_snapshots
            WHERE symbol = ?
            """,
            (symbol.upper(),),
        ).fetchall()
        snapshots = [
            FinancialSnapshot(
                symbol=row["symbol"],
                period=row["period"],
                currency_scale=float(row["currency_scale"]),
                current_assets=self._optional_float(row["current_assets"]),
                total_assets=self._optional_float(row["total_assets"]),
                current_liabilities=self._optional_float(row["current_liabilities"]),
                total_liabilities=self._optional_float(row["total_liabilities"]),
                equity=self._optional_float(row["equity"]),
                paid_capital=self._optional_float(row["paid_capital"]),
                revenue=self._optional_float(row["revenue"]),
                gross_profit=self._optional_float(row["gross_profit"]),
                operating_profit=self._optional_float(row["operating_profit"]),
                net_income=self._optional_float(row["net_income"]),
                operating_cash_flow=self._optional_float(row["operating_cash_flow"]),
                capital_expenditures=self._optional_float(row["capital_expenditures"]),
                cash_and_equivalents=self._optional_float(row["cash_and_equivalents"]),
                dividends_paid=self._optional_float(row["dividends_paid"]),
            )
            for row in rows
        ]
        versioned = self.financial_snapshots_as_of(symbol, datetime.now())
        merged = {item.period: item for item in snapshots}
        merged.update({item.period: item for item in versioned})
        return sorted(
            merged.values(),
            key=lambda item: tuple(int(part) for part in item.period.split("/")),
        )

    def upsert_financial_versions(self, snapshots: list[FinancialSnapshot]) -> int:
        versioned = [
            item
            for item in snapshots
            if item.published_at is not None and item.disclosure_index is not None
        ]
        self.connection.executemany(
            """
            INSERT INTO financial_snapshot_versions (
                symbol, period, disclosure_index, published_at, currency_scale,
                current_assets, total_assets, current_liabilities, total_liabilities,
                equity, paid_capital, revenue, gross_profit, operating_profit,
                net_income, source, updated_at
                , operating_cash_flow, capital_expenditures,
                cash_and_equivalents, dividends_paid
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, period, disclosure_index) DO UPDATE SET
                published_at = excluded.published_at,
                currency_scale = excluded.currency_scale,
                current_assets = excluded.current_assets,
                total_assets = excluded.total_assets,
                current_liabilities = excluded.current_liabilities,
                total_liabilities = excluded.total_liabilities,
                equity = excluded.equity,
                paid_capital = excluded.paid_capital,
                revenue = excluded.revenue,
                gross_profit = excluded.gross_profit,
                operating_profit = excluded.operating_profit,
                net_income = excluded.net_income,
                operating_cash_flow = excluded.operating_cash_flow,
                capital_expenditures = excluded.capital_expenditures,
                cash_and_equivalents = excluded.cash_and_equivalents,
                dividends_paid = excluded.dividends_paid,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            [
                (
                    item.symbol,
                    item.period,
                    item.disclosure_index,
                    item.published_at.isoformat(),
                    item.currency_scale,
                    item.current_assets,
                    item.total_assets,
                    item.current_liabilities,
                    item.total_liabilities,
                    item.equity,
                    item.paid_capital,
                    item.revenue,
                    item.gross_profit,
                    item.operating_profit,
                    item.net_income,
                    item.source,
                    datetime.now().isoformat(timespec="seconds"),
                    item.operating_cash_flow,
                    item.capital_expenditures,
                    item.cash_and_equivalents,
                    item.dividends_paid,
                )
                for item in versioned
            ],
        )
        return len(versioned)

    def financial_snapshots_as_of(
        self,
        symbol: str,
        as_of: datetime,
    ) -> list[FinancialSnapshot]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM (
                SELECT symbol, period, disclosure_index, published_at,
                       currency_scale, current_assets, total_assets,
                       current_liabilities, total_liabilities, equity,
                       paid_capital, revenue, gross_profit, operating_profit,
                       net_income, source,
                       operating_cash_flow, capital_expenditures,
                       cash_and_equivalents, dividends_paid,
                       ROW_NUMBER() OVER (
                           PARTITION BY symbol, period
                           ORDER BY published_at DESC, disclosure_index DESC
                       ) AS version_rank
                FROM financial_snapshot_versions
                WHERE symbol = ? AND published_at <= ?
            )
            WHERE version_rank = 1
            """,
            (symbol.upper(), as_of.isoformat()),
        ).fetchall()
        return sorted(
            [
                FinancialSnapshot(
                    symbol=row["symbol"],
                    period=row["period"],
                    currency_scale=float(row["currency_scale"]),
                    current_assets=self._optional_float(row["current_assets"]),
                    total_assets=self._optional_float(row["total_assets"]),
                    current_liabilities=self._optional_float(row["current_liabilities"]),
                    total_liabilities=self._optional_float(row["total_liabilities"]),
                    equity=self._optional_float(row["equity"]),
                    paid_capital=self._optional_float(row["paid_capital"]),
                    revenue=self._optional_float(row["revenue"]),
                    gross_profit=self._optional_float(row["gross_profit"]),
                    operating_profit=self._optional_float(row["operating_profit"]),
                    net_income=self._optional_float(row["net_income"]),
                    operating_cash_flow=self._optional_float(row["operating_cash_flow"]),
                    capital_expenditures=self._optional_float(row["capital_expenditures"]),
                    cash_and_equivalents=self._optional_float(row["cash_and_equivalents"]),
                    dividends_paid=self._optional_float(row["dividends_paid"]),
                    published_at=datetime.fromisoformat(row["published_at"]),
                    disclosure_index=int(row["disclosure_index"]),
                    source=str(row["source"]),
                )
                for row in rows
            ],
            key=lambda item: tuple(int(part) for part in item.period.split("/")),
        )

    def financial_symbols(self) -> list[str]:
        rows = self.connection.execute(
            "SELECT DISTINCT symbol FROM financial_snapshots ORDER BY symbol"
        ).fetchall()
        return [str(row["symbol"]) for row in rows]

    def _optional_float(self, value: object) -> float | None:
        return float(value) if value is not None else None

    def upsert_companies(self, companies: list[CompanyProfile]) -> int:
        self.connection.executemany(
            """
            INSERT INTO company_universe (
                symbol, title, city, permalink, sector, is_active,
                first_trade_day, last_trade_day, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                title = CASE
                    WHEN excluded.is_active = 1 OR company_universe.is_active = 0
                    THEN excluded.title ELSE company_universe.title END,
                city = CASE
                    WHEN excluded.is_active = 1 OR company_universe.is_active = 0
                    THEN excluded.city ELSE company_universe.city END,
                permalink = CASE
                    WHEN excluded.permalink <> '' THEN excluded.permalink
                    ELSE company_universe.permalink END,
                sector = CASE
                    WHEN excluded.sector <> '' THEN excluded.sector
                    ELSE company_universe.sector END,
                is_active = CASE
                    WHEN company_universe.is_active >= excluded.is_active
                    THEN company_universe.is_active ELSE excluded.is_active END,
                first_trade_day = COALESCE(
                    company_universe.first_trade_day,
                    excluded.first_trade_day
                ),
                last_trade_day = CASE
                    WHEN excluded.is_active = 1 THEN NULL
                    ELSE COALESCE(excluded.last_trade_day, company_universe.last_trade_day)
                END,
                source = CASE
                    WHEN excluded.is_active = 1 THEN excluded.source
                    ELSE company_universe.source END,
                updated_at = excluded.updated_at
            """,
            [
                (
                    company.symbol,
                    company.title,
                    company.city,
                    company.permalink,
                    company.sector,
                    int(company.is_active),
                    (
                        company.first_trade_day.isoformat()
                        if company.first_trade_day
                        else None
                    ),
                    (
                        company.last_trade_day.isoformat()
                        if company.last_trade_day
                        else None
                    ),
                    company.source,
                    datetime.now().isoformat(timespec="seconds"),
                )
                for company in companies
            ],
        )
        return len(companies)

    def universe_symbols(self) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT symbol
            FROM company_universe
            WHERE is_active = 1
            ORDER BY symbol
            """
        ).fetchall()
        return [str(row["symbol"]) for row in rows]

    def archived_symbols(self) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT symbol
            FROM company_universe
            WHERE is_active = 0
            ORDER BY symbol
            """
        ).fetchall()
        return [str(row["symbol"]) for row in rows]

    def research_symbols(self) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT symbol
            FROM company_universe
            WHERE is_active = 1
               OR EXISTS (
                    SELECT 1 FROM price_bars
                    WHERE price_bars.symbol = company_universe.symbol
               )
            ORDER BY symbol
            """
        ).fetchall()
        return [str(row["symbol"]) for row in rows]

    def research_universe_metadata(
        self,
    ) -> dict[str, tuple[str, date | None, date | None, bool]]:
        rows = self.connection.execute(
            """
            SELECT symbol, sector, first_trade_day, last_trade_day, is_active
            FROM company_universe
            WHERE is_active = 1
               OR EXISTS (
                    SELECT 1 FROM price_bars
                    WHERE price_bars.symbol = company_universe.symbol
               )
            """
        ).fetchall()
        return {
            str(row["symbol"]): (
                str(row["sector"] or ""),
                date.fromisoformat(str(row["first_trade_day"]))
                if row["first_trade_day"]
                else None,
                date.fromisoformat(str(row["last_trade_day"]))
                if row["last_trade_day"]
                else None,
                bool(row["is_active"]),
            )
            for row in rows
        }

    def refresh_listing_periods(self, symbols: list[str] | None = None) -> int:
        selected = symbols or self.research_symbols()
        updated = 0
        for symbol in selected:
            bounds = self.connection.execute(
                """
                SELECT MIN(day) AS first_day, MAX(day) AS last_day
                FROM price_bars
                WHERE symbol = ?
                """,
                (symbol,),
            ).fetchone()
            if not bounds or bounds["first_day"] is None:
                continue
            self.connection.execute(
                """
                UPDATE company_universe
                SET first_trade_day = ?,
                    last_trade_day = CASE WHEN is_active = 1 THEN NULL ELSE ? END
                WHERE symbol = ?
                """,
                (bounds["first_day"], bounds["last_day"], symbol),
            )
            updated += 1
        return updated

    def prune_archived_price_bars(self, symbols: list[str] | None = None) -> int:
        selected = symbols or self.archived_symbols()
        removed = 0
        for symbol in selected:
            row = self.connection.execute(
                """
                SELECT MAX(day) AS last_traded_day
                FROM price_bars
                WHERE symbol = ? AND volume > 0
                """,
                (symbol,),
            ).fetchone()
            last_traded_day = row["last_traded_day"] if row else None
            if last_traded_day is None:
                cursor = self.connection.execute(
                    "DELETE FROM price_bars WHERE symbol = ?",
                    (symbol,),
                )
            else:
                cursor = self.connection.execute(
                    "DELETE FROM price_bars WHERE symbol = ? AND day > ?",
                    (symbol, last_traded_day),
                )
            removed += max(0, int(cursor.rowcount))
        return removed

    def company_sector(self, symbol: str) -> str:
        row = self.connection.execute(
            "SELECT sector FROM company_universe WHERE symbol = ?",
            (symbol.upper(),),
        ).fetchone()
        return str(row["sector"]) if row else ""

    def company_title(self, symbol: str) -> str:
        row = self.connection.execute(
            "SELECT title FROM company_universe WHERE symbol = ?",
            (symbol.upper(),),
        ).fetchone()
        return str(row["title"]) if row else symbol.upper()

    def company_permalink(self, symbol: str) -> str:
        row = self.connection.execute(
            "SELECT permalink FROM company_universe WHERE symbol = ?",
            (symbol.upper(),),
        ).fetchone()
        return str(row["permalink"]) if row else ""

    def sector_symbols(self, sector: str) -> list[str]:
        if not sector:
            return []
        rows = self.connection.execute(
            "SELECT symbol FROM company_universe WHERE sector = ? ORDER BY symbol",
            (sector,),
        ).fetchall()
        return [str(row["symbol"]) for row in rows]

    def macro_news_exists(self, item: MacroNewsItem) -> bool:
        row = self.connection.execute(
            """
            SELECT 1 FROM macro_news
            WHERE source = ? AND published_at = ? AND title = ?
            LIMIT 1
            """,
            (item.source, item.published_at.isoformat(), item.title),
        ).fetchone()
        return row is not None

    def insert_macro_news(self, items: list[MacroNewsItem]) -> int:
        cursor = self.connection.executemany(
            """
            INSERT OR IGNORE INTO macro_news (source, published_at, title, body, link)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    item.source,
                    item.published_at.isoformat(),
                    item.title,
                    item.body,
                    item.link,
                )
                for item in items
            ],
        )
        return max(0, int(cursor.rowcount))

    def latest_macro_news(self, limit: int = 100) -> list[MacroNewsItem]:
        rows = self.connection.execute(
            """
            SELECT source, published_at, title, body, link
            FROM macro_news
            ORDER BY published_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            MacroNewsItem(
                source=row["source"],
                published_at=datetime.fromisoformat(row["published_at"]),
                title=row["title"],
                body=row["body"],
                link=row["link"],
            )
            for row in rows
        ]

    def upsert_macro_indicator(
        self,
        indicator_key: str,
        value: float,
        period: str,
        source: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO macro_indicators (
                indicator_key, value, period, source, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(indicator_key) DO UPDATE SET
                value = excluded.value,
                period = excluded.period,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (
                indicator_key,
                value,
                period,
                source,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )

    def macro_indicators(self) -> dict[str, float]:
        rows = self.connection.execute(
            "SELECT indicator_key, value FROM macro_indicators"
        ).fetchall()
        return {str(row["indicator_key"]): float(row["value"]) for row in rows}

    def latest_news(self, symbol: str) -> NewsItem | None:
        items = self.recent_news(symbol, limit=1)
        return items[0] if items else None

    def recent_news(self, symbol: str, limit: int = 8) -> list[NewsItem]:
        rows = self.connection.execute(
            """
            SELECT symbol, published_at, source, title, body, disclosure_index, source_url
            FROM news_items
            WHERE symbol = ?
            ORDER BY published_at DESC, id DESC
            LIMIT ?
            """,
            (symbol.upper(), limit),
        ).fetchall()
        return [NewsItem(
            symbol=row["symbol"],
            published_at=datetime.fromisoformat(row["published_at"]),
            source=row["source"],
            title=row["title"],
            body=row["body"],
            disclosure_index=(
                int(row["disclosure_index"])
                if row["disclosure_index"] is not None
                else None
            ),
            source_url=str(row["source_url"] or ""),
        ) for row in rows]


