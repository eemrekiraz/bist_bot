from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any

from bist_ai_radar.adapters.yahoo_finance import YahooFinanceFeed


class FailingPrimaryClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.urls.append(url)
        if "query1" in url:
            raise RuntimeError("primary unavailable")
        timestamp = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp())
        return {
            "chart": {
                "result": [
                    {
                        "timestamp": [timestamp],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.0],
                                    "high": [102.0],
                                    "low": [99.0],
                                    "close": [101.0],
                                    "volume": [1_000],
                                }
                            ],
                            "adjclose": [{"adjclose": [101.0]}],
                        },
                    }
                ]
            }
        }


class YahooFinanceFeedTests(unittest.TestCase):
    def test_uses_fallback_endpoint_after_primary_failure(self) -> None:
        client = FailingPrimaryClient()
        feed = YahooFinanceFeed(client=client)

        bars = feed.read_price_bars("THYAO", days=30)

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].source, "YAHOO_FALLBACK")
        self.assertIn("query1", client.urls[0])
        self.assertIn("query2", client.urls[1])


if __name__ == "__main__":
    unittest.main()
