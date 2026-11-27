from __future__ import annotations

from dataclasses import dataclass

from ..models import FinancialSnapshot


@dataclass(frozen=True)
class FundamentalAnalysis:
    score: float
    profitability_score: float
    growth_score: float
    strength_score: float
    valuation_score: float
    revenue_growth: float | None
    net_income_growth: float | None
    operating_margin: float | None
    roe: float | None
    debt_to_equity: float | None
    current_ratio: float | None
    price_to_earnings: float | None
    price_to_book: float | None
    cash_conversion: float | None = None
    free_cash_flow_margin: float | None = None

    def reason(self) -> str:
        growth = (
            self.revenue_growth
            if self.revenue_growth is not None
            else self.net_income_growth
        )
        parts = [
            f"Temel %{self.score * 100:.0f}",
            f"Buyume %{(growth or 0) * 100:.0f}",
        ]
        if self.operating_margin is not None:
            parts.append(f"Marj %{self.operating_margin * 100:.1f}")
        if self.debt_to_equity is not None:
            parts.append(f"Borc/Ozsermaye {self.debt_to_equity:.2f}")
        if self.price_to_earnings is not None:
            parts.append(f"F/K {self.price_to_earnings:.1f}")
        if self.free_cash_flow_margin is not None:
            parts.append(f"SNA marji %{self.free_cash_flow_margin * 100:.1f}")
        return " | ".join(parts)

    def to_text(self, symbol: str) -> str:
        return (
            f"SIRKET ANALIZI: {symbol}\n"
            f"Toplam temel skor: %{self.score * 100:.0f}\n"
            f"Karlilik: %{self.profitability_score * 100:.0f}\n"
            f"Buyume: %{self.growth_score * 100:.0f}\n"
            f"Finansal guc: %{self.strength_score * 100:.0f}\n"
            f"Degerleme: %{self.valuation_score * 100:.0f}\n\n"
            f"Ciro buyumesi: {self._percent(self.revenue_growth)}\n"
            f"Faaliyet marji: {self._percent(self.operating_margin)}\n"
            f"ROE: {self._percent(self.roe)}\n"
            f"Nakit/kar donusumu: {self._number(self.cash_conversion)}\n"
            f"Serbest nakit akisi marji: {self._percent(self.free_cash_flow_margin)}\n"
            f"Cari oran: {self._number(self.current_ratio)}\n"
            f"Borc/Ozsermaye: {self._number(self.debt_to_equity)}\n"
            f"Yaklasik F/K: {self._number(self.price_to_earnings)}\n"
            f"Yaklasik PD/DD: {self._number(self.price_to_book)}"
        )

    def _percent(self, value: float | None) -> str:
        return f"%{value * 100:.1f}" if value is not None else "Veri yok"

    def _number(self, value: float | None) -> str:
        return f"{value:.2f}" if value is not None else "Veri yok"


class FundamentalEngine:
    def analyze(
        self,
        snapshots: list[FinancialSnapshot],
        current_price: float,
        sector: str = "",
    ) -> FundamentalAnalysis | None:
        annual = [item for item in snapshots if item.period.endswith("/12")]
        if not annual:
            return None
        latest = snapshots[-1]
        latest_annual = annual[-1]
        previous_annual = annual[-2] if len(annual) >= 2 else None
        if self._is_financial_sector(sector):
            return self._analyze_financial_company(
                latest,
                latest_annual,
                previous_annual,
                current_price,
            )
        if self._is_asset_heavy_sector(sector):
            return self._analyze_asset_heavy_company(
                latest,
                latest_annual,
                previous_annual,
                current_price,
            )

        revenue_growth = self._growth(
            latest_annual.revenue,
            previous_annual.revenue if previous_annual else None,
        )
        net_income_growth = self._growth(
            latest_annual.net_income,
            previous_annual.net_income if previous_annual else None,
        )
        operating_margin = self._ratio(
            latest_annual.operating_profit,
            latest_annual.revenue,
        )
        roe = self._ratio(latest_annual.net_income, latest_annual.equity)
        debt_to_equity = self._ratio(latest.total_liabilities, latest.equity)
        current_ratio = self._ratio(latest.current_assets, latest.current_liabilities)
        cash_conversion = self._ratio(
            latest_annual.operating_cash_flow,
            latest_annual.net_income,
        )
        free_cash_flow_margin = self._ratio(
            latest_annual.free_cash_flow,
            latest_annual.revenue,
        )

        market_cap = (
            current_price * latest.paid_capital
            if latest.paid_capital and current_price > 0
            else None
        )
        price_to_earnings = self._ratio(market_cap, latest_annual.net_income)
        price_to_book = self._ratio(market_cap, latest.equity)

        profitability_score = self._average(
            self._bounded((operating_margin + 0.05) / 0.25)
            if operating_margin is not None
            else None,
            self._bounded(roe / 0.25) if roe is not None else None,
            self._bounded((cash_conversion + 0.20) / 1.40)
            if cash_conversion is not None
            else None,
        )
        growth_score = self._average(
            self._bounded((revenue_growth + 0.10) / 0.40)
            if revenue_growth is not None
            else None,
            self._bounded((net_income_growth + 0.15) / 0.60)
            if net_income_growth is not None
            else None,
        )
        strength_score = self._average(
            self._bounded((current_ratio - 0.60) / 1.40)
            if current_ratio is not None
            else None,
            self._bounded((2.50 - debt_to_equity) / 2.00)
            if debt_to_equity is not None
            else None,
            self._bounded((free_cash_flow_margin + 0.05) / 0.20)
            if free_cash_flow_margin is not None
            else None,
        )
        valuation_score = self._average(
            self._inverse_range(price_to_earnings, 5.0, 30.0),
            self._inverse_range(price_to_book, 0.5, 5.0),
        )
        score = (
            profitability_score * 0.30
            + growth_score * 0.25
            + strength_score * 0.25
            + valuation_score * 0.20
        )
        return FundamentalAnalysis(
            score=score,
            profitability_score=profitability_score,
            growth_score=growth_score,
            strength_score=strength_score,
            valuation_score=valuation_score,
            revenue_growth=revenue_growth,
            net_income_growth=net_income_growth,
            operating_margin=operating_margin,
            roe=roe,
            debt_to_equity=debt_to_equity,
            current_ratio=current_ratio,
            price_to_earnings=price_to_earnings if price_to_earnings and price_to_earnings > 0 else None,
            price_to_book=price_to_book if price_to_book and price_to_book > 0 else None,
            cash_conversion=cash_conversion,
            free_cash_flow_margin=free_cash_flow_margin,
        )

    def _analyze_financial_company(
        self,
        latest: FinancialSnapshot,
        latest_annual: FinancialSnapshot,
        previous_annual: FinancialSnapshot | None,
        current_price: float,
    ) -> FundamentalAnalysis:
        net_income_growth = self._growth(
            latest_annual.net_income,
            previous_annual.net_income if previous_annual else None,
        )
        roe = self._ratio(latest_annual.net_income, latest_annual.equity)
        roa = self._ratio(latest_annual.net_income, latest_annual.total_assets)
        capital_ratio = self._ratio(latest.equity, latest.total_assets)
        debt_to_equity = self._ratio(latest.total_liabilities, latest.equity)
        market_cap = (
            current_price * latest.paid_capital
            if latest.paid_capital and current_price > 0
            else None
        )
        price_to_earnings = self._ratio(market_cap, latest_annual.net_income)
        price_to_book = self._ratio(market_cap, latest.equity)
        profitability_score = self._average(
            self._bounded(roe / 0.25) if roe is not None else None,
            self._bounded(roa / 0.05) if roa is not None else None,
        )
        growth_score = (
            self._bounded((net_income_growth + 0.15) / 0.60)
            if net_income_growth is not None
            else 0.5
        )
        strength_score = (
            self._bounded((capital_ratio - 0.05) / 0.15)
            if capital_ratio is not None
            else 0.5
        )
        valuation_score = self._average(
            self._inverse_range(price_to_earnings, 3.0, 20.0),
            self._inverse_range(price_to_book, 0.4, 3.0),
        )
        score = (
            profitability_score * 0.35
            + growth_score * 0.20
            + strength_score * 0.20
            + valuation_score * 0.25
        )
        return FundamentalAnalysis(
            score=score,
            profitability_score=profitability_score,
            growth_score=growth_score,
            strength_score=strength_score,
            valuation_score=valuation_score,
            revenue_growth=None,
            net_income_growth=net_income_growth,
            operating_margin=None,
            roe=roe,
            debt_to_equity=debt_to_equity,
            current_ratio=None,
            price_to_earnings=price_to_earnings if price_to_earnings and price_to_earnings > 0 else None,
            price_to_book=price_to_book if price_to_book and price_to_book > 0 else None,
        )

    def _is_financial_sector(self, sector: str) -> bool:
        normalized = sector.upper()
        return any(
            keyword in normalized
            for keyword in (
                "BANK",
                "SIGORT",
                "FINANS",
                "FAKTOR",
                "VARLIK YONET",
                "ARACI KURUM",
            )
        )

    def _is_asset_heavy_sector(self, sector: str) -> bool:
        normalized = sector.upper()
        return any(
            keyword in normalized
            for keyword in (
                "GAYRIMENKUL",
                "GYO",
                "HOLDING",
                "YATIRIM ORTAKLIGI",
            )
        )

    def _analyze_asset_heavy_company(
        self,
        latest: FinancialSnapshot,
        latest_annual: FinancialSnapshot,
        previous_annual: FinancialSnapshot | None,
        current_price: float,
    ) -> FundamentalAnalysis:
        revenue_growth = self._growth(
            latest_annual.revenue,
            previous_annual.revenue if previous_annual else None,
        )
        net_income_growth = self._growth(
            latest_annual.net_income,
            previous_annual.net_income if previous_annual else None,
        )
        roe = self._ratio(latest_annual.net_income, latest.equity)
        debt_to_equity = self._ratio(latest.total_liabilities, latest.equity)
        current_ratio = self._ratio(latest.current_assets, latest.current_liabilities)
        market_cap = (
            current_price * latest.paid_capital
            if latest.paid_capital and current_price > 0
            else None
        )
        price_to_earnings = self._ratio(market_cap, latest_annual.net_income)
        price_to_book = self._ratio(market_cap, latest.equity)
        profitability_score = self._average(
            self._bounded(roe / 0.18) if roe is not None else None,
            self._bounded((net_income_growth + 0.10) / 0.50)
            if net_income_growth is not None
            else None,
        )
        growth_score = self._average(
            self._bounded((revenue_growth + 0.10) / 0.35)
            if revenue_growth is not None
            else None,
            self._bounded((net_income_growth + 0.15) / 0.55)
            if net_income_growth is not None
            else None,
        )
        strength_score = self._average(
            self._bounded((current_ratio - 0.40) / 1.60)
            if current_ratio is not None
            else None,
            self._bounded((3.50 - debt_to_equity) / 3.00)
            if debt_to_equity is not None
            else None,
        )
        valuation_score = self._average(
            self._inverse_range(price_to_book, 0.25, 2.50),
            self._inverse_range(price_to_earnings, 4.0, 25.0),
        )
        score = (
            profitability_score * 0.20
            + growth_score * 0.15
            + strength_score * 0.30
            + valuation_score * 0.35
        )
        return FundamentalAnalysis(
            score=score,
            profitability_score=profitability_score,
            growth_score=growth_score,
            strength_score=strength_score,
            valuation_score=valuation_score,
            revenue_growth=revenue_growth,
            net_income_growth=net_income_growth,
            operating_margin=None,
            roe=roe,
            debt_to_equity=debt_to_equity,
            current_ratio=current_ratio,
            price_to_earnings=price_to_earnings if price_to_earnings and price_to_earnings > 0 else None,
            price_to_book=price_to_book if price_to_book and price_to_book > 0 else None,
        )

    def _growth(self, current: float | None, previous: float | None) -> float | None:
        if current is None or previous is None or previous <= 0:
            return None
        return current / previous - 1

    def _ratio(self, numerator: float | None, denominator: float | None) -> float | None:
        if numerator is None or denominator is None or denominator == 0:
            return None
        return numerator / denominator

    def _average(self, *values: float | None) -> float:
        available = [value for value in values if value is not None]
        return sum(available) / len(available) if available else 0.5

    def _bounded(self, value: float) -> float:
        return max(0.0, min(1.0, value))

    def _inverse_range(self, value: float | None, low: float, high: float) -> float | None:
        if value is None or value <= 0:
            return None
        return self._bounded((high - value) / (high - low))
