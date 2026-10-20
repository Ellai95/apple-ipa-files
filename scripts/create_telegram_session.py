#!/usr/bin/env python3
"""Create a Telegram Telethon StringSession locally, once, for GitHub Actions.

Run locally only. Never commit or share the printed session string.
"""
import os
from urllib.parse import urlsplit, unquote
from telethon import TelegramClient
from telethon.sessions import StringSession


def get_proxy():
    """Optional local HTTP CONNECT or SOCKS proxy from environment variable."""
    raw = os.environ.get("TELEGRAM_PROXY_URL", "").strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "socks5", "socks4"):
        raise SystemExit("Proxy URL must start with http://, socks5:// or socks4://")
    if not parts.hostname or not parts.port:
        raise SystemExit("Proxy URL must contain host and port")
    proxy = {
        "proxy_type": scheme,
        "addr": parts.hostname,
        "port": parts.port,
        "rdns": True,
    }
    if parts.username:
        proxy["username"] = unquote(parts.username)
    if parts.password:
        proxy["password"] = unquote(parts.password)
    return proxy


def main():
    api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    if not api_id or not api_hash:
        raise SystemExit(
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH as environment variables first."
        )

    proxy = get_proxy()
    if proxy:
        print("Connecting through local proxy:", proxy["proxy_type"], proxy["addr"], proxy["port"])
    with TelegramClient(
        StringSession(), int(api_id), api_hash, proxy=proxy, timeout=12,
        connection_retries=2,
    ) as client:
        client.start()
        print("\nLogin successful. Copy this value into the GitHub secret TELEGRAM_SESSION.")
        print("Keep it private: it grants access to your Telegram account.")
        print(client.session.save())


if __name__ == "__main__":
    main()
