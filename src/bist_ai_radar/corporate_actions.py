from __future__ import annotations

from dataclasses import dataclass

from .models import PriceBar


@dataclass(frozen=True)
class CorporateActionCheck:
    detected: bool
    recent: bool
    note: str
    verified: bool = True


def assess_corporate_actions(
    bars: list[PriceBar],
    recent_sessions: int = 5,
) -> CorporateActionCheck:
    """Detect Yahoo adjustment-factor changes and avoid trading through them blindly."""
    if len(bars) < 2:
        return CorporateActionCheck(False, False, "Kurumsal aksiyon kontrolu icin fiyat gecmisi yetersiz")

    events: list[int] = []
    for index, (previous, current) in enumerate(zip(bars, bars[1:]), start=1):
        if previous.trade_close <= 0 or current.trade_close <= 0:
            continue
        previous_factor = previous.close / previous.trade_close
        current_factor = current.close / current.trade_close
        factor_change = current_factor / previous_factor - 1 if previous_factor else 0.0
        raw_return = current.trade_close / previous.trade_close - 1
        adjusted_return = current.close / previous.close - 1 if previous.close else 0.0
        if abs(factor_change) >= 0.03 and abs(raw_return - adjusted_return) >= 0.03:
            events.append(index)

    if not events:
        return CorporateActionCheck(False, False, "Kurumsal aksiyon duzeltmesi yok")
    recent = events[-1] >= max(1, len(bars) - recent_sessions)
    if recent:
        return CorporateActionCheck(
            True,
            True,
            "Yeni temettu/bolunme/sermaye hareketi duzeltmesi: emir teyidi bekleniyor",
        )
    return CorporateActionCheck(
        True,
        False,
        "Gecmiste kurumsal aksiyon duzeltmesi var; teknik hesaplar duzeltilmis fiyatla yapildi",
    )


def corporate_action_history_verified(bars: list[PriceBar]) -> bool:
    if len(bars) < 2:
        return False
    for previous, current in zip(bars, bars[1:]):
        if (
            previous.raw_close is None
            or current.raw_close is None
            or previous.trade_close <= 0
            or current.trade_close <= 0
            or previous.close <= 0
        ):
            continue
        previous_factor = previous.close / previous.trade_close
        current_factor = current.close / current.trade_close
        if previous_factor <= 0:
            return False
        factor_change = current_factor / previous_factor - 1
        if abs(factor_change) < 0.03:
            continue
        raw_return = current.trade_close / previous.trade_close - 1
        adjusted_return = current.close / previous.close - 1
        if abs(raw_return - adjusted_return) < 0.02 or abs(adjusted_return) >= 0.30:
            return False
    return True
