#!/usr/bin/env python3
"""Create a Telegram Telethon StringSession locally, once, for GitHub Actions.

Run locally only. Never commit or share the printed session string.
"""
import os
from telethon import TelegramClient
from telethon.sessions import StringSession


def main():
    api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    if not api_id or not api_hash:
        raise SystemExit(
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH as environment variables first."
        )

    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        client.start()
        print("\nLogin successful. Copy this value into the GitHub secret TELEGRAM_SESSION.")
        print("Keep it private: it grants access to your Telegram account.")
        print(client.session.save())


if __name__ == "__main__":
    main()
