from __future__ import annotations

import sqlite3
import unittest

from bist_ai_radar.db import SCHEMA
from bist_ai_radar.source_health import (
    format_source_health,
    record_source_failure,
    record_source_success,
    source_statuses,
)


class SourceHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.addCleanup(self.connection.close)

    def test_marks_repeated_source_failure_as_critical(self) -> None:
        for _ in range(3):
            record_source_failure(self.connection, "KAP_NEWS", "source down")

        kap = next(item for item in source_statuses(self.connection) if item.source == "KAP_NEWS")

        self.assertEqual(kap.status, "KRITIK")
        self.assertEqual(kap.consecutive_failures, 3)

    def test_success_resets_source_failure_count(self) -> None:
        record_source_failure(self.connection, "YAHOO", "timeout")
        record_source_success(self.connection, "YAHOO")

        yahoo = next(item for item in source_statuses(self.connection) if item.source == "YAHOO")

        self.assertEqual(yahoo.status, "HAZIR")
        self.assertEqual(yahoo.consecutive_failures, 0)

    def test_formats_latest_source_error_details(self) -> None:
        record_source_success(self.connection, "YAHOO")
        record_source_failure(self.connection, "KAP_NEWS", "temporary source down")

        text = format_source_health(source_statuses(self.connection))

        self.assertIn("Yahoo fiyat: HAZIR", text)
        self.assertIn("KAP bildirim: UYARI", text)
        self.assertIn("temporary source down", text)


if __name__ == "__main__":
    unittest.main()
