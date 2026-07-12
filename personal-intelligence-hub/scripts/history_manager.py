from __future__ import annotations

import hashlib
import re
import difflib
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from hub_utils import HISTORY_PATH, HUB_DIR, dump_json, load_json


LEGACY_PATHS = [
    HUB_DIR / "tmp" / "pushed_history_v2.json",
    HUB_DIR / "tmp" / "pushed_history.json",
]


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip().lower())
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff ]", "", text)
    return text


def normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        keys_to_remove = [k for k in qs.keys() if k.startswith('utm_') or k in ['ref', 'source', 'multitrack']]
        for k in keys_to_remove:
            del qs[k]
        new_query = urlencode(qs, doseq=True)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
    except Exception:
        return url


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
        if isinstance(entry, str):
            continue
        ts = entry.get("timestamp")
        try:
            if ts and datetime.fromisoformat(ts) >= cutoff:
                entries.append(entry)
        except ValueError:
            continue
    return entries


def is_redundant(url: str, title: str, source: str, days: int = 7) -> bool:
    norm_url = normalize_url(url)
    fingerprint = generate_fingerprint(title, source)
    norm_title = normalize_text(title)
    
    for entry in load_recent_history(days=days):
        entry_url = normalize_url(entry.get("url", ""))
        if entry_url and entry_url == norm_url:
            return True
        if entry.get("fingerprint") == fingerprint:
            return True
            
        entry_title = normalize_text(entry.get("title", ""))
        if entry_title and norm_title:
            similarity = difflib.SequenceMatcher(None, entry_title, norm_title).ratio()
            if similarity > 0.85:
                return True
                
    return False


def save_history(urls: list[str], fingerprints: list[str], titles: list[str] = None) -> None:
    entries = load_recent_history(days=30)
    timestamp = datetime.now().isoformat()
    if titles is None:
        titles = [""] * len(urls)
        
    for url, fingerprint, title in zip(urls, fingerprints, titles):
        entries.append(
            {"url": url, "fingerprint": fingerprint, "title": title, "timestamp": timestamp}
        )
    dump_json(HISTORY_PATH, entries)
