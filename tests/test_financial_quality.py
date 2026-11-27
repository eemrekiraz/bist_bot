from __future__ import annotations

import unittest
from datetime import date, datetime

from bist_ai_radar.financial_quality import (
    financial_information_available_day,
    inspect_financial_freshness,
    usable_financial_snapshots,
    valid_financial_publication,
)
from bist_ai_radar.models import FinancialSnapshot


class FinancialQualityTests(unittest.TestCase):
    def test_flags_stale_financial_period(self) -> None:
        snapshots = [
            FinancialSnapshot("TEST", "2024/12", 1.0),
            FinancialSnapshot("TEST", "2025/03", 1.0),
        ]

        report = inspect_financial_freshness(
            snapshots,
            as_of=date(2026, 1, 15),
            max_age_days=240,
        )

        self.assertTrue(report.stale)
        self.assertIn("ESKI", report.to_text())
        self.assertEqual(usable_financial_snapshots(snapshots, date(2026, 1, 15)), [])

    def test_keeps_recent_financial_period(self) -> None:
        snapshots = [FinancialSnapshot("TEST", "2025/12", 1.0)]

        report = inspect_financial_freshness(
            snapshots,
            as_of=date(2026, 2, 15),
            max_age_days=240,
        )

        self.assertFalse(report.stale)
        self.assertEqual(usable_financial_snapshots(snapshots, date(2026, 2, 15)), snapshots)

    def test_financial_disclosure_is_available_from_next_day(self) -> None:
        published = datetime(2026, 3, 2, 18, 30)

        self.assertEqual(financial_information_available_day(published), date(2026, 3, 3))

    def test_rejects_version_without_valid_publication_provenance(self) -> None:
        missing = FinancialSnapshot("TEST", "2025/12", 1.0)
        valid = FinancialSnapshot(
            "TEST",
            "2025/12",
            1.0,
            published_at=datetime(2026, 3, 2, 18, 30),
            disclosure_index=123,
        )

        self.assertFalse(valid_financial_publication(missing))
        self.assertTrue(valid_financial_publication(valid))


if __name__ == "__main__":
    unittest.main()
