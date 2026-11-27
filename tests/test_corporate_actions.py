from __future__ import annotations

import unittest
from datetime import date, timedelta

from bist_ai_radar.corporate_actions import (
    assess_corporate_actions,
    corporate_action_history_verified,
)
from bist_ai_radar.models import PriceBar


def _bar(index: int, adjusted: float, raw: float) -> PriceBar:
    return PriceBar(
        "TEST",
        date(2026, 7, 1) + timedelta(days=index),
        adjusted,
        adjusted,
        adjusted,
        adjusted,
        1_000,
        raw,
        raw,
        raw,
        raw,
    )


class CorporateActionTests(unittest.TestCase):
    def test_detects_recent_adjustment_factor_change(self) -> None:
        check = assess_corporate_actions([
            _bar(0, 100, 100),
            _bar(1, 102, 51),
        ])

        self.assertTrue(check.detected)
        self.assertTrue(check.recent)

    def test_leaves_unadjusted_prices_clear(self) -> None:
        check = assess_corporate_actions([
            _bar(0, 100, 100),
            _bar(1, 102, 102),
        ])

        self.assertFalse(check.detected)

    def test_rejects_inconsistent_adjustment_jump(self) -> None:
        bars = [_bar(0, 100, 100), _bar(1, 140, 70)]

        self.assertFalse(corporate_action_history_verified(bars))

    def test_accepts_split_when_adjusted_series_is_continuous(self) -> None:
        bars = [_bar(0, 100, 100), _bar(1, 102, 51)]

        self.assertTrue(corporate_action_history_verified(bars))


if __name__ == "__main__":
    unittest.main()
