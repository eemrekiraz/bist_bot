from __future__ import annotations

from statistics import mean

from ..models import PriceBar


class NumericEngine:
    def score(self, bars: list[PriceBar]) -> tuple[float, str]:
        if len(bars) < 30:
            return 0.0, "Yetersiz fiyat gecmisi"

        latest = bars[-1]
        closes = [bar.close for bar in bars]
        volumes = [bar.volume for bar in bars]
        ma20 = mean(closes[-20:])
        ma50 = mean(closes[-50:]) if len(closes) >= 50 else mean(closes)
        avg_volume = mean(volumes[-20:-1])

        trend_break = latest.close > ma20 and ma20 >= ma50
        volume_spike = latest.volume / avg_volume if avg_volume else 0.0
        distance_to_ma20 = (latest.close - ma20) / ma20

        score = 0.0
        reasons: list[str] = []
        if trend_break:
            score += 0.35
            reasons.append("Trend kirilimi")
        if volume_spike >= 2.0:
            score += 0.30
            reasons.append(f"Hacim patlamasi x{volume_spike:.1f}")
        if 0.0 <= distance_to_ma20 <= 0.04:
            score += 0.20
            reasons.append("Ortalamaya yakin guclenme")
        if latest.close > bars[-2].high:
            score += 0.15
            reasons.append("Onceki tepe ustu kapanis")

        return min(score, 1.0), " + ".join(reasons) or "Sayisal sinyal zayif"

