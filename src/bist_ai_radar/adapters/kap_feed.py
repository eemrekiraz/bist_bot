from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
import time
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .http import HttpClient
from ..kap_documents import KapDocumentReader
from ..models import NewsItem

_ISTANBUL = ZoneInfo("Europe/Istanbul")

class KapJsonFeed:
    def __init__(self, url: str, client: HttpClient | None = None) -> None:
        if not url:
            raise ValueError("KAP feed URL is empty. Set KAP_FEED_URL in .env.")
        self.url = url
        self.client = client or HttpClient()

    def read_news(
        self,
        symbol: str | None = None,
        limit: int = 50,
        enrich_documents: bool = False,
        document_limit: int = 3,
    ) -> list[NewsItem]:
        normalized_symbol = symbol.upper() if symbol else None
        payload = (
            self._company_disclosures(normalized_symbol)
            if normalized_symbol
            else self.client.get_json(self.url)
        )
        items = self._items(payload, normalized_symbol, limit)
        return self._enrich_documents(items, document_limit) if enrich_documents else items

    def read_news_history(self, symbol: str, years: int = 5) -> list[NewsItem]:
        normalized_symbol = symbol.upper()
        member_oid = self._member_oid(normalized_symbol)
        if not member_oid:
            return []
        end_date = datetime.now().date()
        cutoff = end_date - timedelta(days=365 * years)
        items_by_key: dict[tuple[str, str, str], NewsItem] = {}
        while end_date >= cutoff:
            start_date = max(cutoff, end_date - timedelta(days=89))
            payload = self._company_disclosures(
                normalized_symbol,
                member_oid=member_oid,
                start_date=start_date,
                end_date=end_date,
            )
            for item in self._items(payload, normalized_symbol, limit=10000):
                key = (item.symbol, item.published_at.isoformat(), item.title)
                items_by_key[key] = item
            end_date = start_date - timedelta(days=1)
            time.sleep(0.40)
        return sorted(items_by_key.values(), key=lambda item: item.published_at)

    def read_news_window(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[NewsItem]:
        normalized_symbol = symbol.upper()
        payload = self._company_disclosures(
            normalized_symbol,
            start_date=start_date,
            end_date=end_date,
        )
        return self._items(payload, normalized_symbol, limit=10000)

    def read_market_news(self, end_date: date) -> list[NewsItem]:
        payload = self._disclosures(
            member_oid=None,
            start_date=end_date - timedelta(days=1),
            end_date=end_date,
        )
        return self._items(payload, normalized_symbol=None, limit=2500)

    def _items(
        self,
        payload: Any,
        normalized_symbol: str | None,
        limit: int,
    ) -> list[NewsItem]:
        records = self._records(payload)
        items: list[NewsItem] = []
        for record in records:
            try:
                item = self._to_news_item(record)
            except ValueError:
                continue
            if item is None:
                continue
            symbols = self._symbols(record)
            items.extend(
                replace(item, symbol=symbol) for symbol in symbols
                if normalized_symbol is None or symbol == normalized_symbol
            )
        items.sort(key=lambda item: (
            item.published_at
            if item.published_at.tzinfo is not None
            else item.published_at.replace(tzinfo=_ISTANBUL)
        ))
        return items[-limit:] if limit > 0 else []

    def _member_oid(self, symbol: str) -> str | None:
        api_root = self.url.split("/api/", maxsplit=1)[0]
        matches = self.client.get_json(f"{api_root}/api/member/filter/{quote(symbol)}")
        if not isinstance(matches, list):
            return []
        member = next(
            (
                item
                for item in matches
                if isinstance(item, dict) and str(item.get("mkkMemberOid", "")).strip()
            ),
            None,
        )
        return str(member["mkkMemberOid"]) if member else None

    def _company_disclosures(
        self,
        symbol: str,
        member_oid: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Any:
        resolved_member_oid = member_oid or self._member_oid(symbol)
        if not resolved_member_oid:
            return []
        window_end = end_date or datetime.now().date()
        window_start = start_date or window_end - timedelta(days=89)
        return self._disclosures(resolved_member_oid, window_start, window_end)

    def _disclosures(self, member_oid: str | None, start_date: date, end_date: date) -> Any:
        api_root = self.url.split("/api/", maxsplit=1)[0]
        payload = {
            "fromDate": start_date.strftime("%d.%m.%Y"),
            "toDate": end_date.strftime("%d.%m.%Y"),
            "disclosureTypes": None,
            "memberTypes": [],
            "mkkMemberOid": member_oid,
        }
        return self.client.post_json(f"{api_root}/api/disclosure/list/main", payload)

    def _records(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("disclosures", "items", "data", "result"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    def _to_news_item(self, record: dict[str, Any]) -> NewsItem | None:
        original = record
        basic = record.get("disclosureBasic")
        if isinstance(basic, dict):
            record = basic
        title = self._first_text(record, "title", "subject", "disclosureClass", "summary")
        published = self._first_text(record, "published_at", "publishDate", "disclosureDate", "date")
        if not title or not published:
            return None
        body = self._first_text(
            record,
            "body",
            "text",
            "content",
            "description",
            "additionalExplanation",
            "summary",
            "subject",
        ) or self._first_text(
            original,
            "body",
            "text",
            "content",
            "description",
            "additionalExplanation",
            "summary",
            "subject",
        ) or ""
        source = self._first_text(record, "source") or "KAP"
        disclosure_index = self._disclosure_index(record, original)
        return NewsItem(
            symbol=self._symbols(original)[0],
            published_at=self._parse_datetime(published),
            source=source,
            title=title,
            body=body,
            disclosure_index=disclosure_index,
            source_url=(
                f"{self._site_root()}/tr/Bildirim/{disclosure_index}"
                if disclosure_index is not None
                else ""
            ),
        )

    def _symbols(self, original: dict[str, Any]) -> tuple[str, ...]:
        basic = original.get("disclosureBasic")
        for record in (basic, original):
            if not isinstance(record, dict):
                continue
            value = self._first_text(record, "symbol", "stockCode", "ticker", "relatedStocks", "companyCode")
            if value:
                symbols = tuple(dict.fromkeys(code.strip().upper() for code in value.split(",") if code.strip()))
                if symbols:
                    return symbols
        return ("GENEL",)

    def _enrich_documents(
        self,
        items: list[NewsItem],
        document_limit: int,
    ) -> list[NewsItem]:
        reader = KapDocumentReader(
            client=self.client,
            base_url=self._site_root(),
        )
        enriched: list[NewsItem] = []
        remaining = max(0, document_limit)
        for item in reversed(items):
            if remaining and item.disclosure_index and len(item.body.strip()) < 300:
                document = reader.read(item.disclosure_index)
                if document is not None:
                    item = NewsItem(
                        symbol=item.symbol,
                        published_at=item.published_at,
                        source=item.source,
                        title=item.title,
                        body=document.text,
                        disclosure_index=item.disclosure_index,
                        source_url=document.url,
                    )
                remaining -= 1
            enriched.append(item)
        return list(reversed(enriched))

    def _site_root(self) -> str:
        return self.url.split("/tr/api/", maxsplit=1)[0].rstrip("/")

    def _disclosure_index(
        self,
        record: dict[str, Any],
        original: dict[str, Any],
    ) -> int | None:
        for source in (record, original):
            value = source.get("disclosureIndex") or source.get("disclosure_index")
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    def _first_text(self, record: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = record.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    def _parse_datetime(self, value: str) -> datetime:
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            for pattern in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
                try:
                    return datetime.strptime(value, pattern)
                except ValueError:
                    continue
        raise ValueError(f"Unsupported KAP date format: {value}")
