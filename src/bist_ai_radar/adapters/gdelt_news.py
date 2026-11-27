from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode, urlparse

from .http import HttpClient
from ..models import MacroNewsItem


class GdeltNewsFeed:
    trusted_domains = {
        "reuters.com",
        "apnews.com",
        "bbc.com",
        "bbc.co.uk",
        "bloomberg.com",
        "ft.com",
        "cnbc.com",
        "dw.com",
        "aljazeera.com",
        "aa.com.tr",
        "trthaber.com",
        "theguardian.com",
        "euronews.com",
    }

    def __init__(
        self,
        base_url: str = "https://api.gdeltproject.org/api/v2/doc/doc",
        client: HttpClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.client = client or HttpClient(timeout_seconds=35)

    def read(self, max_records: int = 50, timespan: str = "6h") -> list[MacroNewsItem]:
        query = urlencode(
            {
                "query": (
                    "(Turkey OR Europe OR \"Middle East\" OR \"United States\" "
                    "OR China OR Russia OR global) "
                    "(economy OR inflation OR interest OR currency OR central bank "
                    "OR oil OR gas OR commodity OR trade OR tariff OR shipping "
                    "OR supply chain OR semiconductor OR war OR conflict OR sanction)"
                ),
                "mode": "ArtList",
                "maxrecords": max_records,
                "format": "json",
                "timespan": timespan,
                "sort": "HybridRel",
            }
        )
        payload = self.client.get_json(f"{self.base_url}?{query}")
        items: list[MacroNewsItem] = []
        for article in payload.get("articles", []):
            url = str(article.get("url", "")).strip()
            domain = self._registered_domain(url)
            if not url or domain not in self.trusted_domains:
                continue
            title = str(article.get("title", "")).strip()
            seen_date = str(article.get("seendate", "")).strip()
            if not title or not seen_date:
                continue
            items.append(
                MacroNewsItem(
                    source=f"GDELT:{domain}",
                    published_at=datetime.strptime(seen_date, "%Y%m%dT%H%M%SZ"),
                    title=title,
                    body=f"Trusted global source: {domain}",
                    link=url,
                )
            )
        return items

    def _registered_domain(self, url: str) -> str:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        for domain in self.trusted_domains:
            if host == domain or host.endswith(f".{domain}"):
                return domain
        return host
