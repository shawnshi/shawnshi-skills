from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path

from hub_utils import HISTORY_PATH, HUB_DIR, dump_json, load_json


LEGACY_PATHS = [
    HUB_DIR / "tmp" / "pushed_history_v2.json",
    HUB_DIR / "tmp" / "pushed_history.json",
]


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip().lower())
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff ]", "", text)
    return text


def generate_fingerprint(title: str, source: str) -> str:
    payload = f"{normalize_text(title)}|{normalize_text(source)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _load_entries() -> list[dict]:
    data = load_json(HISTORY_PATH, [])
    if data:
        return data
    for legacy in LEGACY_PATHS:
        legacy_data = load_json(legacy, [])
        if legacy_data:
            return legacy_data
    return []


def load_recent_history(days: int = 7) -> list[dict]:
    cutoff = datetime.now() - timedelta(days=days)
    entries = []
    for entry in _load_entries():
        ts = entry.get("timestamp")
        try:
            if ts and datetime.fromisoformat(ts) >= cutoff:
                entries.append(entry)
        except ValueError:
            continue
    return entries


def is_redundant(url: str, title: str, source: str, days: int = 7) -> bool:
    fingerprint = generate_fingerprint(title, source)
    for entry in load_recent_history(days=days):
        if entry.get("url") == url or entry.get("fingerprint") == fingerprint:
            return True
    return False


def save_history(urls: list[str], fingerprints: list[str]) -> None:
    entries = load_recent_history(days=30)
    timestamp = datetime.now().isoformat()
    for url, fingerprint in zip(urls, fingerprints):
        entries.append(
            {"url": url, "fingerprint": fingerprint, "timestamp": timestamp}
        )
    dump_json(HISTORY_PATH, entries)
