from __future__ import annotations

import json
import time
from dataclasses import dataclass
from http.cookiejar import CookieJar
from http.client import IncompleteRead, RemoteDisconnected
from urllib.error import HTTPError, URLError
from typing import Any
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


@dataclass(frozen=True)
class HttpClient:
    timeout_seconds: int = 20
    user_agent: str = "bist-ai-radar/0.1"
    max_retries: int = 4

    def get_json(self, url: str) -> Any:
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Accept-Language": "tr",
            },
        )
        return self._send_json(request, url)

    def get_text(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Language": "tr",
            },
        )
        return self._send(request, url)

    def get_bytes(self, url: str) -> bytes:
        request = Request(url, headers={"User-Agent": self.user_agent})
        return self._send_bytes(request, url)

    def post_json(self, url: str, body: dict[str, Any]) -> Any:
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Accept-Language": "tr",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return self._send_json(request, url)

    def get_session_json(self, start_url: str, url: str) -> Any:
        return json.loads(self.get_session_text(start_url, url))

    def get_session_text(self, start_url: str, url: str) -> str:
        common_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/149.0 Safari/537.36"
            ),
            "Accept-Language": "tr",
        }
        for attempt in range(self.max_retries + 1):
            try:
                opener = build_opener(HTTPCookieProcessor(CookieJar()))
                with opener.open(
                    Request(start_url, headers=common_headers),
                    timeout=self.timeout_seconds,
                ):
                    pass
                request = Request(
                    url,
                    headers={
                        **common_headers,
                        "Accept": "application/json, text/plain, */*",
                        "Referer": start_url,
                        "X-Requested-With": "XMLHttpRequest",
                    },
                )
                with opener.open(request, timeout=self.timeout_seconds) as response:
                    return self._decode(response.read())
            except HTTPError as error:
                if error.code not in (429, 502, 503, 504) or attempt == self.max_retries:
                    raise RuntimeError(f"HTTP {error.code} while fetching {url}") from error
                retry_after = error.headers.get("Retry-After") if error.headers else None
                wait_seconds = float(retry_after) if retry_after else 2 ** (attempt + 1)
                time.sleep(min(wait_seconds, 30))
            except (
                URLError,
                TimeoutError,
                ConnectionError,
                IncompleteRead,
                RemoteDisconnected,
                OSError,
            ) as error:
                if attempt == self.max_retries:
                    raise RuntimeError(
                        f"Network error while fetching {url}: "
                        f"{getattr(error, 'reason', error)}"
                    ) from error
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Session request exhausted retries for {url}")

    def _send_json(self, request: Request, url: str) -> Any:
        return json.loads(self._send(request, url))

    def _send(self, request: Request, url: str) -> str:
        return self._decode(self._send_bytes(request, url))

    def _send_bytes(self, request: Request, url: str) -> bytes:
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    raw_payload = response.read()
                break
            except HTTPError as error:
                if error.code not in (429, 502, 503, 504) or attempt == self.max_retries:
                    raise RuntimeError(f"HTTP {error.code} while fetching {url}") from error
                retry_after = error.headers.get("Retry-After")
                wait_seconds = float(retry_after) if retry_after else 2 ** (attempt + 1)
                time.sleep(min(wait_seconds, 30))
            except (
                URLError,
                TimeoutError,
                ConnectionError,
                IncompleteRead,
                RemoteDisconnected,
                OSError,
            ) as error:
                if attempt == self.max_retries:
                    raise RuntimeError(
                        f"Network error while fetching {url}: "
                        f"{getattr(error, 'reason', error)}"
                    ) from error
                time.sleep(2 ** attempt)
        return raw_payload

    def _decode(self, payload: bytes) -> str:
        for encoding in ("utf-8", "iso-8859-9", "cp1254"):
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError:
                continue
        return payload.decode("utf-8", errors="replace")
