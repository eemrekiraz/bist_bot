from __future__ import annotations

import unittest
from http.client import IncompleteRead
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from bist_ai_radar.adapters.http import HttpClient


class HttpClientTests(unittest.TestCase):
    @patch("bist_ai_radar.adapters.http.time.sleep")
    @patch("bist_ai_radar.adapters.http.build_opener")
    def test_retries_session_request_after_network_error(self, build_opener, sleeper) -> None:
        first = MagicMock()
        first.open.side_effect = [MagicMock(), URLError("temporary")]
        start_response = MagicMock()
        start_response.__enter__.return_value = start_response
        start_response.__exit__.return_value = False
        first.open.side_effect = [start_response, URLError("temporary")]

        second = MagicMock()
        retry_start = MagicMock()
        retry_start.__enter__.return_value = retry_start
        retry_start.__exit__.return_value = False
        payload = MagicMock()
        payload.read.return_value = b'{"ok": true}'
        payload.__enter__.return_value = payload
        payload.__exit__.return_value = False
        second.open.side_effect = [retry_start, payload]
        build_opener.side_effect = [first, second]

        result = HttpClient(max_retries=1).get_session_json(
            "https://example.test/start",
            "https://example.test/data",
        )

        self.assertEqual(result, {"ok": True})
        sleeper.assert_called_once_with(1)

    @patch("bist_ai_radar.adapters.http.build_opener")
    def test_reads_text_with_primed_session(self, build_opener) -> None:
        opener = MagicMock()
        start_response = MagicMock()
        start_response.__enter__.return_value = start_response
        start_response.__exit__.return_value = False
        payload = MagicMock()
        payload.read.return_value = "oturum tamam".encode("utf-8")
        payload.__enter__.return_value = payload
        payload.__exit__.return_value = False
        opener.open.side_effect = [start_response, payload]
        build_opener.return_value = opener

        result = HttpClient().get_session_text(
            "https://example.test/start",
            "https://example.test/page",
        )

        self.assertEqual(result, "oturum tamam")
        self.assertEqual(opener.open.call_count, 2)

    @patch("bist_ai_radar.adapters.http.time.sleep")
    @patch("bist_ai_radar.adapters.http.build_opener")
    def test_retries_incomplete_session_response(self, build_opener, sleeper) -> None:
        failed_start = MagicMock()
        failed_start.__enter__.return_value = failed_start
        failed_start.__exit__.return_value = False
        incomplete = MagicMock()
        incomplete.__enter__.return_value = incomplete
        incomplete.__exit__.return_value = False
        incomplete.read.side_effect = IncompleteRead(b"partial")
        failed = MagicMock()
        failed.open.side_effect = [failed_start, incomplete]

        retry_start = MagicMock()
        retry_start.__enter__.return_value = retry_start
        retry_start.__exit__.return_value = False
        complete = MagicMock()
        complete.__enter__.return_value = complete
        complete.__exit__.return_value = False
        complete.read.return_value = b"complete"
        recovered = MagicMock()
        recovered.open.side_effect = [retry_start, complete]
        build_opener.side_effect = [failed, recovered]

        result = HttpClient(max_retries=1).get_session_text(
            "https://example.test/start",
            "https://example.test/page",
        )

        self.assertEqual(result, "complete")
        sleeper.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
