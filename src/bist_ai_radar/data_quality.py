from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .models import PriceBar
from .corporate_actions import corporate_action_history_verified


@dataclass(frozen=True)
class PriceQualityReport:
    symbol: str
    source: str
    bars: int
    raw_coverage: float
    invalid_bars: int
    extreme_moves: tuple[str, ...]
    adjustment_changes: tuple[str, ...]
    latest_day: date | None = None
    age_days: int | None = None
    max_age_days: int | None = None

    @property
    def passed(self) -> bool:
        return (
            self.raw_coverage >= 0.95
            and self.invalid_bars == 0
            and len(self.extreme_moves) == 0
            and not self.stale
        )

    @property
    def stale(self) -> bool:
        return (
            self.age_days is not None
            and self.max_age_days is not None
            and self.age_days > self.max_age_days
        )

    def to_text(self) -> str:
        status = "GECTI" if self.passed else "INCELE"
        freshness = (
            f"Son fiyat: {self.latest_day.isoformat()} | Yas: {self.age_days} gun"
            if self.latest_day is not None and self.age_days is not None
            else "Son fiyat: bilinmiyor"
        )
        lines = [
            f"FIYAT KALITE: {self.symbol} | {status}",
            f"Kaynak: {self.source or 'Bilinmiyor'}",
            f"Satir: {self.bars} | Ham fiyat kapsami: %{self.raw_coverage * 100:.1f}",
            freshness,
            f"Gecersiz OHLC: {self.invalid_bars}",
            f"Asiri gunluk hareket: {len(self.extreme_moves)}",
            f"Duzeltme faktoru degisimi: {len(self.adjustment_changes)}",
        ]
        if self.stale:
            lines.append(f"  Uyari: fiyat verisi {self.max_age_days} gun esiginden eski")
        lines.extend(f"  Hareket: {item}" for item in self.extreme_moves[:10])
        lines.extend(f"  Kurumsal aksiyon adayi: {item}" for item in self.adjustment_changes[:10])
        return "\n".join(lines)


def inspect_price_quality(
    bars: list[PriceBar],
    as_of: date | None = None,
    max_age_days: int | None = None,
) -> PriceQualityReport:
    if not bars:
        return PriceQualityReport("UNKNOWN", "", 0, 0.0, 0, (), ())
    raw_count = sum(bar.raw_close is not None for bar in bars)
    invalid_bars = sum(
        bar.trade_low <= 0
        or bar.trade_high < bar.trade_low
        or not bar.trade_low <= bar.trade_open <= bar.trade_high
        or not bar.trade_low <= bar.trade_close <= bar.trade_high
        for bar in bars
    )
    extreme_moves: list[str] = []
    adjustment_changes: list[str] = []
    previous_factor: float | None = None
    for previous, current in zip(bars, bars[1:]):
        raw_return = current.trade_close / previous.trade_close - 1
        adjusted_return = current.close / previous.close - 1
        if abs(raw_return) >= 0.35 and abs(adjusted_return) >= 0.25:
            extreme_moves.append(
                f"{current.day.isoformat()} ham %{raw_return * 100:+.1f}, "
                f"duzeltilmis %{adjusted_return * 100:+.1f}"
            )
        factor = (
            current.close / current.trade_close
            if current.trade_close > 0
            else 1.0
        )
        if previous_factor is not None and abs(factor / previous_factor - 1) >= 0.03:
            adjustment_changes.append(
                f"{current.day.isoformat()} faktor {previous_factor:.5f}->{factor:.5f}"
            )
        previous_factor = factor
    latest_day = bars[-1].day
    age_days = (as_of - latest_day).days if as_of is not None else None
    return PriceQualityReport(
        symbol=bars[-1].symbol,
        source=bars[-1].source,
        bars=len(bars),
        raw_coverage=raw_count / len(bars),
        invalid_bars=invalid_bars,
        extreme_moves=tuple(extreme_moves),
        adjustment_changes=tuple(adjustment_changes),
        latest_day=latest_day,
        age_days=age_days,
        max_age_days=max_age_days,
    )


def training_price_history_is_valid(bars: list[PriceBar]) -> bool:
    report = inspect_price_quality(bars)
    return (
        report.raw_coverage >= 0.95
        and report.invalid_bars == 0
        and not report.extreme_moves
        and corporate_action_history_verified(bars)
    )
