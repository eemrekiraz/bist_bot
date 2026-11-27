"""Matured outcomes of ledger recommendations, compared with BIST and sector.

An outcome exists for a horizon only after that many sessions have actually
traded since the recommendation's close day; nothing is extrapolated, and a
12-month label is never filled before 252 sessions have passed. Returns use
the adjusted close so dividends and splits do not count as gains or losses.

Every outcome separates the absolute result from the relative one, so a loss
in a falling market is not automatically counted as a selection error.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
from statistics import mean, pstdev

from .models import PriceBar

BENCHMARK_SYMBOL = "XU100"
HORIZONS = {5: "1 hafta", 21: "1 ay", 63: "3 ay", 126: "6 ay", 252: "12 ay"}
# Assumed round-trip commission + slippage. An explicit assumption, reported
# with every evaluation; it is not a measured cost.
DEFAULT_ROUND_TRIP_COST = 0.002
MIN_SECTOR_PEERS = 3
# Descriptive market-regime labels for the evaluation window. They describe the
# market, they are not training thresholds.
REGIME_Z = 0.5
CRISIS_DRAWDOWN = -0.15
EXECUTION_NOTE = "Bot emir, stop veya pozisyon uygulamaz; sonuç kapanıştan kapanışa ölçülür."


@dataclass(frozen=True)
class Outcome:
    entry_id: str
    symbol: str
    profile: str
    method_version: str
    published_at: str
    main_sector: str
    horizon: int
    exit_day: str
    gross_return: float
    net_return: float
    cost_assumption: float
    benchmark_return: float | None
    excess_vs_benchmark: float | None
    sector_return: float | None
    sector_peers_used: int
    excess_vs_sector: float | None
    regime: str
    corporate_action_in_window: bool
    attribution: str

    def to_dict(self) -> dict:
        return asdict(self)


def _index(bars: list[PriceBar]) -> dict[str, int]:
    return {bar.day.isoformat(): position for position, bar in enumerate(bars)}


def _window_return(bars: list[PriceBar], start_day: str, end_day: str) -> float | None:
    days = _index(bars)
    if start_day not in days or end_day not in days:
        return None
    start, end = bars[days[start_day]], bars[days[end_day]]
    if start.close <= 0 or end.close <= 0:
        return None
    return end.close / start.close - 1


def _corporate_action(bars: list[PriceBar], start: int, end: int) -> bool:
    factors = [
        bar.close / bar.trade_close for bar in bars[start:end + 1] if bar.trade_close > 0
    ]
    return bool(factors) and (max(factors) / min(factors) - 1) >= 0.03


def classify_regime(benchmark: list[PriceBar], start_day: str, end_day: str) -> str:
    days = _index(benchmark)
    if start_day not in days or end_day not in days:
        return "bilinmiyor"
    window = [bar.close for bar in benchmark[days[start_day]:days[end_day] + 1]]
    if len(window) < 2 or min(window) <= 0:
        return "bilinmiyor"
    peak, drawdown = window[0], 0.0
    for value in window:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    if drawdown <= CRISIS_DRAWDOWN:
        return "kriz"
    daily = [b / a - 1 for a, b in zip(window, window[1:])]
    spread = pstdev(daily) * sqrt(len(daily)) if len(daily) > 1 else 0.0
    total = window[-1] / window[0] - 1
    if spread <= 0:
        return "yatay"
    z = total / spread
    return "boga" if z >= REGIME_Z else "ayi" if z <= -REGIME_Z else "yatay"


def attribute(net_return: float, excess: float | None) -> str:
    if excess is None:
        return "karsilastirma_eksik"
    if excess > 0:
        return "basarili" if net_return > 0 else "piyasa_kaynakli_zarar"
    return "endeksin_gerisinde_kar" if net_return > 0 else "secim_hatasi"


def evaluate_entry(
    entry: dict,
    bars_by_symbol: dict[str, list[PriceBar]],
    *,
    horizons: tuple[int, ...] = tuple(HORIZONS),
    round_trip_cost: float = DEFAULT_ROUND_TRIP_COST,
) -> list[Outcome]:
    bars = bars_by_symbol.get(entry["symbol"], [])
    days = _index(bars)
    start_day = entry["close_day"]
    if start_day not in days:
        return []
    start = days[start_day]
    benchmark = bars_by_symbol.get(BENCHMARK_SYMBOL, [])
    outcomes = []
    for horizon in horizons:
        end = start + horizon
        if end >= len(bars):
            continue
        exit_day = bars[end].day.isoformat()
        gross = _window_return(bars, start_day, exit_day)
        if gross is None:
            continue
        net = gross - round_trip_cost
        bench = _window_return(benchmark, start_day, exit_day)
        peer_returns = [
            value for value in (
                _window_return(bars_by_symbol.get(peer, []), start_day, exit_day)
                for peer in entry.get("sector_peers", [])
            ) if value is not None
        ]
        sector = mean(peer_returns) if len(peer_returns) >= MIN_SECTOR_PEERS else None
        excess = None if bench is None else net - bench
        outcomes.append(Outcome(
            entry_id=entry["entry_id"], symbol=entry["symbol"], profile=entry["profile"],
            method_version=entry["method_version"], published_at=entry["published_at"],
            main_sector=entry["main_sector"], horizon=horizon, exit_day=exit_day,
            gross_return=gross, net_return=net, cost_assumption=round_trip_cost,
            benchmark_return=bench, excess_vs_benchmark=excess,
            sector_return=sector, sector_peers_used=len(peer_returns),
            excess_vs_sector=None if sector is None else net - sector,
            regime=classify_regime(benchmark, start_day, exit_day),
            corporate_action_in_window=_corporate_action(bars, start, end),
            attribution=attribute(net, excess),
        ))
    return outcomes


def evaluate_ledger(
    entries: list[dict], bars_by_symbol: dict[str, list[PriceBar]], **options: object,
) -> list[Outcome]:
    return [
        outcome for entry in entries
        for outcome in evaluate_entry(entry, bars_by_symbol, **options)
    ]


def _share(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(outcomes: list[Outcome], pending: int = 0) -> dict:
    """Per-horizon summary, split by regime and by error attribution."""
    summary: dict = {
        "pending_entries": pending,
        "execution": EXECUTION_NOTE,
        "cost_assumption": outcomes[0].cost_assumption if outcomes else DEFAULT_ROUND_TRIP_COST,
        "horizons": {},
    }
    for horizon, label in HORIZONS.items():
        rows = [item for item in outcomes if item.horizon == horizon]
        if not rows:
            continue
        compared = [item for item in rows if item.excess_vs_benchmark is not None]
        by_regime: dict[str, dict] = {}
        for regime in sorted({item.regime for item in compared}):
            group = [item for item in compared if item.regime == regime]
            by_regime[regime] = {
                "count": len(group),
                "beat_benchmark": _share([item.excess_vs_benchmark > 0 for item in group]),
                "mean_excess": mean(item.excess_vs_benchmark for item in group),
            }
        attributions: dict[str, int] = {}
        for item in rows:
            attributions[item.attribution] = attributions.get(item.attribution, 0) + 1
        sector_rows = [item.excess_vs_sector for item in rows if item.excess_vs_sector is not None]
        summary["horizons"][str(horizon)] = {
            "label": label,
            "count": len(rows),
            "absolute_positive": _share([item.net_return > 0 for item in rows]),
            "mean_net_return": mean(item.net_return for item in rows),
            "compared_with_benchmark": len(compared),
            "beat_benchmark": _share([item.excess_vs_benchmark > 0 for item in compared]),
            "mean_excess_vs_benchmark": mean(item.excess_vs_benchmark for item in compared) if compared else None,
            "compared_with_sector": len(sector_rows),
            "mean_excess_vs_sector": mean(sector_rows) if sector_rows else None,
            "corporate_action_windows": sum(item.corporate_action_in_window for item in rows),
            "by_regime": by_regime,
            "attribution": attributions,
        }
    return summary
