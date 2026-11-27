from __future__ import annotations

import unittest
from datetime import date, timedelta

from bist_ai_radar.data_quality import inspect_price_quality
from bist_ai_radar.models import PriceBar


class DataQualityTests(unittest.TestCase):

    def test_keeps_trade_and_adjusted_prices_separate(self) -> None:
        bar = PriceBar(
            symbol="TEST",
            day=date(2025, 1, 1),
            open=90,
            high=100,
            low=80,
            close=95,
            volume=1000,
            raw_open=100,
            raw_high=110,
            raw_low=90,
            raw_close=105,
        )

        self.assertEqual(bar.close, 95)
        self.assertEqual(bar.trade_close, 105)

    def test_flags_extreme_unexplained_move(self) -> None:
        bars = [
            PriceBar(
                symbol="TEST",
                day=date(2025, 1, 1) + timedelta(days=index),
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1000,
                raw_open=price,
                raw_high=price,
                raw_low=price,
                raw_close=price,
            )
            for index, price in enumerate((100.0, 150.0))
        ]

        report = inspect_price_quality(bars)

        self.assertFalse(report.passed)
        self.assertEqual(len(report.extreme_moves), 1)

    def test_flags_stale_price_series_when_threshold_given(self) -> None:
        bars = [
            PriceBar(
                symbol="TEST",
                day=date(2026, 1, 1),
                open=10,
                high=11,
                low=9,
                close=10,
                volume=1000,
                raw_open=10,
                raw_high=11,
                raw_low=9,
                raw_close=10,
            )
        ]

        report = inspect_price_quality(
            bars,
            as_of=date(2026, 1, 15),
            max_age_days=7,
        )

        self.assertTrue(report.stale)
        self.assertFalse(report.passed)
        self.assertIn("fiyat verisi", report.to_text())


if __name__ == "__main__":
    unittest.main()
