from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from .adapters.http import HttpClient


@dataclass(frozen=True)
class KapDocument:
    disclosure_index: int
    url: str
    text: str


class KapDocumentReader:
    """Reads public KAP disclosure detail pages without making them mandatory."""

    def __init__(
        self,
        client: HttpClient | None = None,
        base_url: str = "https://www.kap.org.tr",
    ) -> None:
        if client is None:
            from .adapters.http import HttpClient

            client = HttpClient(timeout_seconds=15, max_retries=2)
        self.client = client
        self.base_url = base_url.rstrip("/")

    def read(self, disclosure_index: int) -> KapDocument | None:
        if disclosure_index <= 0:
            return None
        url = f"{self.base_url}/tr/Bildirim/{disclosure_index}"
        try:
            html = self.client.get_text(url)
        except RuntimeError:
            return None
        text = extract_kap_document_text(html)
        for attachment_url in extract_kap_attachment_urls(html, url)[:1]:
            try:
                attachment_text = extract_pdf_text(self.client.get_bytes(attachment_url))
            except RuntimeError:
                continue
            if attachment_text:
                text = f"{text}\n\nEK DOSYA\n{attachment_text}".strip()
        if not text:
            return None
        return KapDocument(disclosure_index=disclosure_index, url=url, text=text)


def extract_kap_document_text(html: str, limit: int = 6_000) -> str:
    """Returns readable disclosure text while dropping scripts and navigation."""
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()
    candidates = soup.select(
        ".disclosure-content, .disclosureContent, .additional-explanation, "
        "[class*='additional'], [class*='explanation'], article, main"
    )
    raw_text = " ".join(
        candidate.get_text(" ", strip=True) for candidate in candidates
    ) if candidates else soup.get_text(" ", strip=True)
    normalized = re.sub(r"\s+", " ", raw_text).strip()
    return normalized[:limit] if len(normalized) >= 40 else ""


def extract_kap_attachment_urls(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if ".pdf" not in href.lower():
            continue
        url = urljoin(page_url, href)
        if url.startswith("https://www.kap.org.tr/") and url not in urls:
            urls.append(url)
    return urls


def extract_pdf_text(payload: bytes, limit: int = 6_000) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(BytesIO(payload))
        raw_text = " ".join((page.extract_text() or "") for page in reader.pages[:20])
    except Exception:
        return ""
    return re.sub(r"\s+", " ", raw_text).strip()[:limit]
