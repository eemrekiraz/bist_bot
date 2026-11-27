from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from ..models import NewsItem, PriceBar


class CsvMarketDataFeed:
    def read_price_bars(self, path: str | Path, symbol: str | None = None) -> list[PriceBar]:
        bars: list[PriceBar] = []
        with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                row_symbol = (symbol or row["symbol"]).upper()
                bars.append(
                    PriceBar(
                        symbol=row_symbol,
                        day=date.fromisoformat(row["day"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=int(float(row["volume"])),
                        raw_open=float(row["open"]),
                        raw_high=float(row["high"]),
                        raw_low=float(row["low"]),
                        raw_close=float(row["close"]),
                        source="CSV",
                    )
                )
        return sorted(bars, key=lambda bar: (bar.symbol, bar.day))

    def read_news(self, path: str | Path, symbol: str | None = None) -> list[NewsItem]:
        news: list[NewsItem] = []
        with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                row_symbol = (symbol or row["symbol"]).upper()
                published_at = datetime.fromisoformat(row["published_at"])
                news.append(
                    NewsItem(
                        symbol=row_symbol,
                        published_at=published_at,
                        source=row.get("source", "CSV"),
                        title=row["title"],
                        body=row.get("body", ""),
                    )
                )
        return sorted(news, key=lambda item: (item.symbol, item.published_at))
