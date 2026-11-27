from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

from .http import HttpClient
from ..models import CompanyProfile


class KapUniverseFeed:
    def __init__(
        self,
        url: str = "https://www.kap.org.tr/tr/bist-sirketler",
        client: HttpClient | None = None,
    ) -> None:
        self.url = url
        self.client = client or HttpClient()

    def read_companies(self) -> list[CompanyProfile]:
        soup = BeautifulSoup(self.client.get_text(self.url), "html.parser")
        sector_map = self._sector_map()
        table = soup.find("table")
        if table is None:
            return []
        companies: dict[str, CompanyProfile] = {}
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) < 3:
                continue
            code_text = cells[0].get_text(" ", strip=True).upper()
            title = cells[1].get_text(" ", strip=True)
            city = cells[2].get_text(" ", strip=True)
            link = cells[0].find("a", href=True) or cells[1].find("a", href=True)
            permalink = str(link["href"]).rsplit("/", maxsplit=1)[-1] if link else ""
            for symbol in re.findall(r"\b[A-Z0-9]{4,6}\b", code_text):
                companies[symbol] = CompanyProfile(
                    symbol=symbol,
                    title=title,
                    city=city,
                    permalink=permalink,
                    sector=sector_map.get(symbol, ""),
                )
        return sorted(companies.values(), key=lambda item: item.symbol)

    def _sector_map(self) -> dict[str, str]:
        html = self.client.get_text("https://www.kap.org.tr/tr/Sektorler")
        matches = re.findall(
            r'\\"sectorName\\":\\"(.*?)\\".*?\\"stockCode\\":\\"(.*?)\\"',
            html,
        )
        return {
            symbol.upper(): self._clean_sector(sector)
            for sector, symbol in matches
        }

    def _clean_sector(self, value: str) -> str:
        translated = value.replace("�", "").translate(str.maketrans({"ı": "i", "ş": "s", "ğ": "g"}))
        return "".join(
            character
            for character in unicodedata.normalize("NFKD", translated)
            if not unicodedata.combining(character)
        ).strip()
