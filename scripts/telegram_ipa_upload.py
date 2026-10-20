#!/usr/bin/env python3
"""Transfer a small authorized IPA pilot from Telegram to GitHub Releases.

Does not download IPA files to the user's PC. Runs inside GitHub Actions.
Only source message URLs explicitly listed by the user are processed.
"""
import argparse
import asyncio
import hashlib
import http.client
import json
import os
from pathlib import Path
import plistlib
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from telethon import TelegramClient
from telethon.sessions import StringSession

GITHUB_API = "https://api.github.com"
MAX_FILE_BYTES = 1_900_000_000
TAG = "telegram-ipa-pilot"
GITHUB_VERSION = "2022-11-28"


def github_request(repo, token, path, payload=None, method=None):
    url = GITHUB_API + "/repos/" + repo + path
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method or ("POST" if body is not None else "GET"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": GITHUB_VERSION,
            "User-Agent": "apple-ipa-telegram-transfer",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def get_or_create_release(repo, token):
    try:
        return github_request(repo, token, "/releases/tags/" + TAG)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    return github_request(repo, token, "/releases", {
        "tag_name": TAG,
        "target_commitish": "main",
        "name": "Telegram IPA pilot (authorized files only)",
        "body": "Small manual transfer test. Only upload files with distribution rights.",
        "draft": False,
        "prerelease": True,
    })


def list_release_assets(repo, token, release_id):
    assets = []
    for page in range(1, 31):
        rows = github_request(
            repo, token, f"/releases/{release_id}/assets?per_page=100&page={page}"
        )
        assets.extend(rows)
        if len(rows) < 100:
            break
    return assets


def parse_sources(raw):
    urls = re.split(r"[,\s]+", raw.strip())
    rows = []
    for url in urls:
        if not url:
            continue
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ("t.me", "telegram.me"):
            raise ValueError("Use full https://t.me/channel/message_id links only")
        match = re.fullmatch(r"/([A-Za-z0-9_]{5,32})/(\d+)/?", parsed.path)
        if not match:
            raise ValueError("Invalid public channel post link: " + url[:150])
        rows.append((match.group(1), int(match.group(2)), url))
    if not rows or len(rows) > 5:
        raise ValueError("Provide 1 to 5 Telegram post URLs per pilot run")
    return list(dict.fromkeys(rows))


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_ipa(path):
    with zipfile.ZipFile(path) as archive:
        info = next(
            (
                entry for entry in archive.infolist()
                if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", entry.filename)
            ),
            None,
        )
        if info is None or info.file_size > 2 * 1024 * 1024:
            raise ValueError("IPA does not contain a plausible Payload/*.app/Info.plist")
        metadata = plistlib.loads(archive.read(info))
    bundle_id = metadata.get("CFBundleIdentifier")
    version = metadata.get("CFBundleShortVersionString") or metadata.get("CFBundleVersion")
    if not isinstance(bundle_id, str) or not bundle_id:
        raise ValueError("IPA is missing CFBundleIdentifier")
    return {"bundle_id": bundle_id, "version": str(version or "unknown")}


def upload_asset(repo, token, release_id, path, asset_name):
    quoted = urllib.parse.quote(asset_name, safe="")
    conn = http.client.HTTPSConnection("uploads.github.com", timeout=180)
    size = path.stat().st_size
    try:
        conn.putrequest(
            "POST",
            f"/repos/{repo}/releases/{release_id}/assets?name={quoted}",
        )
        conn.putheader("Authorization", "Bearer " + token)
        conn.putheader("Accept", "application/vnd.github+json")
        conn.putheader("X-GitHub-Api-Version", GITHUB_VERSION)
        conn.putheader("User-Agent", "apple-ipa-telegram-transfer")
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Content-Length", str(size))
        conn.endheaders()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                conn.send(chunk)
        response = conn.getresponse()
        data = response.read()
        if response.status != 201:
            raise RuntimeError(
                f"GitHub asset upload returned HTTP {response.status}: "
                + data[:350].decode("utf-8", errors="replace")
            )
        asset = json.loads(data)
        if asset.get("state") != "uploaded" or asset.get("size") != size:
            raise RuntimeError("GitHub asset state or size did not match uploaded file")
        return asset
    finally:
        conn.close()


async def transfer(args):
    api_id = os.environ["TELEGRAM_API_ID"].strip()
    api_hash = os.environ["TELEGRAM_API_HASH"].strip()
    session = os.environ["TELEGRAM_SESSION"].strip()
    token = os.environ["GH_TOKEN"].strip()
    repo = os.environ["GITHUB_REPOSITORY"].strip()

    sources = parse_sources(args.urls)
    release = get_or_create_release(repo, token)
    assets = list_release_assets(repo, token, release["id"])
    existing = {asset["name"]: asset for asset in assets if asset.get("state") == "uploaded"}
    report = {"release_tag": TAG, "items": [], "errors": []}

    async with TelegramClient(StringSession(session), int(api_id), api_hash) as client:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session not authorized")
        for channel, message_id, source_url in sources:
            prefix = f"tg-{channel.lower()}-{message_id}-"
            if any(name.startswith(prefix) for name in existing):
                existing_asset = next(v for k, v in existing.items() if k.startswith(prefix))
                report["items"].append({
                    "source": source_url,
                    "status": "already_uploaded",
                    "download_url": existing_asset.get("browser_download_url"),
                })
                print(f"Already in GitHub Releases: {source_url}")
                continue
            try:
                entity = await client.get_entity(channel)
                message = await client.get_messages(entity, ids=message_id)
                if message is None or message.document is None:
                    raise ValueError("Telegram post has no downloadable document")
                original_name = (getattr(message.file, "name", None) or "").strip()
                if not original_name.lower().endswith(".ipa"):
                    raise ValueError("Telegram document filename does not end with .ipa")
                original_size = getattr(message.file, "size", None)
                if not original_size or original_size > MAX_FILE_BYTES:
                    raise ValueError("IPA must be nonempty and smaller than 1.9 GB")
                with tempfile.TemporaryDirectory(prefix="telegram-ipa-") as tmp:
                    target = Path(tmp) / "source.ipa"
                    print(f"Downloading from Telegram in GitHub runner: {source_url}")
                    await client.download_media(message, file=str(target))
                    if not target.is_file() or target.stat().st_size != original_size:
                        raise RuntimeError("Telegram download size mismatch")
                    ipa_metadata = validate_ipa(target)
                    digest = sha256_file(target)
                    name = prefix + digest[:12] + ".ipa"
                    if name in existing:
                        asset = existing[name]
                    else:
                        print(f"Uploading {name} ({original_size} bytes) to GitHub Releases")
                        asset = await asyncio.to_thread(
                            upload_asset, repo, token, release["id"], target, name
                        )
                    if asset.get("digest") and asset["digest"] != "sha256:" + digest:
                        raise RuntimeError("GitHub SHA-256 digest mismatch")
                    report["items"].append({
                        "source": source_url, "status": "uploaded",
                        "filename": original_name, "size_bytes": original_size,
                        "sha256": digest, "bundle_id": ipa_metadata["bundle_id"],
                        "version": ipa_metadata["version"],
                        "download_url": asset.get("browser_download_url"),
                    })
                    existing[name] = asset
                    print(f"Uploaded: {name}")
            except Exception as exc:
                message_text = f"{type(exc).__name__}: {str(exc)[:240]}"
                report["errors"].append({"source": source_url, "error": message_text})
                print(f"Could not transfer {source_url}: {message_text}")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls", required=True, help="Comma/space-separated t.me public post URLs")
    parser.add_argument("--output", default="telegram-ipa-transfer-report.json")
    args = parser.parse_args()

    for key in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION", "GH_TOKEN", "GITHUB_REPOSITORY"):
        if not os.environ.get(key, "").strip():
            raise SystemExit("Missing required environment variable: " + key)
    report = asyncio.run(transfer(args))
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Pilot done: {len(report['items'])} handled; {len(report['errors'])} errors")
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
