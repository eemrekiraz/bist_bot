from __future__ import annotations

import sqlite3
import unittest
from datetime import date

from bist_ai_radar.db import SCHEMA
from bist_ai_radar.models import PriceBar
from bist_ai_radar.repositories import MarketRepository


def _bar(day: date, raw: bool, source: str = "") -> PriceBar:
    return PriceBar(
        symbol="AAA",
        day=day,
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=1_000,
        raw_open=100.0 if raw else None,
        raw_high=102.0 if raw else None,
        raw_low=99.0 if raw else None,
        raw_close=101.0 if raw else None,
        source=source,
    )


class PriceRefreshTests(unittest.TestCase):
    def test_refresh_removes_overlapping_legacy_rows_without_raw_prices(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        self.addCleanup(connection.close)
        repository = MarketRepository(connection)
        repository.upsert_price_bars(
            [
                _bar(date(2026, 1, 1), False),
                _bar(date(2026, 1, 2), False),
                _bar(date(2026, 1, 3), False),
                _bar(date(2025, 12, 31), False),
            ]
        )

        repository.upsert_refreshed_price_bars(
            [
                _bar(date(2026, 1, 1), True, "YAHOO"),
                _bar(date(2026, 1, 3), True, "YAHOO"),
            ]
        )

        rows = connection.execute(
            "SELECT day, raw_close FROM price_bars WHERE symbol = 'AAA' ORDER BY day"
        ).fetchall()
        self.assertEqual([row["day"] for row in rows], ["2025-12-31", "2026-01-01", "2026-01-03"])
        self.assertEqual([row["raw_close"] for row in rows[1:]], [101.0, 101.0])


if __name__ == "__main__":
    unittest.main()
