from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from hub_utils import HISTORY_PATH, HUB_DIR, atomic_dump_json, load_json


HISTORY_SCHEMA_VERSION = "2.0"
LEGACY_PATHS = [
    HUB_DIR / "tmp" / "pushed_history_v2.json",
    HUB_DIR / "tmp" / "pushed_history.json",
]
TRACKING_QUERY_KEYS = {
    "ref",
    "source",
    "multitrack",
    "fbclid",
    "gclid",
}


def _identity_text(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", str(value or "")).strip().lower(),
    )


def normalize_text(text: str) -> str:
    normalized = _identity_text(text)
    return re.sub(r"[^a-z0-9\u4e00-\u9fff ]", "", normalized)


def normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(str(url).strip())
        query = sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in TRACKING_QUERY_KEYS
        )
        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path,
                parsed.params,
                urlencode(query, doseq=True),
                "",
            )
        )
    except (TypeError, ValueError):
        return str(url)


def generate_fingerprint(title: str, source: str) -> str:
    payload = f"{normalize_text(title)}|{normalize_text(source)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def generate_event_id(identity: dict[str, Any]) -> str:
    required = ("primary_domain", "actor", "action", "object", "event_date")
    values = [_identity_text(identity.get(field, "")) for field in required]
    if any(not value or value == "unknown" for value in values):
        raise ValueError(
            "semantic event identity requires domain, actor, action, object and event_date"
        )
    key_version = str(identity.get("key_version") or "1")
    payload = "|".join([f"event-v{key_version}", *values])
    return "evt1_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_content_id(url: str, title: str, source: str) -> str:
    payload = "|".join(
        ["content-v1", normalize_url(url), normalize_text(title), normalize_text(source)]
    )
    return "cnt1_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _legacy_entry(
    *,
    url: str = "",
    fingerprint: str = "",
    title: str = "",
    source: str = "",
    timestamp: str = "",
    identity_quality: str = "legacy_url",
) -> dict[str, Any]:
    canonical_url = normalize_url(url)
    identifier = generate_content_id(canonical_url, title, source or fingerprint)
    return {
        "event_id": identifier,
        "event_identity": None,
        "identity_quality": identity_quality,
        "canonical_url": canonical_url,
        "urls": [canonical_url] if canonical_url else [],
        "title": title,
        "source": source,
        "fingerprints": [fingerprint] if fingerprint else [],
        "first_seen_at": timestamp,
        "last_seen_at": timestamp,
        "archive_refs": [],
    }


def _coerce_history_entries(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and data.get("schema_version") == HISTORY_SCHEMA_VERSION:
        entries = data.get("entries")
        return [deepcopy(entry) for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []
    if isinstance(data, list):
        converted: list[dict[str, Any]] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            if "canonical_url" in entry or "event_id" in entry:
                converted.append(deepcopy(entry))
                continue
            converted.append(
                _legacy_entry(
                    url=str(entry.get("url") or ""),
                    fingerprint=str(entry.get("fingerprint") or ""),
                    title=str(entry.get("title") or ""),
                    source=str(entry.get("source") or ""),
                    timestamp=str(entry.get("timestamp") or ""),
                    identity_quality="legacy_entry",
                )
            )
        return converted
    if isinstance(data, dict) and ("urls" in data or "fingerprints" in data):
        converted = []
        urls = data.get("urls") or {}
        if isinstance(urls, dict):
            for url, timestamp in urls.items():
                converted.append(
                    _legacy_entry(
                        url=str(url),
                        timestamp=str(timestamp or ""),
                        identity_quality="legacy_url",
                    )
                )
        fingerprints = data.get("fingerprints") or {}
        if isinstance(fingerprints, dict):
            for fingerprint, timestamp in fingerprints.items():
                converted.append(
                    _legacy_entry(
                        fingerprint=str(fingerprint),
                        timestamp=str(timestamp or ""),
                        identity_quality="legacy_title",
                    )
                )
        return converted
    if isinstance(data, dict):
        converted = []
        for url, timestamp in data.items():
            if str(url).startswith(("http://", "https://")):
                converted.append(
                    _legacy_entry(
                        url=str(url),
                        timestamp=str(timestamp or ""),
                        identity_quality="legacy_url",
                    )
                )
        return converted
    return []


def _load_entries(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or HISTORY_PATH
    entries = _coerce_history_entries(load_json(target, {}))
    if entries:
        return entries
    if path is not None:
        return []
    for legacy in LEGACY_PATHS:
        entries = _coerce_history_entries(load_json(legacy, {}))
        if entries:
            return entries
    return []


def _entry_timestamp(entry: dict[str, Any]) -> datetime | None:
    raw = entry.get("last_seen_at") or entry.get("first_seen_at") or entry.get("timestamp")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.astimezone()
    return parsed


def _merge_timestamp(first: str, second: str, *, latest: bool) -> str:
    parsed: list[tuple[datetime, str]] = []
    for raw in (first, second):
        if not raw:
            continue
        try:
            value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.astimezone()
        parsed.append((value, str(raw)))
    if not parsed:
        return second or first
    selector = max if latest else min
    return selector(parsed, key=lambda value: value[0])[1]


def load_recent_history(
    days: int = 7,
    *,
    now: datetime | None = None,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    current = now or datetime.now().astimezone()
    if current.tzinfo is None or current.utcoffset() is None:
        current = current.astimezone()
    cutoff = current - timedelta(days=days)
    return [
        entry
        for entry in _load_entries(path)
        if (timestamp := _entry_timestamp(entry)) is not None
        and cutoff <= timestamp.astimezone(current.tzinfo) <= current
    ]


def match_history(
    candidate: dict[str, Any],
    *,
    days: int = 7,
    entries: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    pool = entries if entries is not None else load_recent_history(days=days, now=now)
    candidate_id = str(candidate.get("event_id") or "")
    if not candidate_id and isinstance(candidate.get("event_identity"), dict):
        try:
            candidate_id = generate_event_id(candidate["event_identity"])
        except ValueError:
            candidate_id = ""
    candidate_url = normalize_url(str(candidate.get("url") or ""))
    candidate_fingerprint = generate_fingerprint(
        str(candidate.get("title") or ""), str(candidate.get("source") or "")
    )
    candidate_title = normalize_text(str(candidate.get("title") or ""))
    candidate_is_semantic = candidate_id.startswith("evt1_")
    for entry in pool:
        entry_id = str(entry.get("event_id") or "")
        if candidate_id and entry_id == candidate_id:
            return {"redundant": True, "match_type": "event_id", "matched_id": entry_id}
        # A complete semantic identity is the event key.  Stable index or feed URLs
        # are often reused for multiple releases, so URL/title fallbacks must not
        # collapse two explicitly different semantic events.
        if candidate_is_semantic and entry_id.startswith("evt1_"):
            continue
        entry_urls = {
            normalize_url(str(value))
            for value in [entry.get("canonical_url"), *(entry.get("urls") or [])]
            if value
        }
        if candidate_url and candidate_url in entry_urls:
            return {"redundant": True, "match_type": "url", "matched_id": entry_id}
        if candidate_fingerprint in set(entry.get("fingerprints") or []):
            return {"redundant": True, "match_type": "fingerprint", "matched_id": entry_id}
        entry_title = normalize_text(str(entry.get("title") or ""))
        if candidate_title and entry_title:
            similarity = difflib.SequenceMatcher(None, entry_title, candidate_title).ratio()
            if similarity > 0.9:
                return {"redundant": True, "match_type": "title", "matched_id": entry_id}
    return {"redundant": False, "match_type": "none", "matched_id": None}


def is_redundant(
    url: str,
    title: str,
    source: str,
    days: int = 7,
    *,
    event_id: str = "",
    event_identity: dict[str, Any] | None = None,
) -> bool:
    result = match_history(
        {
            "event_id": event_id,
            "event_identity": event_identity,
            "url": url,
            "title": title,
            "source": source,
        },
        days=days,
    )
    return bool(result["redundant"])


def _entry_from_item(
    item: dict[str, Any],
    *,
    timestamp: str,
    archive_ref: str | None,
) -> dict[str, Any]:
    identity = item.get("event_identity") if isinstance(item.get("event_identity"), dict) else None
    quality = str(item.get("identity_quality") or "provisional")
    event_id = str(item.get("event_id") or "") if quality == "semantic" else ""
    if identity is not None and quality == "semantic":
        try:
            derived_event_id = generate_event_id(identity)
            event_id = derived_event_id
        except ValueError:
            event_id = ""
    if not event_id:
        event_id = generate_content_id(
            str(item.get("url") or ""),
            str(item.get("title") or ""),
            str(item.get("source") or ""),
        )
        quality = "provisional"
    canonical_url = normalize_url(str(item.get("url") or ""))
    provided_fingerprint = str(item.get("fingerprint") or "").strip()
    return {
        "event_id": event_id,
        "event_identity": deepcopy(identity),
        "identity_quality": quality,
        "canonical_url": canonical_url,
        "urls": [canonical_url] if canonical_url else [],
        "title": str(item.get("title") or ""),
        "source": str(item.get("source") or ""),
        "fingerprints": [
            provided_fingerprint
            or generate_fingerprint(
                str(item.get("title") or ""), str(item.get("source") or "")
            )
        ],
        "first_seen_at": timestamp,
        "last_seen_at": timestamp,
        "archive_refs": [archive_ref] if archive_ref else [],
    }


def save_history_items(
    items: list[dict[str, Any]],
    *,
    archive_ref: str | None = None,
    path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    target = path or HISTORY_PATH
    current = now or datetime.now().astimezone()
    if current.tzinfo is None or current.utcoffset() is None:
        current = current.astimezone()
    timestamp = current.isoformat()
    entries = _coerce_history_entries(load_json(target, {}))
    by_id = {str(entry.get("event_id") or ""): entry for entry in entries if entry.get("event_id")}
    for item in items:
        incoming = _entry_from_item(item, timestamp=timestamp, archive_ref=archive_ref)
        existing = by_id.get(incoming["event_id"])
        if existing is None:
            entries.append(incoming)
            by_id[incoming["event_id"]] = incoming
            continue
        existing["urls"] = sorted(set((existing.get("urls") or []) + incoming["urls"]))
        existing["fingerprints"] = sorted(
            set((existing.get("fingerprints") or []) + incoming["fingerprints"])
        )
        existing["archive_refs"] = sorted(
            set((existing.get("archive_refs") or []) + incoming["archive_refs"])
        )
        existing["first_seen_at"] = _merge_timestamp(
            str(existing.get("first_seen_at") or ""),
            timestamp,
            latest=False,
        )
        existing["last_seen_at"] = _merge_timestamp(
            str(existing.get("last_seen_at") or ""),
            timestamp,
            latest=True,
        )
        if not existing.get("canonical_url"):
            existing["canonical_url"] = incoming["canonical_url"]
        if existing.get("identity_quality") != "semantic" and incoming["identity_quality"] == "semantic":
            existing["event_identity"] = incoming["event_identity"]
            existing["identity_quality"] = "semantic"
    entries.sort(key=lambda entry: (str(entry.get("event_id") or ""), str(entry.get("canonical_url") or "")))
    payload = {
        "resource_kind": "pih_history_index",
        "schema_version": HISTORY_SCHEMA_VERSION,
        "generated_at": timestamp,
        "entries": entries,
    }
    atomic_dump_json(target, payload)
    return payload


def save_history(
    urls: list[str],
    fingerprints: list[str],
    titles: list[str] | None = None,
    *,
    path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    titles = titles or [""] * len(urls)
    items = [
        {"url": url, "title": title, "source": "", "fingerprint": fingerprint}
        for url, fingerprint, title in zip(urls, fingerprints, titles)
    ]
    return save_history_items(items, path=path, now=now)
