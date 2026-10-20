#!/usr/bin/env python3
"""Inventory IPA-like documents in Telegram channels without downloading the files."""
import argparse
import asyncio
import json
import os
import re
from collections import defaultdict
from datetime import timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.sessions import StringSession

IPA_SUFFIXES = (".ipa", ".ipa.zip")
IPA_WORD = re.compile(r"\\bipa\\b", re.IGNORECASE)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channels", required=True, help="Comma-separated Telegram usernames")
    parser.add_argument("--limit", type=int, default=10000, help="Messages to inspect per channel")
    parser.add_argument("--output", default="telegram-ipa-inventory.json")
    return parser.parse_args()


def get_file_info(message):
    if not message.document:
        return None, None, None
    file_obj = message.file
    name = (getattr(file_obj, "name", None) or "").strip()
    size = getattr(file_obj, "size", None)
    mime_type = getattr(file_obj, "mime_type", None)
    if not name:
        for attr in (message.document.attributes or []):
            candidate = getattr(attr, "file_name", None)
            if candidate:
                name = candidate.strip()
                break
    return name, size, mime_type


async def scan_channel(client, channel, limit):
    entity = await client.get_entity(channel)
    channel_title = getattr(entity, "title", None) or channel
    username = getattr(entity, "username", None)
    rows = []
    seen = 0

    async for message in client.iter_messages(entity, limit=limit, wait_time=1):
        seen += 1
        if not message.document:
            continue
        name, size, mime_type = get_file_info(message)
        caption = (message.message or "").strip()
        strict_match = bool(name and name.casefold().endswith(IPA_SUFFIXES))
        caption_match = bool(
            not strict_match and IPA_WORD.search(caption) and size and size >= 5 * 1024 * 1024
        )
        if not strict_match and not caption_match:
            continue

        post_url = f"https://t.me/{username}/{message.id}" if username else None
        rows.append({
            "channel": channel_title,
            "channel_username": username,
            "message_id": message.id,
            "post_url": post_url,
            "date": message.date.isoformat() if message.date else None,
            "filename": name or None,
            "size_bytes": size,
            "mime_type": mime_type,
            "match_type": "filename" if strict_match else "caption_heuristic",
            "needs_review": bool(caption_match),
            "caption_preview": caption[:180] if caption else None,
        })

    return {"channel": channel, "title": channel_title, "messages_inspected": seen, "items": rows}


async def main():
    args = parse_args()
    api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    session = os.environ.get("TELEGRAM_SESSION", "").strip()
    if not api_id or not api_hash or not session:
        raise SystemExit(
            "Missing GitHub secrets: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION."
        )
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1")

    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    if not channels:
        raise SystemExit("No Telegram channels supplied")

    all_rows = []
    channel_summaries = []
    errors = []

    async with TelegramClient(StringSession(session), int(api_id), api_hash) as client:
        if not await client.is_user_authorized():
            raise SystemExit(
                "TELEGRAM_SESSION is not authorized. Generate a new StringSession locally."
            )
        for channel in channels:
            normalized = channel if channel.startswith("@") else "@" + channel
            try:
                result = await scan_channel(client, normalized, args.limit)
                channel_summaries.append({
                    "channel": result["channel"],
                    "title": result["title"],
                    "messages_inspected": result["messages_inspected"],
                    "ipa_candidates": len(result["items"]),
                })
                all_rows.extend(result["items"])
                print(
                    f"Scanned {normalized}: {result['messages_inspected']} messages, "
                    f"{len(result['items'])} IPA candidates"
                )
            except FloodWaitError as exc:
                errors.append({"channel": normalized, "error": f"Telegram flood wait: {exc.seconds}s"})
                print(f"Telegram asked us to wait {exc.seconds}s for {normalized}; continuing.")
            except (RPCError, ValueError, TypeError) as exc:
                errors.append({"channel": normalized, "error": f"{type(exc).__name__}: {str(exc)[:240]}"})
                print(f"Could not scan {normalized}: {type(exc).__name__}: {str(exc)[:160]}")
            except Exception as exc:
                errors.append({"channel": normalized, "error": f"{type(exc).__name__}: {str(exc)[:240]}"})
                print(f"Could not scan {normalized}: {type(exc).__name__}: {str(exc)[:160]}")

    duplicate_groups = defaultdict(list)
    for index, item in enumerate(all_rows):
        key = (str(item.get("filename") or "").casefold(), item.get("size_bytes"))
        if key != ("", None):
            duplicate_groups[key].append(index)
    for indexes in duplicate_groups.values():
        if len(indexes) > 1:
            for index in indexes:
                all_rows[index]["duplicate_candidate"] = True
    for item in all_rows:
        item.setdefault("duplicate_candidate", False)

    total_bytes = sum(item.get("size_bytes") or 0 for item in all_rows)
    strict_count = sum(item["match_type"] == "filename" for item in all_rows)
    heuristic_count = len(all_rows) - strict_count
    unique_name_size = len(duplicate_groups)
    report = {
        "schema_version": 1,
        "generated_at": __import__("datetime").datetime.now(timezone.utc).isoformat(),
        "mode": "metadata_inventory_only_no_ipa_downloads",
        "channels": channels,
        "messages_limit_per_channel": args.limit,
        "summary": {
            "channels_requested": len(channels),
            "channels_scanned": len(channel_summaries),
            "messages_inspected": sum(x["messages_inspected"] for x in channel_summaries),
            "ipa_candidates": len(all_rows),
            "filename_matches": strict_count,
            "caption_heuristic_candidates_review_required": heuristic_count,
            "unique_filename_size_pairs": unique_name_size,
            "duplicate_candidates_by_filename_and_size": len(all_rows) - unique_name_size,
            "total_candidate_size_bytes": total_bytes,
        },
        "channel_summaries": channel_summaries,
        "errors": errors,
        "items": all_rows,
    }
    output = Path(args.output)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    print("\\nInventory summary:")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Saved inventory to {output}")


if __name__ == "__main__":
    asyncio.run(main())
