from __future__ import annotations

import unittest
from datetime import date, datetime

from bist_ai_radar.market_calendar import (
    is_first_market_session_of_week,
    is_last_market_session_of_week,
    is_market_open_at,
    market_session,
)


class MarketCalendarSessionTests(unittest.TestCase):
    def test_recognizes_official_2026_closed_and_half_days(self) -> None:
        self.assertEqual(market_session(date(2026, 3, 20)).status, "CLOSED")
        self.assertEqual(market_session(date(2026, 5, 26)).status, "HALF")
        self.assertEqual(market_session(date(2026, 10, 29)).status, "CLOSED")

    def test_half_day_closes_at_thirteen(self) -> None:
        self.assertTrue(is_market_open_at(datetime(2026, 5, 26, 12, 59)))
        self.assertFalse(is_market_open_at(datetime(2026, 5, 26, 13, 1)))

    def test_moves_week_boundaries_around_holidays(self) -> None:
        self.assertTrue(is_first_market_session_of_week(date(2026, 3, 23)))
        self.assertTrue(is_last_market_session_of_week(date(2026, 5, 26)))
        self.assertFalse(is_last_market_session_of_week(date(2026, 5, 25)))


if __name__ == "__main__":
    unittest.main()
