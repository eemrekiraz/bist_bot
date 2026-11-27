from __future__ import annotations

import re
import time
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from urllib.parse import quote, urlencode

from bs4 import BeautifulSoup

from .http import HttpClient
from ..models import FinancialSnapshot


class KapFinancialFeed:
    FIELD_ALIASES = {
        "donen varliklar": "current_assets",
        "toplam varliklar": "total_assets",
        "kisa vadeli yukumlulukler": "current_liabilities",
        "toplam yukumlulukler": "total_liabilities",
        "ana ortakliga ait ozkaynaklar": "equity",
        "toplam ozkaynaklar": "equity",
        "odenmis sermaye": "paid_capital",
        "hasilat": "revenue",
        "brut kar zarar": "gross_profit",
        "esas faaliyet kari zarari": "operating_profit",
        "net donem kari zarari": "net_income",
        "donem kari zararinin dagilimi ana ortaklik paylari": "net_income",
        "isletme faaliyetlerinden nakit akislari": "operating_cash_flow",
        "maddi ve maddi olmayan duran varlik alımlarindan kaynaklanan nakit cikislari": "capital_expenditures",
        "nakit ve nakit benzerleri": "cash_and_equivalents",
        "odenen temettuler": "dividends_paid",
    }
    TAXONOMY_ALIASES = {
        "current_assets": ("ifrs-full_CurrentAssets|",),
        "total_assets": ("ifrs-full_Assets|",),
        "current_liabilities": ("ifrs-full_CurrentLiabilities|",),
        "total_liabilities": ("ifrs-full_Liabilities|",),
        "equity": (
            "ifrs-full_EquityAttributableToOwnersOfParent|",
            "ifrs-full_Equity|",
        ),
        "paid_capital": ("ifrs-full_IssuedCapital|",),
        "revenue": (
            "ifrs-full_Revenue|",
            "kap-fr_RevenueFromFinanceSectorOperations|",
        ),
        "gross_profit": (
            "ifrs-full_GrossProfit|",
            "kap-fr_GrossProfitLossFromCommercialOperations|",
        ),
        "operating_profit": (
            "ifrs-full_ProfitLossFromOperatingActivities|",
        ),
        "net_income": (
            "ifrs-full_ProfitLossAttributableToOwnersOfParent|",
            "ifrs-full_ProfitLoss|",
        ),
        "operating_cash_flow": (
            "ifrs-full_CashFlowsFromUsedInOperatingActivities|",
        ),
        "capital_expenditures": (
            "ifrs-full_PurchaseOfPropertyPlantAndEquipment|",
            "ifrs-full_PurchaseOfIntangibleAssets|",
        ),
        "cash_and_equivalents": (
            "ifrs-full_CashAndCashEquivalents|",
        ),
        "dividends_paid": (
            "ifrs-full_DividendsPaid|",
        ),
    }

    def __init__(
        self,
        base_url: str = "https://www.kap.org.tr",
        client: HttpClient | None = None,
        request_delay_seconds: float = 0.6,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or HttpClient()
        self.request_delay_seconds = request_delay_seconds

    def read_snapshots(
        self,
        symbol: str,
        company_permalink: str = "",
    ) -> list[FinancialSnapshot]:
        normalized_symbol = symbol.upper()
        company = self._company(normalized_symbol, company_permalink)
        if company is None:
            return []
        html = self.client.get_text(
            f"{self.base_url}/tr/sirket-finansal-bilgileri/{company['permaLink']}"
        )
        return self._parse_html(normalized_symbol, html)

    def read_annual_history(
        self,
        symbol: str,
        years: int = 6,
        company_permalink: str = "",
    ) -> list[FinancialSnapshot]:
        return self._read_history(symbol, years, (4,), company_permalink)

    def read_quarterly_history(
        self,
        symbol: str,
        years: int = 3,
        company_permalink: str = "",
    ) -> list[FinancialSnapshot]:
        return self._read_history(
            symbol,
            years,
            (1, 2, 3, 4),
            company_permalink,
        )

    def _read_history(
        self,
        symbol: str,
        years: int,
        report_periods: tuple[int, ...],
        company_permalink: str = "",
    ) -> list[FinancialSnapshot]:
        normalized_symbol = symbol.upper()
        company = self._company(normalized_symbol, company_permalink)
        if company is None or not str(company.get("mkkMemberOid", "")).strip():
            return []
        time.sleep(self.request_delay_seconds)
        latest_complete_year = (
            date.today().year
            if any(period < 4 for period in report_periods)
            else date.today().year - 1
        )
        target_years = range(
            latest_complete_year,
            latest_complete_year - years,
            -1,
        )
        snapshots: list[FinancialSnapshot] = []
        seen_disclosures: set[int] = set()
        failed_queries: list[str] = []
        successful_queries = 0
        for year in target_years:
            for report_period in report_periods:
                query = urlencode(
                    {
                        "srcbar": "Y",
                        "cmp": "Y",
                        "cat": "2",
                        "m": company["mkkMemberOid"],
                        "yr": year,
                        "pr": report_period,
                    }
                )
                try:
                    result_url = f"{self.base_url}/tr/bildirim-sorgu-sonuc?{query}"
                    session_reader = getattr(self.client, "get_session_text", None)
                    result_html = (
                        session_reader(f"{self.base_url}/tr", result_url)
                        if session_reader
                        else self.client.get_text(result_url)
                    )
                except RuntimeError:
                    failed_queries.append(f"{year}/{report_period}")
                    time.sleep(self.request_delay_seconds)
                    continue
                successful_queries += 1
                time.sleep(self.request_delay_seconds)
                record = next(
                    (
                        item
                        for item in self._financial_report_records(result_html)
                        if item["year"] == year and item["period"] == report_period
                    ),
                    None,
                )
                if not record or record["disclosure_index"] in seen_disclosures:
                    continue
                seen_disclosures.add(record["disclosure_index"])
                try:
                    detail_html = self.client.get_text(
                        f"{self.base_url}/tr/Bildirim/{record['disclosure_index']}"
                    )
                except RuntimeError:
                    time.sleep(self.request_delay_seconds)
                    continue
                time.sleep(self.request_delay_seconds)
                snapshots.extend(
                    self._parse_disclosure_html(
                        normalized_symbol,
                        detail_html,
                        year,
                        record["published_at"],
                        record["disclosure_index"],
                        int(record["period"]),
                    )
                )
        if failed_queries and successful_queries == 0:
            raise RuntimeError(
                "KAP tarihsel sorgulari yanit vermedi: "
                + ", ".join(failed_queries)
            )
        return snapshots

    def _company(
        self,
        symbol: str,
        company_permalink: str = "",
    ) -> dict[str, str] | None:
        matches = self.client.get_json(
            f"{self.base_url}/tr/api/member/filter/{quote(symbol)}"
        )
        if not isinstance(matches, list):
            return None
        companies = [
            item
            for item in matches
            if isinstance(item, dict)
            and str(item.get("permaLink", "")).strip()
        ]
        normalized_permalink = company_permalink.strip().lower()
        if normalized_permalink:
            return next(
                (
                    item
                    for item in companies
                    if str(item.get("permaLink", "")).strip().lower()
                    == normalized_permalink
                ),
                None,
            )
        return companies[0] if companies else None

    def _parse_html(self, symbol: str, html: str) -> list[FinancialSnapshot]:
        soup = BeautifulSoup(html, "html.parser")
        values_by_period: dict[str, dict[str, float | None]] = {}
        scales_by_period: dict[str, float] = {}
        for table in soup.find_all("table"):
            rows = [
                [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                for row in table.find_all("tr")
            ]
            if not rows or len(rows[0]) < 2:
                continue
            periods = rows[0][1:]
            for period in periods:
                values_by_period.setdefault(period, {})
            for row in rows[1:]:
                if len(row) < 2:
                    continue
                label = self._normalize(row[0])
                if label == "sunum para birimi":
                    for period, value in zip(periods, row[1:]):
                        scales_by_period[period] = self._currency_scale(value)
                    continue
                field_name = self._field_name(label)
                if not field_name:
                    continue
                for period, value in zip(periods, row[1:]):
                    parsed = self._parse_number(value)
                    existing = values_by_period[period].get(field_name)
                    if parsed is not None and (existing is None or field_name != "equity"):
                        values_by_period[period][field_name] = parsed

        rsc_fields = {
            "ifrs-full_Revenue": "revenue",
            "ifrs-full_GrossProfit": "gross_profit",
            "ifrs-full_ProfitLossFromOperatingActivities": "operating_profit",
            "ifrs-full_ProfitLossAttributableToOwnersOfParent": "net_income",
        }
        for taxonomy_key, field_name in rsc_fields.items():
            marker = f'tr\\",\\"{taxonomy_key}\\"'
            start = html.find(marker)
            if start < 0:
                continue
            end = html.find("\\n", start)
            segment = html[start : end if end >= 0 else start + 8000]
            matches = re.findall(
                r'gelir_(\d{4}/\d{2})_\d+.*?children\\":\\"(-?[\d.]+)',
                segment,
            )
            for period, value in matches:
                values_by_period.setdefault(period, {})[field_name] = self._parse_number(value)

        snapshots: list[FinancialSnapshot] = []
        for period, values in values_by_period.items():
            scale = scales_by_period.get(period, 1.0)
            scaled = {
                field: value * scale if value is not None else None
                for field, value in values.items()
            }
            if scaled:
                snapshots.append(
                    FinancialSnapshot(
                        symbol=symbol,
                        period=period,
                        currency_scale=scale,
                        **scaled,
                    )
                )
        return sorted(snapshots, key=lambda item: self._period_key(item.period))

    def _financial_report_records(self, html: str) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        blocks = re.findall(
            r'\{\\"disclosureBasic\\":\{(.*?)\}\}',
            html,
            re.DOTALL,
        )
        for block in blocks:
            title = self._escaped_value(block, "title")
            if title != "Finansal Rapor":
                continue
            published = self._escaped_value(block, "publishDate")
            index_match = re.search(r'disclosureIndex\\":(\d+)', block)
            year_match = re.search(r'year\\":(\d+)', block)
            period_match = re.search(r'period\\":(\d+)', block)
            if not published or not index_match or not year_match or not period_match:
                continue
            records.append(
                {
                    "published_at": datetime.strptime(
                        published,
                        "%d.%m.%Y %H:%M:%S",
                    ),
                    "disclosure_index": int(index_match.group(1)),
                    "year": int(year_match.group(1)),
                    "period": int(period_match.group(1)),
                }
            )
        return records

    def _escaped_value(self, block: str, key: str) -> str:
        match = re.search(rf'{re.escape(key)}\\":\\"([^\\"]*)\\"', block)
        return match.group(1) if match else ""

    def _parse_disclosure_html(
        self,
        symbol: str,
        html: str,
        year: int,
        published_at: datetime,
        disclosure_index: int,
        report_period: int = 4,
    ) -> list[FinancialSnapshot]:
        soup = BeautifulSoup(html, "html.parser")
        scale = 1.0
        for table in soup.select("table.financial-header-table"):
            text = table.get_text(" ", strip=True)
            if "Sunum Para Birimi" in text:
                match = re.search(r"Sunum Para Birimi\s+([\d.]+)", text)
                if match:
                    scale = self._currency_scale(match.group(1))
                    break
        values = ({}, {})
        for field_name, aliases in self.TAXONOMY_ALIASES.items():
            row_values: list[float | None] = []
            for row in soup.find_all("tr"):
                row_text = row.get_text(" ", strip=True)
                if not any(row_text.startswith(alias) for alias in aliases):
                    continue
                row_values = [
                    self._parse_number(node.get("title", ""))
                    for node in row.select(".monetary-field-default")
                ]
                if any(value is not None for value in row_values):
                    break
            for position in range(min(2, len(row_values))):
                if row_values[position] is not None:
                    values[position][field_name] = row_values[position] * scale
        snapshots: list[FinancialSnapshot] = []
        month = {1: 3, 2: 6, 3: 9, 4: 12}.get(report_period, 12)
        for position, period_year in enumerate((year, year - 1)):
            if not values[position]:
                continue
            snapshots.append(
                FinancialSnapshot(
                    symbol=symbol,
                    period=f"{period_year}/{month:02d}",
                    currency_scale=scale,
                    published_at=published_at,
                    disclosure_index=disclosure_index,
                    source="KAP_DISCLOSURE",
                    **values[position],
                )
            )
        return snapshots

    def _normalize(self, value: str) -> str:
        translated = value.casefold().translate(str.maketrans({"ı": "i", "ş": "s", "ğ": "g"}))
        plain = "".join(
            character
            for character in unicodedata.normalize("NFKD", translated)
            if not unicodedata.combining(character)
        )
        return re.sub(r"[^a-z0-9 ]+", " ", plain).strip().replace("  ", " ")

    def _field_name(self, label: str) -> str | None:
        exact = self.FIELD_ALIASES.get(label)
        if exact:
            return exact
        compact_label = label.replace(" ", "")
        best_alias = max(
            self.FIELD_ALIASES,
            key=lambda alias: SequenceMatcher(
                None,
                compact_label,
                alias.replace(" ", ""),
            ).ratio(),
        )
        similarity = SequenceMatcher(
            None,
            compact_label,
            best_alias.replace(" ", ""),
        ).ratio()
        return self.FIELD_ALIASES[best_alias] if similarity >= 0.82 else None

    def _currency_scale(self, value: str) -> float:
        digits = re.match(r"\s*(\d+)", value.replace(".", ""))
        return float(digits.group(1)) if digits else 1.0

    def _parse_number(self, value: str) -> float | None:
        cleaned = value.strip().replace(".", "").replace(",", ".")
        if not cleaned or cleaned in {"-", "—"}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _period_key(self, period: str) -> tuple[int, int]:
        match = re.match(r"(\d{4})/(\d{2})", period)
        return (int(match.group(1)), int(match.group(2))) if match else (0, 0)
