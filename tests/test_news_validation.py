from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from bist_ai_radar.models import MacroNewsItem
from bist_ai_radar.news_validation import (
    corroborating_source_count,
    critical_news_is_confirmed,
    source_quality_weight,
    validate_macro_news_items,
)


def _item(
    source: str,
    title: str,
    published_at: datetime,
    link: str,
) -> MacroNewsItem:
    return MacroNewsItem(source, published_at, title, title, link)


class NewsValidationTests(unittest.TestCase):
    def test_rejects_stale_future_invalid_and_same_source_duplicates(self) -> None:
        now = datetime(2026, 7, 20, 12, 0)
        current = _item("FED", "Federal Reserve holds rates", now, "https://fed/1")
        duplicate = _item(
            "FED",
            "Federal Reserve holds rates again",
            now - timedelta(minutes=5),
            "https://fed/1",
        )
        stale = _item("ECB", "Old decision", now - timedelta(days=30), "https://ecb/1")
        future = _item("BOE", "Future decision", now + timedelta(hours=8), "https://boe/1")
        invalid = _item("BEA", "", now, "")

        result = validate_macro_news_items(
            [current, duplicate, stale, future, invalid],
            now=now,
        )

        self.assertEqual(result.accepted, (current,))
        self.assertEqual(result.rejected_duplicate, 1)
        self.assertEqual(result.rejected_stale, 1)
        self.assertEqual(result.rejected_future, 1)
        self.assertEqual(result.rejected_invalid, 1)

    def test_requires_cross_source_confirmation_for_gdelt_critical_news(self) -> None:
        now = datetime(2026, 7, 20, 12, 0)
        first = _item(
            "GDELT:source-a.com",
            "Oil supply disruption intensifies in region",
            now,
            "https://source-a/1",
        )
        second = _item(
            "GDELT:source-b.com",
            "Regional oil supply disruption intensifies",
            now + timedelta(hours=1),
            "https://source-b/1",
        )

        self.assertFalse(critical_news_is_confirmed(first, [first]))
        self.assertEqual(corroborating_source_count(first, [first, second]), 2)
        self.assertTrue(critical_news_is_confirmed(first, [first, second]))
        self.assertGreater(
            source_quality_weight(first, [first, second]),
            source_quality_weight(first, [first]),
        )

    def test_official_high_trust_news_is_confirmed_directly(self) -> None:
        item = _item(
            "TCMB_PPK",
            "Para politikasi kurulu faiz karari",
            datetime(2026, 7, 20),
            "https://tcmb/1",
        )

        self.assertTrue(critical_news_is_confirmed(item, [item]))


if __name__ == "__main__":
    unittest.main()
