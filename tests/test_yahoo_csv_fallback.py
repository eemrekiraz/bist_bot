from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from bist_ai_radar.adapters.yahoo_finance import YahooFinanceFeed


class FailingClient:
    def get_json(self, url: str):
        raise RuntimeError("network unavailable")


class YahooCsvFallbackTests(unittest.TestCase):
    def test_uses_local_csv_when_both_yahoo_endpoints_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "TEST.csv"
            path.write_text(
                "day,open,high,low,close,volume\n"
                "2026-07-15,10,11,9,10.5,1000\n",
                encoding="utf-8",
            )
            feed = YahooFinanceFeed(
                client=FailingClient(),
                csv_fallback_directory=directory,
            )

            with patch("bist_ai_radar.adapters.yahoo_finance.date", wraps=date) as clock:
                clock.today.return_value = date(2026, 7, 20)
                bars = feed.read_price_bars("TEST", days=10)

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].source, "CSV_FALLBACK")


if __name__ == "__main__":
    unittest.main()
