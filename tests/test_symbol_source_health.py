from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timedelta

from bist_ai_radar.db import SCHEMA
from bist_ai_radar.symbol_source_health import (
    record_symbol_source_failure,
    record_symbol_source_success,
    symbol_source_attempt_allowed,
    symbol_source_quarantine_count,
)


class SymbolSourceHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.addCleanup(self.connection.close)

    def test_quarantines_404_for_seven_days(self) -> None:
        now = datetime(2026, 7, 20, 10, 0)
        blocked_until = record_symbol_source_failure(
            self.connection,
            "YAHOO",
            "OLD",
            "HTTP 404 while fetching symbol",
            now,
        )

        self.assertEqual(blocked_until, now + timedelta(days=7))
        self.assertFalse(
            symbol_source_attempt_allowed(
                self.connection,
                "YAHOO",
                "OLD",
                now + timedelta(days=1),
            )
        )
        self.assertEqual(symbol_source_quarantine_count(self.connection, "YAHOO", now), 1)

    def test_success_clears_backoff(self) -> None:
        now = datetime(2026, 7, 20, 10, 0)
        record_symbol_source_failure(self.connection, "YAHOO", "TEST", "timeout", now)
        record_symbol_source_success(
            self.connection,
            "YAHOO",
            "TEST",
            now + timedelta(hours=1),
        )

        self.assertTrue(
            symbol_source_attempt_allowed(
                self.connection,
                "YAHOO",
                "TEST",
                now + timedelta(hours=1),
            )
        )


if __name__ == "__main__":
    unittest.main()
