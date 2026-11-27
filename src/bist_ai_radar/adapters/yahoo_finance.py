from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import os
from pathlib import Path
from urllib.parse import urlencode

from .csv_feed import CsvMarketDataFeed
from .http import HttpClient
from ..models import PriceBar


class YahooFinanceFeed:
    def __init__(
        self,
        client: HttpClient | None = None,
        base_url: str = "https://query1.finance.yahoo.com/v8/finance/chart",
        fallback_base_url: str = "https://query2.finance.yahoo.com/v8/finance/chart",
        csv_fallback_directory: str | Path | None = None,
    ) -> None:
        self.client = client or HttpClient()
        self.base_url = base_url.rstrip("/")
        self.fallback_base_url = fallback_base_url.rstrip("/")
        self.csv_fallback_directory = Path(
            csv_fallback_directory
            or os.getenv("PRICE_FALLBACK_CSV_DIR", "data/price_fallback")
        )

    def read_price_bars(self, symbol: str, days: int = 550) -> list[PriceBar]:
        errors: list[str] = []
        endpoints = tuple(
            endpoint
            for endpoint in (self.base_url, self.fallback_base_url)
            if endpoint
        )
        for index, endpoint in enumerate(dict.fromkeys(endpoints)):
            try:
                return self._read_price_bars(
                    symbol,
                    days,
                    endpoint,
                    "YAHOO" if index == 0 else "YAHOO_FALLBACK",
                )
            except RuntimeError as error:
                errors.append(str(error))
        try:
            bars = self._read_csv_fallback(symbol, days)
            if bars:
                return bars
        except (OSError, ValueError, KeyError) as error:
            errors.append(f"CSV fallback: {error}")
        raise RuntimeError(
            f"Yahoo Finance price fetch failed for {symbol.upper()}: "
            + " | ".join(errors)
        )

    def _read_price_bars(
        self,
        symbol: str,
        days: int,
        endpoint: str,
        source: str,
    ) -> list[PriceBar]:
        query_symbol = self._to_yahoo_symbol(symbol)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        query = urlencode(
            {
                "period1": int(start.timestamp()),
                "period2": int(end.timestamp()),
                "interval": "1d",
                "events": "history",
            }
        )
        payload = self.client.get_json(f"{endpoint}/{query_symbol}?{query}")
        result = payload.get("chart", {}).get("result") or []
        if not result:
            error = payload.get("chart", {}).get("error")
            raise RuntimeError(f"No Yahoo Finance data for {query_symbol}: {error}")

        chart = result[0]
        timestamps = chart.get("timestamp") or []
        quote = (chart.get("indicators", {}).get("quote") or [{}])[0]
        adjusted_close = (
            chart.get("indicators", {}).get("adjclose") or [{}]
        )[0].get("adjclose")
        bars: list[PriceBar] = []
        for index, timestamp in enumerate(timestamps):
            open_price = self._value_at(quote.get("open"), index)
            high = self._value_at(quote.get("high"), index)
            low = self._value_at(quote.get("low"), index)
            close = self._value_at(quote.get("close"), index)
            volume = self._value_at(quote.get("volume"), index)
            if None in {open_price, high, low, close, volume}:
                continue
            adjusted = self._value_at(adjusted_close, index)
            adjustment_factor = (
                float(adjusted) / float(close)
                if adjusted is not None and float(close) > 0
                else 1.0
            )
            bars.append(
                PriceBar(
                    symbol=symbol.upper(),
                    day=datetime.fromtimestamp(timestamp, timezone.utc).date(),
                    open=float(open_price) * adjustment_factor,
                    high=float(high) * adjustment_factor,
                    low=float(low) * adjustment_factor,
                    close=float(close) * adjustment_factor,
                    volume=int(volume),
                    raw_open=float(open_price),
                    raw_high=float(high),
                    raw_low=float(low),
                    raw_close=float(close),
                    source=source,
                )
            )
        bars = self._dedupe_market_days(bars)
        if not bars:
            raise RuntimeError(f"No usable Yahoo Finance data for {query_symbol}")
        return bars

    def _read_csv_fallback(self, symbol: str, days: int) -> list[PriceBar]:
        normalized = symbol.upper().removesuffix(".IS")
        path = self.csv_fallback_directory / f"{normalized}.csv"
        if not path.exists():
            return []
        cutoff = date.today() - timedelta(days=days)
        bars = CsvMarketDataFeed().read_price_bars(path, normalized)
        return [
            PriceBar(
                symbol=bar.symbol,
                day=bar.day,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                raw_open=bar.raw_open,
                raw_high=bar.raw_high,
                raw_low=bar.raw_low,
                raw_close=bar.raw_close,
                source="CSV_FALLBACK",
            )
            for bar in bars
            if bar.day >= cutoff
        ]

    def _to_yahoo_symbol(self, symbol: str) -> str:
        normalized = symbol.upper()
        if normalized.endswith(".IS") or "=" in normalized or normalized.startswith("^"):
            return normalized
        return f"{normalized}.IS"

    def _value_at(self, values: list[float | int | None] | None, index: int) -> float | int | None:
        if not values or index >= len(values):
            return None
        return values[index]

    def _dedupe_market_days(self, bars: list[PriceBar]) -> list[PriceBar]:
        deduped: dict[date, PriceBar] = {}
        for bar in bars:
            if bar.day <= datetime.combine(date.today(), time.min).date():
                deduped[bar.day] = bar
        return [deduped[day] for day in sorted(deduped)]
