from __future__ import annotations

import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def request_json(request: str | Request, stage: str) -> tuple[int, dict]:
    if isinstance(request, str):
        request = Request(request)
    request.add_header("User-Agent", "BIST-Radar-Setup/1.0")
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                return response.status, json.load(response) if response.status != 204 else {}
        except HTTPError as error:
            if attempt < 2 and (error.code == 429 or error.code >= 500):
                time.sleep(3 * (attempt + 1))
                continue
            raise SystemExit(f"{stage} failed (HTTP {error.code}).") from None
        except (URLError, TimeoutError):
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise SystemExit(f"{stage} failed (network or TLS connection).") from None
        except ValueError:
            raise SystemExit(f"{stage} returned an invalid response.") from None
    raise SystemExit(f"{stage} failed.")


def verify_public_menus(base_url: str, secret: str) -> None:
    commands = ("/komutlar", "/sektor", "/portfoy", "/portfoy dengeli", "/portfoy kalite", "/portfoy buyume")
    for command in commands:
        for attempt in range(6):
            request = Request(base_url + "/telegram", data=json.dumps({"message": {
                "chat": {"id": 1, "type": "private"}, "from": {"id": 1}, "text": command,
            }}).encode(), headers={"Content-Type": "application/json",
                "X-Telegram-Bot-Api-Secret-Token": secret})
            status, reply = request_json(request, "Published menu verification")
            valid = (
                status == 200 and reply.get("method") == "sendMessage"
                and 0 < len(reply.get("text", "")) <= 4096
                and bool(reply.get("reply_markup", {}).get("inline_keyboard"))
            )
            if valid:
                print(f"Verified {command} with inline buttons ({len(reply['text'])} characters).")
                break
            if attempt == 5:
                raise SystemExit(f"Published menu verification failed for {command} (HTTP {status}).")
            time.sleep(5)
    print("Six published menu and portfolio responses verified without sending Telegram messages.")


def main() -> None:
    base_url = os.environ.get("PUBLIC_BOT_WORKER_URL", "").rstrip("/")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    parsed = urlsplit(base_url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https" or parsed.netloc != host
        or not host.endswith(".workers.dev") or parsed.path or parsed.query or parsed.fragment
    ):
        raise SystemExit("PUBLIC_BOT_WORKER_URL must be the deployed https://...workers.dev origin.")
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise SystemExit("Set a valid TELEGRAM_BOT_TOKEN secret before activation.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", secret):
        raise SystemExit("Set a random TELEGRAM_WEBHOOK_SECRET of 32–256 allowed characters.")

    _, identity = request_json(f"https://api.telegram.org/bot{token}/getMe", "Telegram token verification")
    if not identity.get("ok") or not identity.get("result", {}).get("is_bot"):
        raise SystemExit("Telegram token verification failed.")
    _, health = request_json(f"{base_url}/health", "Worker health check")
    if not health.get("ready"):
        raise SystemExit("The deployed Worker has not loaded its public reports.")
    probe = Request(
            f"{base_url}/telegram",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-Telegram-Bot-Api-Secret-Token": secret,
            },
        )
    status, _ = request_json(probe, "Worker webhook secret verification")
    if status != 204:
        raise SystemExit("The Worker did not accept the webhook secret.")
    verify_public_menus(base_url, secret)
    request = Request(
            f"https://api.telegram.org/bot{token}/setWebhook",
            data=json.dumps({
                "url": f"{base_url}/telegram",
                "secret_token": secret,
                "allowed_updates": ["message", "callback_query"],
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
    _, registration = request_json(request, "Telegram webhook registration")
    if not registration.get("ok"):
        raise SystemExit("Telegram rejected the webhook registration.")
    _, verification = request_json(
        f"https://api.telegram.org/bot{token}/getWebhookInfo", "Telegram webhook verification"
    )
    if not verification.get("ok") or verification.get("result", {}).get("url") != f"{base_url}/telegram":
        raise SystemExit("Telegram webhook URL verification failed.")
    if not {"message", "callback_query"}.issubset(verification["result"].get("allowed_updates", [])):
        raise SystemExit("Telegram webhook is not subscribed to message and button updates.")
    print("Telegram webhook is configured.")
    username = identity["result"].get("username", "")
    if re.fullmatch(r"[A-Za-z0-9_]+", username):
        print(f"Public bot: https://t.me/{username}")


if __name__ == "__main__":
    main()
