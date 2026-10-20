"""Extract clean AppStore+ titles and comparable versions from Telegram IPA names.

This file only normalizes catalog metadata; it never rewrites the IPA payload.
"""
import re
import unicodedata


ADVERTISING = (
    r"(?i)(?:https?://)?t\.me/[A-Za-z0-9_]+(?:/\d+)?",
    r"(?i)(?:tg\s*[@:_-]\s*|@)[A-Za-z][A-Za-z0-9_]{2,}",
    r"(?i)\b(?:KamoHacks|AppAssassin|IAppsBestLibrary|privateipa|unlimipa|islamusamanov)\b",
)
TIMESTAMP = re.compile(r"(?<!\d)[17-21]\d{8}(?!\d)")
VERSION_TRAILING = re.compile(
    r"(?i)(?:[-\s_\[(]|^)(?:v(?:er(?:sion)?)?\.?\s*)?"
    r"(\d{1,4}(?:[._]\d{1,5}){1,5})(?:[\s_\])\-]|$)"
)


def version_tuple(value):
    if not value:
        return ()
    nums = re.findall(r"\d+", str(value))
    if not nums or len(nums) > 7:
        return ()
    return tuple(int(x) for x in nums)


def compare_versions(left, right):
    """Return -1, 0 or +1. Unknown versions are never treated as newer."""
    a, b = version_tuple(left), version_tuple(right)
    if not a or not b:
        return 0
    count = max(len(a), len(b))
    a = a + (0,) * (count - len(a))
    b = b + (0,) * (count - len(b))
    return (a > b) - (a < b)


def clean_title(filename):
    name = unicodedata.normalize("NFKC", (filename or "").strip())
    name = re.sub(r"(?i)\.ipa(?:\.zip)?$", "", name)
    for pattern in ADVERTISING:
        name = re.sub(pattern, " ", name)
    # Post timestamps and publishing-service suffixes are not app titles.
    name = TIMESTAMP.sub(" ", name)
    name = re.sub(r"(?i)\b(?:patched|cracked|uploaded\s*by|repack)\b", " ", name)
    # Remove explicit bracketed version and version-like trailing tokens only.
    name = re.sub(r"(?i)[\[(]\s*v?\d+(?:[._]\d+){1,5}\s*[\])]", " ", name)
    name = re.sub(r"(?i)(?:[-_ ]+|\s+)v?\d+(?:[._]\d+){1,5}\s*$", "", name)
    name = re.sub(r"[_]+", " ", name)
    name = re.sub(r"\s*[-–—]\s*", " - ", name)
    name = re.sub(r"[\[\]()]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" ._-–—")
    return name or "Unnamed application"


def filename_version(filename):
    name = unicodedata.normalize("NFKC", filename or "")
    name = re.sub(r"(?i)\.ipa(?:\.zip)?$", "", name)
    for pattern in ADVERTISING:
        name = re.sub(pattern, " ", name)
    name = TIMESTAMP.sub(" ", name)
    versions = VERSION_TRAILING.findall(name)
    return versions[-1].replace("_", ".") if versions else ""


def catalog_key(title):
    return re.sub(r"[^\w]+", "-", unicodedata.normalize("NFKC", title).casefold()).strip("-")


def choose_latest_candidates(rows, index_apps, max_size=1_900_000_000):
    """Choose one most likely latest post per normalized title.

    Filename versions are just ordering hints; the actual IPA Info.plist
    version is verified on download before uploading.
    """
    best = {}
    counts = {"scanned": 0, "over_size": 0, "duplicates": 0}
    for entry in rows:
        counts["scanned"] += 1
        filename = (entry.get("filename") or "").strip()
        size = int(entry.get("size_bytes") or 0)
        if (entry.get("match_type") != "filename"
                or not filename.lower().endswith(".ipa")
                or not 0 < size <= max_size):
            counts["over_size"] += 1
            continue
        channel = entry.get("channel_username")
        if not channel or not entry.get("message_id"):
            continue
        title = clean_title(filename)
        key = catalog_key(title)
        version = filename_version(filename)
        stored = index_apps.get(key)
        if stored and version and stored.get("version"):
            if compare_versions(version, stored["version"]) <= 0:
                continue
        proposed = {**entry, "clean_title": title, "app_key": key,
                    "filename_version": version}
        previous = best.get(key)
        if previous is not None:
            counts["duplicates"] += 1
            a, b = version_tuple(version), version_tuple(previous["filename_version"])
            # Prefer a known newer version, or most recent post as tiebreaker.
            if a and b and compare_versions(version, previous["filename_version"]) != 0:
                if compare_versions(version, previous["filename_version"]) > 0:
                    best[key] = proposed
            elif (proposed.get("date") or "") > (previous.get("date") or ""):
                best[key] = proposed
        else:
            best[key] = proposed
    return list(best.values()), counts
