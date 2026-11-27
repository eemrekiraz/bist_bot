from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta
from math import exp, sqrt
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from bist_ai_radar.db import connect, init_db
from bist_ai_radar.models import CompanyProfile, FinancialSnapshot, NewsItem, PriceBar
from bist_ai_radar.public_research import (
    ISTANBUL, public_report, public_sector_directory, publish_public_snapshot,
    sector_report_pages, sector_key, _sector_names, render_public_report, price_scenarios,
)
from bist_ai_radar.repositories import MarketRepository
from bist_ai_radar.public_worker_export import export_worker_reports


class PublicResearchTests(unittest.TestCase):
    def test_snapshot_covers_sectors_and_omits_company_with_recent_risk(self) -> None:
        now = datetime(2026, 11, 27, 20, tzinfo=ISTANBUL)
        with TemporaryDirectory() as directory, patch.dict(
            os.environ, {"DATABASE_URL": f"sqlite:///{Path(directory) / 'research.sqlite3'}"}
        ):
            init_db()
            with connect() as connection:
                repository = MarketRepository(connection)
                for symbol, sector in (("ALFA", "Enerji"), ("BETA", "Otomotiv"), ("GAMA", "Enerji")):
                    repository.upsert_companies([CompanyProfile(symbol, symbol, "", "", sector)])
                    repository.upsert_price_bars([
                        PriceBar(symbol, now.date() - timedelta(days=offset),
                                 100, 101, 99, 100, 600000, raw_close=100)
                        for offset in range(75, -1, -1)
                    ])
                    repository.upsert_financial_snapshots([
                        FinancialSnapshot(
                            symbol, period, 1, current_assets=180, current_liabilities=70,
                            total_liabilities=95, equity=200, paid_capital=1, revenue=revenue,
                            operating_profit=45, net_income=35, operating_cash_flow=50,
                            capital_expenditures=10,
                        )
                        for period, revenue in (("2024/12", 120), ("2025/12", 170), ("2026/09", 155))
                    ])
                repository.insert_news_items([
                    NewsItem("GAMA", now - timedelta(days=2), "KAP", "Sözleşme iptali", "",
                             1, "https://www.kap.org.tr/tr/Bildirim/1"),
                    NewsItem("GAMA", now - timedelta(days=1), "KAP", "Rutin açıklama", "",
                             2, "https://www.kap.org.tr/tr/Bildirim/2"),
                ])
            with patch("bist_ai_radar.public_research.save_report_snapshot") as save:
                publish_public_snapshot(now)
        raw = save.call_args.args[1]
        snapshot = json.loads(raw)
        self.assertEqual(len(snapshot["companies"]), 3)
        with patch("bist_ai_radar.public_research.load_report_snapshot", return_value=raw):
            portfolio = public_report("portfoy", ["kalite"], now)
            self.assertIn("ALFA", portfolio)
            self.assertIn("BETA", portfolio)
            self.assertNotIn("GAMA", portfolio)
            self.assertIn("Neden:", portfolio)
            sector = public_report("sektor", ["ENERJİ"], now)
            self.assertIn("ALFA", sector)
            self.assertIn("Tarama puanı", sector)
            self.assertNotIn("BETA", sector)
            self.assertIn("Enerji", public_sector_directory())
            self.assertIn("Sanayi", public_sector_directory())
            self.assertIn("https://www.kap.org.tr/tr/Bildirim/1", public_report("haber", ["GAMA"], now))
            later = now + timedelta(days=5)
            self.assertNotIn("ALFA", public_report("portfoy", [], later))
            self.assertIn("bekleniyor", public_report("tara", ["ALFA"], later))

    def test_all_eligible_sector_companies_are_ranked_across_pages(self) -> None:
        now = datetime(2026, 11, 27, 20, tzinfo=ISTANBUL)
        companies = [
            {
                "symbol": f"BNK{index:02d}", "title": f"Örnek banka {index:02d}",
                "sector": "Bankalar", "day": "2026-11-27", "period": "2026/09",
                "eligible": True, "news": [],
                "scores": {profile: index / 100 for profile in ("dengeli", "kalite", "buyume")},
                "reasons": ["Özkaynak kârlılığı güçlü", "Finansal güç skoru olumlu"],
                "risk": "Bilanço ve piyasa koşulları değişebilir.",
            }
            for index in range(25)
        ]
        payload = json.dumps({"updated": now.isoformat(), "companies": companies, "macro": []})
        with patch("bist_ai_radar.public_research.load_report_snapshot", return_value=payload):
            first = public_report("sektor", ["banka"], now)
            second = public_report("sektor", ["banka", "sayfa", "2"], now)
            missing = public_report("sektor", ["hacim"], now)
        self.assertIn("25 aday", first)
        self.assertIn("BNK24", first)
        self.assertIn("Tarama puanı 24,0/100", first)
        self.assertIn("/sektor banka sayfa 2", first)
        self.assertIn("BNK24", first.split("BNK23")[0])
        self.assertIn("Önceki • /sektor banka sayfa 1", second)
        all_pages = sector_report_pages(companies, companies, "banka", "Son tarama")
        for item in companies:
            self.assertEqual("\n".join(all_pages).count(item["symbol"]), 1)
        self.assertTrue(all(len(page) < 4096 for page in all_pages))
        self.assertIn("Sektör adlarını görmek için /komutlar", missing)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "assets"
            count = export_worker_reports(path, json.loads(payload), now)
            index = json.loads((path / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(count, 25)
            self.assertIn("Aşağıdaki isimlere dokunarak", index["help"])
            self.assertEqual(index["sectors"]["finans"]["label"], "Finans")
            self.assertEqual(index["sectorAliases"]["banka"], "finans")
            self.assertEqual(index["priceExpires"], "2026-11-30T18:10:00+03:00")
            entry = index["sectors"]["finans"]
            sector_page = path / "sector" / str(entry["id"]) / f"{entry['pages']}.json"
            archived_page = json.loads(sector_page.read_text(encoding="utf-8"))
            self.assertIn("BNK00", archived_page)

    def test_main_sectors_merge_subsectors_and_allow_short_names_or_numbers(self) -> None:
        companies = [{"sector": value} for value in (
            "BANKALAR", "SIGORTA SIRKETLERI", "FINANSAL KIRALAMA VE FAKTORING SIRKETLERI",
            "BILISIM", "TELEKOMUNIKASYON", "GIDA, ICECEK VE TUTUN", "TARIM VE HAYVANCILIK",
            "METAL ESYA MAKINE ELEKTRIKLI CIHAZLAR VE ULASIM ARACLARI",
        )]
        self.assertEqual(list(_sector_names(companies)), ["finans", "teknoloji", "gida", "sanayi"])
        self.assertEqual(sector_key(companies[-1]["sector"]), "sanayi")
        self.assertEqual(sector_key("TAS VE TOPRAGA DAYALI"), "sanayi")
        self.assertEqual(sector_key("BURO YONETIMI VE SIRKET DESTEK FAALIYETLERI"), "hizmet")
        self.assertEqual(sector_key("Sektör bilgisi yok"), "")
        directory = sector_report_pages(companies, [], "", "Tarama")[0]
        self.assertIn("ANA SEKTÖRLER", directory)
        self.assertNotIn("FAKTORING", directory)
        for query in ("banka", "finans", "1", "Bankalar", "sigorta"):
            self.assertIn("SEKTÖR • Finans", sector_report_pages(companies, [], query, "Tarama")[0])

    def test_company_text_uses_separate_bullets_and_profile_score(self) -> None:
        now = datetime(2026, 11, 27, 20, tzinfo=ISTANBUL)
        company = {
            "symbol": "TEST", "title": "Örnek şirket", "sector": "Bankalar",
            "day": "2026-11-27", "period": "2026/09", "eligible": True, "news": [],
            "scores": {"dengeli": 0.7, "kalite": 0.8, "buyume": 0.9},
            "reasons": ["Güçlü bilanço", "Pozitif nakit akışı"], "risk": "Yüksek oynaklık; Faiz riski",
        }
        snapshot = {"updated": now.isoformat(), "companies": [company], "macro": []}
        report = render_public_report(snapshot, "portfoy", "buyume", now)
        self.assertIn("Tarama puanı 90,0/100", report)
        self.assertIn("Neden:\n• Güçlü bilanço\n• Pozitif nakit akışı", report)
        self.assertIn("Dikkat:\n• Yüksek oynaklık\n• Faiz riski", report)

    def test_price_scenarios_use_adjusted_returns_and_tradable_price(self) -> None:
        bars = [SimpleNamespace(close=100 * exp(0.01 if index % 2 else 0), trade_close=200)
                for index in range(61)]
        result = price_scenarios(bars)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["lower"], 200 * exp(-0.01 * sqrt(252)))
        self.assertEqual(result["base"], 200)
        self.assertAlmostEqual(result["upper"], 200 * exp(0.01 * sqrt(252)))
        self.assertEqual(result["sessions"], 60)
        self.assertEqual(result["horizon"], 252)

    def test_price_scenarios_reject_insufficient_flat_or_extreme_prices(self) -> None:
        for closes in ([100] * 61, [100, 101] * 10, [100, 0] * 31, [100, float("nan")] * 31,
                       [1, 10000] * 31):
            bars = [SimpleNamespace(close=value, trade_close=100) for value in closes]
            self.assertIsNone(price_scenarios(bars))

    def test_price_scenario_text_is_explicitly_not_a_prediction(self) -> None:
        now = datetime(2026, 11, 27, 20, tzinfo=ISTANBUL)
        company = {
            "symbol": "TEST", "title": "Örnek şirket", "sector": "Bankalar",
            "day": "2026-11-27", "period": "2026/09", "eligible": True, "news": [],
            "scores": {"dengeli": 0.7}, "reasons": ["Güçlü bilanço"], "risk": "Piyasa riski",
            "price_scenario": {"price": 100, "lower": 80, "base": 100, "upper": 125, "sessions": 60},
        }
        report = render_public_report({"updated": now.isoformat(), "companies": [company]}, "tara", "TEST", now)
        for expected in ("• Aşağı senaryo: 80,00 TL", "• Yatay senaryo: 100,00 TL",
                         "• Yukarı senaryo: 125,00 TL", "Hedef değer veya eğitilmiş model tahmini değildir"):
            self.assertIn(expected, report)




