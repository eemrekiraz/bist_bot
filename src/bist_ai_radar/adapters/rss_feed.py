from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from .http import HttpClient
from ..models import MacroNewsItem


class OfficialRssFeed:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def read(
        self,
        source: str,
        url: str,
        limit: int = 10,
        enrich: bool = True,
    ) -> list[MacroNewsItem]:
        root = ElementTree.fromstring(self.client.get_text(url))
        entries = root.findall(".//item") or root.findall(".//{*}entry")
        items: list[MacroNewsItem] = []
        for entry in entries[:limit]:
            title = self._text(entry, "title")
            link = self._link(entry, url)
            published = (
                self._text(entry, "pubDate")
                or self._text(entry, "published")
                or self._text(entry, "updated")
            )
            body = (
                self._text(entry, "description")
                or self._text(entry, "summary")
                or self._text(entry, "content")
            )
            if enrich and link and len(body) < 200:
                body = self._article_text(link) or body
            if not title or not published:
                continue
            items.append(
                MacroNewsItem(
                    source=source,
                    published_at=self._parse_datetime(published),
                    title=BeautifulSoup(title, "html.parser").get_text(" ", strip=True),
                    body=BeautifulSoup(body, "html.parser").get_text(" ", strip=True),
                    link=link,
                )
            )
        return items

    def _text(self, entry: ElementTree.Element, name: str) -> str:
        node = entry.find(name)
        if node is None:
            node = entry.find(f"{{*}}{name}")
        return "".join(node.itertext()).strip() if node is not None else ""

    def _link(self, entry: ElementTree.Element, base_url: str) -> str:
        node = entry.find("link")
        if node is None:
            node = entry.find("{*}link")
        if node is None:
            return ""
        value = node.get("href") or (node.text or "")
        return urljoin(base_url, value.strip())

    def _article_text(self, url: str) -> str:
        try:
            soup = BeautifulSoup(self.client.get_text(url), "html.parser")
        except Exception:
            return ""
        selectors = ("main p", "article p", ".content p", ".detail-content p")
        for selector in selectors:
            paragraphs = [
                node.get_text(" ", strip=True)
                for node in soup.select(selector)
                if node.get_text(" ", strip=True)
            ]
            if paragraphs:
                return " ".join(paragraphs)[:8000]
        return ""

    def _parse_datetime(self, value: str) -> datetime:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                parsed = self._parse_turkish_datetime(value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    def _parse_turkish_datetime(self, value: str) -> datetime:
        months = {
            "Oca": 1,
            "Şub": 2,
            "Sub": 2,
            "Mar": 3,
            "Nis": 4,
            "May": 5,
            "Haz": 6,
            "Tem": 7,
            "Ağu": 8,
            "Agu": 8,
            "Eyl": 9,
            "Eki": 10,
            "Kas": 11,
            "Ara": 12,
        }
        parts = value.split()
        if len(parts) < 4 or parts[1] not in months:
            raise ValueError(f"Unsupported feed date: {value}")
        hour, minute, second = (int(part) for part in parts[3].split(":"))
        return datetime(
            int(parts[2]),
            months[parts[1]],
            int(parts[0]),
            hour,
            minute,
            second,
        )
