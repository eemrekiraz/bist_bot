from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from bist_ai_radar.adapters.rss_feed import OfficialRssFeed
from bist_ai_radar.engines import MacroNewsEngine
from bist_ai_radar.models import MacroNewsItem, PriceBar


class FakeRssClient:
    def get_text(self, url: str) -> str:
        return """
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Faiz Oranlarına İlişkin Duyuru</title>
            <link href="/duyuru/1"/>
            <updated>1 Tem 2026 14:00:00</updated>
            <summary>Para politikası sıkılaştırılmıştır.</summary>
          </entry>
        </feed>
        """




class MacroNewsTests(unittest.TestCase):
    def test_reads_atom_with_turkish_date(self) -> None:
        items = OfficialRssFeed(client=FakeRssClient()).read(
            "TCMB",
            "https://example.com/feed",
            enrich=False,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].published_at, datetime(2026, 7, 1, 14, 0))

    def test_defense_sector_offsets_geopolitical_risk(self) -> None:
        item = MacroNewsItem(
            source="GDELT:reuters.com",
            published_at=datetime.now(),
            title="Regional war and sanctions intensify",
            body="Conflict risk rises.",
            link="https://reuters.com/example",
        )

        broad = MacroNewsEngine().classify(item)
        defense = MacroNewsEngine().classify(item, "SAVUNMA")

        self.assertGreater(defense.score, broad.score)



if __name__ == "__main__":
    unittest.main()
