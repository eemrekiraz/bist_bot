from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from bist_ai_radar.public_worker_register import main, request_json, verify_public_menus


class PublicWorkerRegisterTests(unittest.TestCase):
    def test_menu_verification_waits_for_new_edge_version(self) -> None:
        old = (200, {"method": "sendMessage", "text": "Old menu"})
        current = (200, {"method": "sendMessage", "text": "New menu",
                         "reply_markup": {"inline_keyboard": [[{"text": "Finans"}]]}})
        with patch("bist_ai_radar.public_worker_register.request_json", side_effect=[old, *([current] * 6)]) as request, patch(
            "bist_ai_radar.public_worker_register.time.sleep"
        ) as sleep, patch("sys.stdout", new_callable=io.StringIO):
            verify_public_menus("https://example.test.workers.dev", "secret")
            self.assertEqual(request.call_count, 7)
            sleep.assert_called_once_with(5)

    def test_menu_verification_rejects_oversized_replies(self) -> None:
        oversized = (200, {"method": "sendMessage", "text": "x" * 4097,
                           "reply_markup": {"inline_keyboard": [[{"text": "Finans"}]]}})
        with patch("bist_ai_radar.public_worker_register.request_json", return_value=oversized) as request, patch(
            "bist_ai_radar.public_worker_register.time.sleep"
        ):
            with self.assertRaisesRegex(SystemExit, "failed for /komutlar"):
                verify_public_menus("https://example.test.workers.dev", "secret")
            self.assertEqual(request.call_count, 6)

    def test_requests_identify_the_application(self) -> None:
        for original in ("https://example.test", Request("https://example.test", data=b"{}")):
            response = io.BytesIO(b'{"ok":true}')
            response.status = 200
            with patch("bist_ai_radar.public_worker_register.urlopen", return_value=response) as fetch:
                self.assertEqual(request_json(original, "Check"), (200, {"ok": True}))
                self.assertEqual(fetch.call_args.args[0].get_header("User-agent"), "BIST-Radar-Setup/1.0")

    def test_unauthorized_error_does_not_expose_token_or_retry(self) -> None:
        error = HTTPError("https://example.test/private-token", 401, "private-token", {}, None)
        with patch("bist_ai_radar.public_worker_register.urlopen", side_effect=error), patch(
            "bist_ai_radar.public_worker_register.time.sleep"
        ) as sleep:
            with self.assertRaises(SystemExit) as result:
                request_json("https://example.test", "Telegram verification")
            self.assertEqual(str(result.exception), "Telegram verification failed (HTTP 401).")
            sleep.assert_not_called()

    def test_network_failure_retries_with_safe_message(self) -> None:
        with patch("bist_ai_radar.public_worker_register.urlopen", side_effect=URLError("secret")) as fetch, patch(
            "bist_ai_radar.public_worker_register.time.sleep"
        ):
            with self.assertRaisesRegex(SystemExit, "Worker check failed \\(network or TLS connection\\)."):
                request_json("https://example.test", "Worker check")
            self.assertEqual(fetch.call_count, 3)

    def test_registration_verifies_actual_webhook(self) -> None:
        base_url = "https://example.test.workers.dev"
        with patch.dict("os.environ", {
            "PUBLIC_BOT_WORKER_URL": base_url,
            "TELEGRAM_BOT_TOKEN": "123:mock_token",
            "TELEGRAM_WEBHOOK_SECRET": "a" * 40,
        }), patch("bist_ai_radar.public_worker_register.request_json", side_effect=[
            (200, {"ok": True, "result": {"is_bot": True, "username": "mock_bot"}}),
            (200, {"ready": True}),
            (204, {}),
            (200, {"ok": True}),
            (200, {"ok": True, "result": {"url": base_url + "/telegram", "allowed_updates": ["message", "callback_query"]}}),
        ]) as request, patch("bist_ai_radar.public_worker_register.verify_public_menus"), patch("sys.stdout", new_callable=io.StringIO) as output:
            main()
            self.assertIn("Telegram webhook is configured.", output.getvalue())
            self.assertIn("https://t.me/mock_bot", output.getvalue())
            registration = json.loads(request.call_args_list[3].args[0].data)
            self.assertEqual(registration["allowed_updates"], ["message", "callback_query"])


if __name__ == "__main__":
    unittest.main()
