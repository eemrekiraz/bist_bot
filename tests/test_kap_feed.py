from __future__ import annotations

import unittest
from datetime import date, datetime
from typing import Any

from bist_ai_radar.adapters.kap_feed import KapJsonFeed


class FakeHttpClient:
    def __init__(self) -> None:
        self.post_body: dict[str, Any] | None = None

    def get_json(self, url: str) -> Any:
        if "/member/filter/" in url:
            return [{"mkkMemberOid": "member-1", "companyCode": "1107"}]
        return [
            {
                "title": "Genel duyuru",
                "summary": "Piyasa duyurusu",
                "publishDate": "05.07.2026 10:00:00",
            }
        ]

    def post_json(self, url: str, body: dict[str, Any]) -> Any:
        self.post_body = body
        return [
            {
                "disclosureBasic": {
                    "stockCode": "THYAO",
                    "title": "Kapasite Artışı",
                    "summary": "Yeni yatırım açıklandı",
                    "publishDate": "02.07.2026 09:32:58",
                }
            }
        ]


class KapJsonFeedTests(unittest.TestCase):
    def test_market_news_uses_details_and_keeps_multi_symbol_links(self) -> None:
        class MarketClient(FakeHttpClient):
            def post_json(self, url: str, body: dict[str, Any]) -> Any:
                self.post_body = body
                return [
                    {"title": "Geçersiz tarih", "publishDate": "?"},
                    {
                        "disclosureIndex": 100,
                        "disclosureBasic": {
                            "stockCode": "ALFA, BETA",
                            "title": "Yatırım",
                            "publishDate": "02.07.2026 09:32:58",
                        },
                    },
                ]

        client = MarketClient()
        feed = KapJsonFeed("https://www.kap.org.tr/tr/api/disclosure/list/light", client=client)
        items = feed.read_market_news(date(2026, 7, 2))

        self.assertEqual({item.symbol for item in items}, {"ALFA", "BETA"})
        self.assertEqual({item.source_url for item in items}, {"https://www.kap.org.tr/tr/Bildirim/100"})
        self.assertIsNone(client.post_body["mkkMemberOid"])
        self.assertEqual(client.post_body["fromDate"], "01.07.2026")

    def test_reads_company_disclosures_with_symbol_filter(self) -> None:
        client = FakeHttpClient()
        feed = KapJsonFeed(
            "https://www.kap.org.tr/tr/api/disclosure/list/light",
            client=client,
        )

        items = feed.read_news("thyao")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].symbol, "THYAO")
        self.assertEqual(items[0].title, "Kapasite Artışı")
        self.assertEqual(items[0].published_at, datetime(2026, 7, 2, 9, 32, 58))
        self.assertEqual(client.post_body["mkkMemberOid"], "member-1")

    def test_reads_light_feed_as_general_news(self) -> None:
        feed = KapJsonFeed(
            "https://www.kap.org.tr/tr/api/disclosure/list/light",
            client=FakeHttpClient(),
        )

        items = feed.read_news()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].symbol, "GENEL")

    def test_uses_disclosure_level_explanation_when_basic_record_is_short(self) -> None:
        feed = KapJsonFeed("https://www.kap.org.tr/tr/api/disclosure/list/light")
        item = feed._to_news_item(
            {
                "additionalExplanation": "Yatirim tutari ve kapasite ayrintilari aciklandi.",
                "disclosureBasic": {
                    "stockCode": "TEST",
                    "title": "Yatirim",
                    "publishDate": "02.07.2026 09:32:58",
                },
            }
        )

        self.assertIsNotNone(item)
        self.assertIn("kapasite", item.body)

    def test_keeps_disclosure_link_metadata(self) -> None:
        feed = KapJsonFeed("https://www.kap.org.tr/tr/api/disclosure/list/light")
        item = feed._to_news_item(
            {
                "disclosureBasic": {
                    "stockCode": "TEST",
                    "publishDate": "01.03.2025 10:00:00",
                    "title": "Test bildirimi",
                    "disclosureIndex": 12345,
                }
            }
        )

        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.disclosure_index, 12345)
        self.assertEqual(item.source_url, "https://www.kap.org.tr/tr/Bildirim/12345")


if __name__ == "__main__":
    unittest.main()
