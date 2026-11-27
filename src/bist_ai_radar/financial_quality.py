from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .models import FinancialSnapshot


@dataclass(frozen=True)
class FinancialFreshnessReport:
    symbol: str
    latest_period: str
    reference_day: date | None
    age_days: int | None
    max_age_days: int

    @property
    def stale(self) -> bool:
        return self.age_days is not None and self.age_days > self.max_age_days

    @property
    def available(self) -> bool:
        return bool(self.latest_period)

    def to_text(self) -> str:
        if not self.available:
            return "Finansal tazelik: veri yok"
        status = "ESKI" if self.stale else "GUNCEL"
        age = f"{self.age_days} gun" if self.age_days is not None else "bilinmiyor"
        return (
            f"Finansal tazelik: {status} | Son donem {self.latest_period} | "
            f"Yas {age}"
        )


def inspect_financial_freshness(
    snapshots: list[FinancialSnapshot],
    as_of: date | None = None,
    max_age_days: int = 240,
) -> FinancialFreshnessReport:
    if not snapshots:
        return FinancialFreshnessReport("", "", None, None, max_age_days)
    latest = max(snapshots, key=lambda item: _period_key(item.period))
    reference_day = (
        latest.published_at.date()
        if latest.published_at is not None
        else financial_period_end(latest.period)
    )
    age_days = (as_of - reference_day).days if as_of and reference_day else None
    return FinancialFreshnessReport(
        symbol=latest.symbol,
        latest_period=latest.period,
        reference_day=reference_day,
        age_days=age_days,
        max_age_days=max_age_days,
    )


def usable_financial_snapshots(
    snapshots: list[FinancialSnapshot],
    as_of: date | None = None,
    max_age_days: int = 240,
) -> list[FinancialSnapshot]:
    report = inspect_financial_freshness(snapshots, as_of, max_age_days)
    return [] if report.stale else snapshots


def financial_information_available_day(published_at: datetime) -> date:
    return published_at.date() + timedelta(days=1)


def valid_financial_publication(snapshot: FinancialSnapshot) -> bool:
    if snapshot.published_at is None or snapshot.disclosure_index is None:
        return False
    period_end = financial_period_end(snapshot.period)
    return period_end is not None and snapshot.published_at.date() > period_end


def _period_key(period: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in period.split("/")[:2])
    except ValueError:
        return (0, 0)
    return year, month


def financial_period_end(period: str) -> date | None:
    year, month = _period_key(period)
    if year <= 0 or month <= 0:
        return None
    return date(year, month, 28)
