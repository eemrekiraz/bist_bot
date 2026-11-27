from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class PriceBar:
    symbol: str
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    raw_open: float | None = None
    raw_high: float | None = None
    raw_low: float | None = None
    raw_close: float | None = None
    source: str = ""

    @property
    def trade_open(self) -> float:
        return self.raw_open if self.raw_open is not None else self.open

    @property
    def trade_high(self) -> float:
        return self.raw_high if self.raw_high is not None else self.high

    @property
    def trade_low(self) -> float:
        return self.raw_low if self.raw_low is not None else self.low

    @property
    def trade_close(self) -> float:
        return self.raw_close if self.raw_close is not None else self.close


@dataclass(frozen=True)
class NewsItem:
    symbol: str
    published_at: datetime
    source: str
    title: str
    body: str
    disclosure_index: int | None = None
    source_url: str = ""


@dataclass(frozen=True)
class FinancialSnapshot:
    symbol: str
    period: str
    currency_scale: float
    current_assets: float | None = None
    total_assets: float | None = None
    current_liabilities: float | None = None
    total_liabilities: float | None = None
    equity: float | None = None
    paid_capital: float | None = None
    revenue: float | None = None
    gross_profit: float | None = None
    operating_profit: float | None = None
    net_income: float | None = None
    operating_cash_flow: float | None = None
    capital_expenditures: float | None = None
    cash_and_equivalents: float | None = None
    dividends_paid: float | None = None
    published_at: datetime | None = None
    disclosure_index: int | None = None
    source: str = "KAP"

    @property
    def free_cash_flow(self) -> float | None:
        if self.operating_cash_flow is None or self.capital_expenditures is None:
            return None
        return self.operating_cash_flow - abs(self.capital_expenditures)


@dataclass(frozen=True)
class CompanyProfile:
    symbol: str
    title: str
    city: str
    permalink: str
    sector: str = ""
    is_active: bool = True
    first_trade_day: date | None = None
    last_trade_day: date | None = None
    source: str = "KAP"


@dataclass(frozen=True)
class MacroNewsItem:
    source: str
    published_at: datetime
    title: str
    body: str
    link: str


@dataclass(frozen=True)
class Signal:
    symbol: str
    reason: str
    score: float
    probability: float
    expected_return_pct: float
    entry: float
    stop: float
    target: float
    horizon_days: int
    capital_at_risk_pct: float = 1.0
    position_size_pct: float = 10.0
    risk_reward: float = 1.0
    action: str = "IZLE"
    execution_cost_pct: float = 0.60

    def to_telegram_message(self) -> str:
        return (
            f"GOZUME TAKILAN FIRSAT: {self.symbol}\n"
            f"- Vade: {self.horizon_days} islem gunu\n"
            f"- Aksiyon: {self.action}\n"
            f"- Guven: %{self.probability * 100:.0f} | Bilesik skor: {self.score:.2f}\n"
            f"- Neden: {self.reason}\n"
            f"- Beklenen getiri: %{self.expected_return_pct:.1f}\n\n"
            "ISLEM PLANI\n"
            f"- Giris: {self.entry:.2f} TL\n"
            f"- Stop: {self.stop:.2f} TL\n"
            f"- Hedef: {self.target:.2f} TL\n"
            f"- Onerilen buyukluk: portfoyun %{self.position_size_pct:.1f}\n"
            f"- Sermaye riski: %{self.capital_at_risk_pct:.2f} | "
            f"R/R: {self.risk_reward:.2f} | Tahmini maliyet: ~%{self.execution_cost_pct:.2f}"
        )


def signal_action(
    score: float,
    probability: float,
    risk_reward: float,
    position_size_pct: float,
) -> str:
    if risk_reward < 1.0 or position_size_pct <= 0:
        return "IZLE"
    if score >= 0.72 and probability >= 0.65 and risk_reward >= 1.5:
        return "KADEMELI AL"
    if score >= 0.62 and probability >= 0.55 and risk_reward >= 1.2:
        return "LIMIT BEKLE"
    return "IZLE"
