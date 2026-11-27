from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from typing import Any

from bist_ai_radar.adapters.kap_financials import KapFinancialFeed
from bist_ai_radar.engines import FundamentalEngine
from bist_ai_radar.models import FinancialSnapshot, PriceBar


class FakeFinancialClient:
    def get_json(self, url: str) -> Any:
        return [{"permaLink": "1-test-company"}]

    def get_text(self, url: str) -> str:
        return """
        <table>
          <tr><th>FİNANSAL DURUM TABLOSU</th><th>2024/12</th><th>2025/12</th></tr>
          <tr><td>Sunum Para Birimi</td><td>1000TL</td><td>1000TL</td></tr>
          <tr><td>Dönen Varlıklar</td><td>800</td><td>1200</td></tr>
          <tr><td>Toplam Varlıklar</td><td>2000</td><td>2500</td></tr>
          <tr><td>Kısa Vadeli Yükümlülükler</td><td>500</td><td>600</td></tr>
          <tr><td>Toplam Yükümlülükler</td><td>900</td><td>1000</td></tr>
          <tr><td>Ana Ortaklığa Ait Özkaynaklar</td><td>1100</td><td>1500</td></tr>
          <tr><td>Ödenmiş Sermaye</td><td>100</td><td>100</td></tr>
        </table>
        <table>
          <tr><th>KAR VEYA ZARAR</th><th>2024/12</th><th>2025/12</th></tr>
          <tr><td>Sunum Para Birimi</td><td>1000TL</td><td>1000TL</td></tr>
          <tr><td>Hasılat</td><td>1500</td><td>2100</td></tr>
          <tr><td>Brüt Kâr (Zarar)</td><td>500</td><td>800</td></tr>
          <tr><td>Esas Faaliyet Kârı (Zararı)</td><td>300</td><td>500</td></tr>
          <tr><td>Net Dönem Kârı (Zararı)</td><td>200</td><td>350</td></tr>
        </table>
        """


class FailingHistoryClient:
    def get_json(self, url: str) -> Any:
        return [{"mkkMemberOid": "member-1", "permaLink": "1-test-company"}]

    def get_session_text(self, start_url: str, url: str) -> str:
        raise RuntimeError("KAP bağlantısı kapattı")


class AmbiguousFinancialClient:
    def get_json(self, url: str) -> Any:
        return [
            {
                "mkkMemberOid": "pension-member",
                "permaLink": "111-garanti-emeklilik",
            },
            {
                "mkkMemberOid": "bank-member",
                "permaLink": "2422-turkiye-garanti-bankasi-a-s",
            },
        ]

    def get_text(self, url: str) -> str:
        return "<table></table>"


def bars(symbol: str, start: float, daily_change: float) -> list[PriceBar]:
    return [
        PriceBar(
            symbol=symbol,
            day=date(2026, 1, 1) + timedelta(days=index),
            open=start + index * daily_change,
            high=start + index * daily_change + 1,
            low=start + index * daily_change - 1,
            close=start + index * daily_change,
            volume=1_000_000,
        )
        for index in range(60)
    ]


class FundamentalTests(unittest.TestCase):
    def test_scores_cash_conversion_and_free_cash_flow(self) -> None:
        snapshots = [
            FinancialSnapshot(
                "TEST", "2024/12", 1, revenue=100, operating_profit=12,
                net_income=10, equity=50, paid_capital=10,
                total_liabilities=30, current_assets=40, current_liabilities=20,
                operating_cash_flow=12, capital_expenditures=4,
            ),
            FinancialSnapshot(
                "TEST", "2025/12", 1, revenue=120, operating_profit=18,
                net_income=15, equity=60, paid_capital=10,
                total_liabilities=28, current_assets=45, current_liabilities=18,
                operating_cash_flow=20, capital_expenditures=5,
            ),
        ]

        analysis = FundamentalEngine().analyze(snapshots, current_price=20)

        self.assertIsNotNone(analysis)
        assert analysis is not None
        self.assertAlmostEqual(analysis.cash_conversion or 0, 20 / 15)
        self.assertAlmostEqual(analysis.free_cash_flow_margin or 0, 15 / 120)

    def test_parses_and_scores_financial_statements(self) -> None:
        snapshots = KapFinancialFeed(client=FakeFinancialClient()).read_snapshots("TEST")

        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[-1].revenue, 2_100_000)
        analysis = FundamentalEngine().analyze(snapshots, current_price=20)
        self.assertIsNotNone(analysis)
        self.assertGreater(analysis.score, 0.60)
        self.assertAlmostEqual(analysis.revenue_growth, 0.40)


    def test_parses_versioned_disclosure_financials(self) -> None:
        html = """
        <table class="financial-header-table">
          <tr><td>Sunum Para Birimi</td><td>1.000 TL</td></tr>
        </table>
        <table>
          <tr><td>ifrs-full_Assets|</td>
              <td><div class="monetary-field-default" title="120"></div></td>
              <td><div class="monetary-field-default" title="100"></div></td></tr>
          <tr><td>ifrs-full_Revenue|</td>
              <td><div class="monetary-field-default" title="80"></div></td>
              <td><div class="monetary-field-default" title="60"></div></td></tr>
        </table>
        """

        snapshots = KapFinancialFeed()._parse_disclosure_html(
            "TEST",
            html,
            2024,
            datetime(2025, 3, 1, 10, 0),
            12345,
        )

        self.assertEqual([item.period for item in snapshots], ["2024/12", "2023/12"])
        self.assertEqual(snapshots[0].total_assets, 120_000)
        self.assertEqual(snapshots[0].revenue, 80_000)
        self.assertEqual(snapshots[0].disclosure_index, 12345)

    def test_preserves_quarter_in_versioned_financial_period(self) -> None:
        html = """
        <table><tr><td>ifrs-full_Revenue|</td>
        <td><div class="monetary-field-default" title="80"></div></td></tr></table>
        """

        snapshots = KapFinancialFeed()._parse_disclosure_html(
            "TEST",
            html,
            2025,
            datetime(2025, 5, 1, 10, 0),
            12346,
            report_period=1,
        )

        self.assertEqual(snapshots[0].period, "2025/03")

    def test_finds_only_financial_report_records(self) -> None:
        html = (
            r'{\"disclosureBasic\":{\"publishDate\":\"01.03.2025 10:00:00\",'
            r'\"disclosureIndex\":123,\"stockCode\":\"TEST\",'
            r'\"title\":\"Finansal Rapor\",\"year\":2024,\"period\":4}}'
            r'{\"disclosureBasic\":{\"publishDate\":\"01.03.2025 10:01:00\",'
            r'\"disclosureIndex\":124,\"stockCode\":\"TEST\",'
            r'\"title\":\"Faaliyet Raporu\",\"year\":2024,\"period\":4}}'
        )

        records = KapFinancialFeed()._financial_report_records(html)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["disclosure_index"], 123)
        self.assertEqual(records[0]["year"], 2024)

    def test_history_raises_when_all_kap_queries_fail(self) -> None:
        feed = KapFinancialFeed(client=FailingHistoryClient(), request_delay_seconds=0)

        with self.assertRaisesRegex(RuntimeError, "yanit vermedi"):
            feed.read_annual_history("TEST", 3)

    def test_prefers_exact_universe_permalink_for_ambiguous_symbols(self) -> None:
        feed = KapFinancialFeed(client=AmbiguousFinancialClient(), request_delay_seconds=0)

        company = feed._company("GARAN", "2422-turkiye-garanti-bankasi-a-s")

        self.assertIsNotNone(company)
        assert company is not None
        self.assertEqual(company["mkkMemberOid"], "bank-member")

    def test_rejects_ambiguous_fallback_when_known_permalink_is_stale(self) -> None:
        feed = KapFinancialFeed(client=AmbiguousFinancialClient(), request_delay_seconds=0)

        self.assertIsNone(feed._company("GARAN", "old-garanti-link"))


if __name__ == "__main__":
    unittest.main()
