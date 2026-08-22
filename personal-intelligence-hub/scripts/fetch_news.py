from __future__ import annotations

import asyncio
import argparse
import random
import re
from datetime import date, datetime, timedelta, timezone, tzinfo
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from blackboard import init_blackboard, record_scan_stats, update_phase
from hub_utils import CURRENT_SCAN_PATH, FETCH_CACHE_PATH, HUB_DIR, LATEST_SCAN_PATH, atomic_dump_json, ensure_runtime_dirs, load_json


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_WINDOW_DAYS = 7
DEFAULT_MAX_CONCURRENCY = 8
MAX_CONCURRENCY = 32
PERMANENT_TRANSPORT_ERROR_MARKERS = (
    "invalid library",
    "certificate verify failed",
    "unsupported protocol",
    "invalid url",
    "no host supplied",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_timezone(timezone_name: str = DEFAULT_TIMEZONE) -> tzinfo:
    """Resolve an IANA timezone without making tzdata mandatory on Windows."""
    if timezone_name == DEFAULT_TIMEZONE:
        return timezone(timedelta(hours=8), name=DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {timezone_name}") from exc


def _coerce_report_date(value: date | datetime | str | None, zone: tzinfo) -> date:
    if value is None:
        return _utc_now().astimezone(zone).date()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("report datetime must be timezone-aware")
        return value.astimezone(zone).date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("report_date must be an ISO date") from exc


def build_calendar_window(
    *,
    report_date: date | datetime | str | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> dict:
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    zone = resolve_timezone(timezone_name)
    end = _coerce_report_date(report_date, zone)
    start = end - timedelta(days=window_days - 1)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": timezone_name,
        "days": window_days,
        "mode": "calendar_days",
    }


def _published_raw(item: dict):
    value = item.get("published_at")
    if value in (None, ""):
        value = item.get("time")
    return value


def _parse_published_date(value, zone: tzinfo) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("published datetime must be timezone-aware")
        return value.astimezone(zone).date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("published datetime must be timezone-aware")
        return parsed.astimezone(zone).date()


def _published_date_state(item: dict, zone: tzinfo) -> tuple[date | None, str | None]:
    raw = _published_raw(item)
    if raw in (None, "", "unknown"):
        return None, "unknown_published_at"
    try:
        return _parse_published_date(raw, zone), None
    except (TypeError, ValueError, OverflowError):
        return None, "invalid_published_at"


def apply_window_contract(
    items: list[dict],
    *,
    window: dict,
    exclude_terms: list[str] | None = None,
) -> tuple[list[dict], list[dict], dict]:
    zone = resolve_timezone(str(window["timezone"]))
    start = date.fromisoformat(str(window["start"]))
    end = date.fromisoformat(str(window["end"]))
    excluded_terms = exclude_terms or []
    kept: list[dict] = []
    quarantine: list[dict] = []
    funnel = {
        "raw": len(items),
        "dated": 0,
        "quarantined": 0,
        "within_window": 0,
        "outside_window": 0,
        "excluded": 0,
        "retained": 0,
        "quarantine_reasons": {
            "unknown_published_at": 0,
            "invalid_published_at": 0,
        },
    }

    for item in items:
        published_date, reason = _published_date_state(item, zone)
        if reason is not None:
            funnel["quarantined"] += 1
            funnel["quarantine_reasons"][reason] += 1
            quarantine.append({"reason": reason, "item": item})
            continue
        funnel["dated"] += 1
        if published_date is None or not (start <= published_date <= end):
            funnel["outside_window"] += 1
            continue
        funnel["within_window"] += 1
        if should_exclude(item.get("title", ""), item.get("raw_desc", ""), excluded_terms):
            funnel["excluded"] += 1
            continue
        kept.append(item)

    funnel["retained"] = len(kept)
    if funnel["raw"] != funnel["dated"] + funnel["quarantined"]:
        raise RuntimeError("candidate funnel does not conserve raw candidates")
    if funnel["dated"] != funnel["within_window"] + funnel["outside_window"]:
        raise RuntimeError("candidate funnel does not conserve dated candidates")
    if funnel["within_window"] != funnel["excluded"] + funnel["retained"]:
        raise RuntimeError("candidate funnel does not conserve in-window candidates")
    return kept, quarantine, funnel


def build_coverage(source_meta: dict[str, object], funnel: dict) -> dict:
    def succeeded(status: object) -> bool:
        if isinstance(status, dict):
            return str(status.get("status", "")).upper() in {"OK", "SUCCESS"}
        return str(status).upper() == "OK"

    attempted = len(source_meta)
    source_succeeded = sum(1 for status in source_meta.values() if succeeded(status))
    source_failed = attempted - source_succeeded
    raw = int(funnel.get("raw", 0))
    dated_rate = (int(funnel.get("dated", 0)) / raw) if raw else 0.0
    reasons: list[str] = []
    if attempted == 0 or source_succeeded == 0:
        run_status = "failed"
        reasons.append("no source completed successfully")
    elif raw == 0:
        run_status = "degraded"
        reasons.append("sources completed but produced no candidates")
    elif source_failed or int(funnel.get("quarantined", 0)):
        run_status = "degraded"
        if source_failed:
            reasons.append(f"{source_failed} source(s) failed")
        if int(funnel.get("quarantined", 0)):
            reasons.append("some candidates lacked a valid publication date")
    else:
        run_status = "complete"
    return {
        "run_status": run_status,
        "baseline_status": run_status,
        "coverage_confidence": (
            "high" if run_status == "complete" else "medium" if run_status == "degraded" else "low"
        ),
        "source_attempted": attempted,
        "source_succeeded": source_succeeded,
        "source_failed": source_failed,
        "source_success_rate": (source_succeeded / attempted) if attempted else 0.0,
        "raw_candidates": raw,
        "dated_candidates": int(funnel.get("dated", 0)),
        "quarantined_candidates": int(funnel.get("quarantined", 0)),
        "dated_candidate_rate": dated_rate,
        "required_lane_failures": [],
        "reasons": reasons,
    }


def headers() -> dict:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def load_cache(path: Path | None = None) -> dict:
    return load_json(path or FETCH_CACHE_PATH, {})


def save_cache(cache: dict, days: int = 7, *, path: Path | None = None) -> None:
    cutoff = (_utc_now() - timedelta(days=days)).timestamp()
    pruned = {url: ts for url, ts in cache.items() if ts > cutoff}
    atomic_dump_json(path or FETCH_CACHE_PATH, pruned)


async def fetch_with_retry(
    session,
    url: str,
    timeout: int = 20,
    is_json: bool = False,
    *,
    semaphore: asyncio.Semaphore | None = None,
):
    last_error = None
    for attempt in range(3):
        try:
            async def request_once():
                async with session.get(url, headers=headers(), timeout=timeout) as resp:
                    resp.raise_for_status()
                    return await (resp.json() if is_json else resp.text())

            if semaphore is None:
                return await request_once()
            async with semaphore:
                return await request_once()
        except Exception as exc:
            last_error = exc
            status = getattr(exc, "status", None)
            if isinstance(status, int):
                retryable = status in {408, 425, 429} or 500 <= status <= 599
            else:
                message = str(exc).lower()
                retryable = not any(
                    marker in message for marker in PERMANENT_TRANSPORT_ERROR_MARKERS
                )
            if attempt < 2 and retryable:
                await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
            else:
                break
    raise last_error


def _publication_fields(
    published_at: str | None,
    published_at_source: str,
    retrieved_at: str,
) -> dict:
    normalized = published_at or "unknown"
    return {
        "published_at": normalized,
        "published_at_source": published_at_source if published_at else "unknown",
        "time": normalized,
        "retrieved_at": retrieved_at,
    }


def _build_hackernews_item(data: dict, *, story_id: int, retrieved_at: str) -> dict:
    raw_time = data.get("time")
    published_at = None
    if isinstance(raw_time, (int, float)) and raw_time > 0:
        published_at = datetime.fromtimestamp(raw_time, tz=timezone.utc).isoformat()
    hn_url = f"https://news.ycombinator.com/item?id={story_id}"
    return {
        "title": data.get("title", "No Title"),
        "url": data.get("url", hn_url),
        "source": "Hacker News",
        **_publication_fields(published_at, "api_created", retrieved_at),
        "raw_desc": "",
    }


def _build_v2ex_item(topic: dict, *, retrieved_at: str) -> dict:
    raw_created = topic.get("created")
    published_at = None
    if isinstance(raw_created, (int, float)) and raw_created > 0:
        published_at = datetime.fromtimestamp(raw_created, tz=timezone.utc).isoformat()
    return {
        "title": topic.get("title", "No Title"),
        "url": topic.get("url", ""),
        "source": "V2EX",
        **_publication_fields(published_at, "api_created", retrieved_at),
        "raw_desc": (topic.get("content") or "")[:500],
    }


def _build_github_item(
    *, title: str, url: str, description: str, retrieved_at: str
) -> dict:
    return {
        "title": title,
        "url": url,
        "source": "GitHub",
        **_publication_fields(None, "unknown", retrieved_at),
        "raw_desc": description,
    }


async def parse_rss(
    session,
    url: str,
    name: str,
    cache: dict,
    limit: int = 6,
    *,
    semaphore: asyncio.Semaphore | None = None,
):
    try:
        import feedparser
        from bs4 import BeautifulSoup

        text = await fetch_with_retry(session, url, semaphore=semaphore)
        feed = feedparser.parse(text)
        if not str(getattr(feed, "version", "") or "").strip():
            raise ValueError("response is not a recognized RSS or Atom feed")
        if bool(getattr(feed, "bozo", False)) and not feed.entries and not feed.feed:
            raise ValueError("feed parser rejected the source payload")
        items = []
        for entry in feed.entries[:limit]:
            link = entry.get("link", "")
            if not link or link in cache:
                continue
            desc_raw = entry.get("summary", "") or entry.get("description", "")
            desc = BeautifulSoup(desc_raw, "html.parser").get_text().strip() if desc_raw else ""
            published = entry.get("published")
            published_source = "rss_published"
            published_at = None
            try:
                parsed = parsedate_to_datetime(published) if published else None
                if parsed is not None and parsed.tzinfo is not None:
                    published_at = parsed.astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError, OverflowError):
                published_at = None
            retrieved_at = _utc_now().isoformat()
            items.append(
                {
                    "title": entry.get("title", "No Title"),
                    "url": link,
                    "source": name,
                    **_publication_fields(published_at, published_source, retrieved_at),
                    "raw_desc": desc,
                }
            )
            cache[link] = _utc_now().timestamp()
        return items, "OK"
    except Exception as exc:
        return [], str(exc)


async def fetch_hackernews(
    session, cache: dict, *, semaphore: asyncio.Semaphore | None = None
):
    try:
        ids = await fetch_with_retry(
            session,
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=10,
            is_json=True,
            semaphore=semaphore,
        )
        pending_ids = []
        for story_id in ids[:10]:
            hn_url = f"https://news.ycombinator.com/item?id={story_id}"
            if hn_url in cache:
                continue
            pending_ids.append(story_id)

        async def fetch_story(story_id):
            return await fetch_with_retry(
                session,
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                timeout=8,
                is_json=True,
                semaphore=semaphore,
            )

        results = await asyncio.gather(
            *(fetch_story(story_id) for story_id in pending_ids),
            return_exceptions=True,
        )
        items = []
        failed = 0
        for story_id, data in zip(pending_ids, results):
            if isinstance(data, Exception):
                failed += 1
                continue
            items.append(
                _build_hackernews_item(
                    data,
                    story_id=story_id,
                    retrieved_at=_utc_now().isoformat(),
                )
            )
            hn_url = f"https://news.ycombinator.com/item?id={story_id}"
            cache[hn_url] = _utc_now().timestamp()
        status = (
            "OK"
            if failed == 0
            else f"partial: {failed}/{len(pending_ids)} item requests failed"
        )
        return items, status
    except Exception as exc:
        return [], str(exc)


async def fetch_v2ex(
    session, cache: dict, *, semaphore: asyncio.Semaphore | None = None
):
    try:
        data = await fetch_with_retry(
            session,
            "https://www.v2ex.com/api/topics/hot.json",
            timeout=10,
            is_json=True,
            semaphore=semaphore,
        )
        items = []
        for topic in data[:10]:
            url = topic.get("url")
            if not url or url in cache:
                continue
            items.append(
                _build_v2ex_item(topic, retrieved_at=_utc_now().isoformat())
            )
            cache[url] = _utc_now().timestamp()
        return items, "OK"
    except Exception as exc:
        return [], str(exc)


async def fetch_github_trending(
    session, cache: dict, *, semaphore: asyncio.Semaphore | None = None
):
    try:
        from bs4 import BeautifulSoup

        html = await fetch_with_retry(
            session,
            "https://github.com/trending",
            timeout=15,
            semaphore=semaphore,
        )
        soup = BeautifulSoup(html, "html.parser")
        articles = soup.select("article.Box-row") or soup.select("article[class*='Box-row']")
        items = []
        for article in articles[:10]:
            title_el = article.select_one("h2 a") or article.select_one("h1 a")
            desc_el = article.select_one("p")
            if not title_el:
                continue
            url = "https://github.com" + title_el["href"]
            if url in cache:
                continue
            items.append(
                _build_github_item(
                    title=title_el.get_text(strip=True),
                    url=url,
                    description=desc_el.get_text(strip=True) if desc_el else "",
                    retrieved_at=_utc_now().isoformat(),
                )
            )
            cache[url] = _utc_now().timestamp()
        return items, "OK"
    except Exception as exc:
        return [], str(exc)


def load_config(focus_path: Path | None = None) -> tuple[dict, list[dict]]:
    focus = load_json(focus_path or HUB_DIR / "references" / "strategic_focus.json", {})
    feeds = load_json(HUB_DIR / "references" / "karpathy_feeds.json", [])
    return focus, feeds


def should_exclude(title: str, desc: str, exclude_terms: list[str]) -> bool:
    text = f"{title} {desc}".lower()
    for term in exclude_terms:
        term_lower = term.lower()
        if re.match(r'^[a-z0-9\s]+$', term_lower):
            if re.search(rf'\b{re.escape(term_lower)}\b', text):
                return True
        else:
            if term_lower in text:
                return True
    return False


def _inside_window(
    item: dict,
    window_days: int | None,
    *,
    report_date: date | datetime | str | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> bool:
    window = build_calendar_window(
        report_date=report_date,
        window_days=window_days or DEFAULT_WINDOW_DAYS,
        timezone_name=timezone_name,
    )
    zone = resolve_timezone(timezone_name)
    published_date, reason = _published_date_state(item, zone)
    if reason is not None or published_date is None:
        return False
    return (
        date.fromisoformat(window["start"])
        <= published_date
        <= date.fromisoformat(window["end"])
    )


async def _scan_all_impl(
    *,
    focus_path: Path | None = None,
    window_days: int | None = None,
    dedupe_days: int | None = None,
    topic: str | None = None,
    region: str | None = None,
    report_date: date | datetime | str | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    output_path: Path | None = None,
    current_output_path: Path | None = None,
    cache_path: Path | None = None,
):
    import aiohttp

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    focus, custom_feeds = load_config(focus_path)
    exclude_terms = focus.get("filters", {}).get("exclude_terms", [])
    cache = load_cache(cache_path)
    effective_window_days = window_days or DEFAULT_WINDOW_DAYS
    window = build_calendar_window(
        report_date=report_date,
        window_days=effective_window_days,
        timezone_name=timezone_name,
    )
    semaphore = asyncio.Semaphore(max_concurrency)

    connector = aiohttp.TCPConnector(
        limit=max_concurrency,
        limit_per_host=max(1, min(4, max_concurrency)),
        ttl_dns_cache=300,
    )
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks_meta = [
            ("Hacker News", fetch_hackernews(session, cache, semaphore=semaphore)),
            ("GitHub", fetch_github_trending(session, cache, semaphore=semaphore)),
            ("V2EX", fetch_v2ex(session, cache, semaphore=semaphore)),
        ]
        for feed in custom_feeds:
            limit = feed.get("limit", 5)
            tasks_meta.append(
                (
                    feed["name"],
                    parse_rss(
                        session,
                        feed["url"],
                        feed["name"],
                        cache,
                        limit=limit,
                        semaphore=semaphore,
                    ),
                )
            )

        results = await asyncio.gather(*[x[1] for x in tasks_meta], return_exceptions=True)

    raw_items = []
    source_meta = {}
    for (name, _), result in zip(tasks_meta, results):
        if isinstance(result, Exception):
            source_meta[name] = str(result)
            continue
        parsed_items, status = result
        source_meta[name] = status
        raw_items.extend(parsed_items)

    items, quarantine, candidate_funnel = apply_window_contract(
        raw_items,
        window=window,
        exclude_terms=exclude_terms,
    )
    coverage = build_coverage(source_meta, candidate_funnel)
    zone = resolve_timezone(timezone_name)
    now = _utc_now().astimezone(zone)
    payload = {
        "generated_at": now.isoformat(),
        "items": items,
        "quarantine": quarantine,
        "coverage": coverage,
        "candidate_funnel": candidate_funnel,
        "metadata": {
            "sources": source_meta,
            "item_count": len(items),
            "topic": topic,
            "region": region,
            "window": window,
            "window_days": effective_window_days,
            "report_date": window["end"],
            "max_concurrency": max_concurrency,
            "elapsed_seconds": round(loop.time() - started_at, 3),
        },
    }
    latest_target = output_path or LATEST_SCAN_PATH
    current_target = current_output_path or CURRENT_SCAN_PATH
    atomic_dump_json(latest_target, payload)
    atomic_dump_json(current_target, payload)
    save_cache(
        cache,
        days=dedupe_days or focus.get("filters", {}).get("dedupe_days", 7),
        path=cache_path,
    )
    record_scan_stats(len(source_meta), len(items))
    update_phase("scan", "completed")
    print(f"[OK] scan saved to {latest_target}")
    return payload


async def scan_all(
    *,
    focus_path: Path | None = None,
    window_days: int | None = None,
    dedupe_days: int | None = None,
    topic: str | None = None,
    region: str | None = None,
    report_date: date | datetime | str | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    output_path: Path | None = None,
    current_output_path: Path | None = None,
    cache_path: Path | None = None,
):
    if max_concurrency <= 0 or max_concurrency > MAX_CONCURRENCY:
        raise ValueError(f"max_concurrency must be between 1 and {MAX_CONCURRENCY}")
    ensure_runtime_dirs()
    init_blackboard()
    update_phase("scan", "running")
    try:
        return await _scan_all_impl(
            focus_path=focus_path,
            window_days=window_days,
            dedupe_days=dedupe_days,
            topic=topic,
            region=region,
            report_date=report_date,
            timezone_name=timezone_name,
            max_concurrency=max_concurrency,
            output_path=output_path,
            current_output_path=current_output_path,
            cache_path=cache_path,
        )
    except Exception as exc:
        try:
            update_phase("scan", "failed")
        except Exception as status_exc:
            exc.add_note(f"failed to update scan phase: {status_exc}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parameterized intelligence source scan.")
    parser.add_argument("--focus-config", type=Path)
    parser.add_argument("--window-days", type=int)
    parser.add_argument("--dedupe-days", type=int)
    parser.add_argument("--topic")
    parser.add_argument("--region")
    parser.add_argument("--report-date", help="Report date in YYYY-MM-DD format")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=DEFAULT_MAX_CONCURRENCY,
        help=f"Global concurrent requests (1..{MAX_CONCURRENCY}; per-host maximum 4).",
    )
    args = parser.parse_args()
    if args.window_days is not None and args.window_days <= 0:
        parser.error("--window-days must be positive")
    if args.dedupe_days is not None and args.dedupe_days <= 0:
        parser.error("--dedupe-days must be positive")
    if args.max_concurrency <= 0 or args.max_concurrency > MAX_CONCURRENCY:
        parser.error(f"--max-concurrency must be between 1 and {MAX_CONCURRENCY}")
    try:
        parsed_report_date = date.fromisoformat(args.report_date) if args.report_date else None
        resolve_timezone(args.timezone)
    except ValueError as exc:
        parser.error(str(exc))
    asyncio.run(
        scan_all(
            focus_path=args.focus_config,
            window_days=args.window_days,
            dedupe_days=args.dedupe_days,
            topic=args.topic,
            region=args.region,
            report_date=parsed_report_date,
            timezone_name=args.timezone,
            max_concurrency=args.max_concurrency,
        )
    )
