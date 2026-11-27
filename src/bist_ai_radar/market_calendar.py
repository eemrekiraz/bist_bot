from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .models import PriceBar

TARGET_CALENDAR_VERSION = "BIST_SESSIONS_V1"
MARKET_OPEN_TIME = time(10, 0)
FULL_DAY_CLOSE_TIME = time(18, 10)
HALF_DAY_CLOSE_TIME = time(13, 0)


@dataclass(frozen=True)
class MarketSession:
    day: date
    status: str
    close_time: time | None
    reason: str = ""

    @property
    def is_open(self) -> bool:
        return self.status in {"FULL", "HALF"}


_FIXED_CLOSED_DAYS = {
    (1, 1): "Yilbasi",
    (4, 23): "Ulusal Egemenlik ve Cocuk Bayrami",
    (5, 1): "Emek ve Dayanisma Gunu",
    (5, 19): "Ataturk'u Anma, Genclik ve Spor Bayrami",
    (7, 15): "Demokrasi ve Milli Birlik Gunu",
    (8, 30): "Zafer Bayrami",
    (10, 29): "Cumhuriyet Bayrami",
}
_YEAR_CLOSED_DAYS = {
    2025: {
        date(2025, 3, 31): "Ramazan Bayrami",
        date(2025, 4, 1): "Ramazan Bayrami",
        date(2025, 6, 6): "Kurban Bayrami",
        date(2025, 6, 9): "Kurban Bayrami",
    },
    2026: {
        date(2026, 3, 20): "Ramazan Bayrami",
        date(2026, 5, 27): "Kurban Bayrami",
        date(2026, 5, 28): "Kurban Bayrami",
        date(2026, 5, 29): "Kurban Bayrami",
    },
}
_YEAR_HALF_DAYS = {
    2025: {
        date(2025, 6, 5): "Kurban Bayrami Arefesi",
        date(2025, 10, 28): "Cumhuriyet Bayrami Arefesi",
    },
    2026: {
        date(2026, 3, 19): "Ramazan Bayrami Arefesi",
        date(2026, 5, 26): "Kurban Bayrami Arefesi",
        date(2026, 10, 28): "Cumhuriyet Bayrami Arefesi",
    },
}


def market_session(day: date) -> MarketSession:
    if day.weekday() >= 5:
        return MarketSession(day, "CLOSED", None, "Hafta sonu")
    special_closed = _YEAR_CLOSED_DAYS.get(day.year, {}).get(day)
    if special_closed:
        return MarketSession(day, "CLOSED", None, special_closed)
    fixed_closed = _FIXED_CLOSED_DAYS.get((day.month, day.day))
    if fixed_closed:
        return MarketSession(day, "CLOSED", None, fixed_closed)
    half_day = _YEAR_HALF_DAYS.get(day.year, {}).get(day)
    if half_day:
        return MarketSession(day, "HALF", HALF_DAY_CLOSE_TIME, half_day)
    return MarketSession(day, "FULL", FULL_DAY_CLOSE_TIME)


def is_market_session(day: date) -> bool:
    return market_session(day).is_open


def is_market_open_at(moment: datetime) -> bool:
    session = market_session(moment.date())
    return bool(
        session.is_open
        and session.close_time is not None
        and MARKET_OPEN_TIME <= moment.time().replace(tzinfo=None) <= session.close_time
    )


def is_first_market_session_of_week(day: date) -> bool:
    if not is_market_session(day):
        return False
    monday = day - timedelta(days=day.weekday())
    return not any(is_market_session(monday + timedelta(days=offset)) for offset in range((day - monday).days))


def is_last_market_session_of_week(day: date) -> bool:
    if not is_market_session(day):
        return False
    return not any(
        is_market_session(day + timedelta(days=offset))
        for offset in range(1, 5 - day.weekday())
    )


def build_market_target_days(
    market_bars: list[PriceBar],
    horizon_sessions: int,
) -> dict[date, date]:
    return {
        market_bars[index].day: market_bars[index + horizon_sessions].day
        for index in range(len(market_bars) - horizon_sessions)
    }


def forward_return_to_day(
    bars: list[PriceBar],
    checkpoint: date,
    target_day: date,
    raw_prices: bool = False,
) -> float | None:
    days = [bar.day for bar in bars]
    entry_position = bisect_right(days, checkpoint) - 1
    exit_position = bisect_right(days, target_day) - 1
    if entry_position < 0 or exit_position < entry_position:
        return None
    entry = (
        bars[entry_position].trade_close
        if raw_prices
        else bars[entry_position].close
    )
    exit_price = (
        bars[exit_position].trade_close
        if raw_prices
        else bars[exit_position].close
    )
    if entry <= 0:
        return None
    return exit_price / entry - 1


def build_forward_return_map(
    bars: list[PriceBar],
    market_target_days: dict[date, date],
    raw_prices: bool = False,
) -> dict[date, float]:
    days = [bar.day for bar in bars]
    values: dict[date, float] = {}
    for entry_position, bar in enumerate(bars):
        target_day = market_target_days.get(bar.day)
        if target_day is None:
            continue
        exit_position = bisect_right(days, target_day) - 1
        if exit_position < entry_position:
            continue
        entry = bar.trade_close if raw_prices else bar.close
        exit_bar = bars[exit_position]
        exit_price = exit_bar.trade_close if raw_prices else exit_bar.close
        if entry > 0:
            values[bar.day] = exit_price / entry - 1
    return values
