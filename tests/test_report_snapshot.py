from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from bist_ai_radar.report_snapshot import (
    get_or_build_report_snapshot,
    load_report_snapshot,
    save_report_snapshot,
)


class ReportSnapshotTests(unittest.TestCase):
    def test_returns_fresh_snapshot_without_rebuilding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime.now()
            save_report_snapshot("monthly-opportunities", "hazir", root, now)
            calls = 0

            def builder() -> str:
                nonlocal calls
                calls += 1
                return "yeniden"

            result = get_or_build_report_snapshot(
                "monthly-opportunities",
                builder,
                24 * 60 * 60,
                root,
            )

        self.assertEqual(result, "hazir")
        self.assertEqual(calls, 0)

    def test_rejects_stale_or_corrupt_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime(2026, 7, 20, 8, 0)
            save_report_snapshot(
                "weekly-opportunities",
                "eski",
                root,
                now - timedelta(days=2),
            )
            stale = load_report_snapshot(
                "weekly-opportunities",
                60,
                root,
                now,
            )
            (root / "weekly-opportunities.json").write_text("bozuk", encoding="utf-8")
            corrupt = load_report_snapshot(
                "weekly-opportunities",
                60,
                root,
                now,
            )

        self.assertIsNone(stale)
        self.assertIsNone(corrupt)


if __name__ == "__main__":
    unittest.main()
