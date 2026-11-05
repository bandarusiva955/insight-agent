"""Alert delivery. Telegram when configured, otherwise the console.

Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable Telegram. Sending never
raises: a broken alert channel must not break the app.
"""

import json
import os
import urllib.request

TELEGRAM_TIMEOUT_SECONDS = 8


def send_alert(message: str) -> str:
    """Deliver an alert and return the channel used ("telegram" or "console")."""

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if token and chat_id:
        try:
            request = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=json.dumps({"chat_id": chat_id, "text": message}).encode(),
                headers={"Content-Type": "application/json"},
            )

            with urllib.request.urlopen(
                request, timeout=TELEGRAM_TIMEOUT_SECONDS
            ):
                return "telegram"

        except Exception as error:
            print(f"Telegram alert failed ({type(error).__name__}).", flush=True)

    print(f"ALERT: {message}", flush=True)

    return "console"
