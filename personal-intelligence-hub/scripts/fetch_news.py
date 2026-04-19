from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timedelta

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from blackboard import init_blackboard, record_scan_stats, update_phase
from hub_utils import CURRENT_SCAN_PATH, FETCH_CACHE_PATH, HUB_DIR, LATEST_SCAN_PATH, dump_json, ensure_runtime_dirs, load_json


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def headers() -> dict:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def load_cache() -> dict:
    return load_json(FETCH_CACHE_PATH, {})


def save_cache(cache: dict, days: int = 7) -> None:
    cutoff = (datetime.now() - timedelta(days=days)).timestamp()
    pruned = {url: ts for url, ts in cache.items() if ts > cutoff}
    dump_json(FETCH_CACHE_PATH, pruned)


async def fetch_with_retry(session, url: str, timeout: int = 20, is_json: bool = False):
    last_error = None
    for attempt in range(3):
        try:
            async with session.get(url, headers=headers(), timeout=timeout) as resp:
                resp.raise_for_status()
                return await (resp.json() if is_json else resp.text())
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
    raise last_error


async def parse_rss(session, url: str, name: str, cache: dict, limit: int = 6):
    try:
        text = await fetch_with_retry(session, url)
        feed = feedparser.parse(text)
        items = []
        for entry in feed.entries[:limit]:
            link = entry.get("link", "")
            if not link or link in cache:
                continue
            desc_raw = entry.get("summary", "") or entry.get("description", "")
            desc = BeautifulSoup(desc_raw, "html.parser").get_text().strip() if desc_raw else ""
            items.append(
                {
                    "title": entry.get("title", "No Title"),
                    "url": link,
                    "source": name,
                    "time": datetime.now().isoformat(),
                    "raw_desc": desc,
                }
            )
            cache[link] = datetime.now().timestamp()
        return items, "OK"
    except Exception as exc:
        return [], str(exc)


async def fetch_hackernews(session, cache: dict):
    try:
        ids = await fetch_with_retry(
            session,
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=10,
            is_json=True,
        )
        items = []
        for story_id in ids[:10]:
            hn_url = f"https://news.ycombinator.com/item?id={story_id}"
            if hn_url in cache:
                continue
            data = await fetch_with_retry(
                session,
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                timeout=8,
                is_json=True,
            )
            items.append(
                {
                    "title": data.get("title", "No Title"),
                    "url": data.get("url", hn_url),
                    "source": "Hacker News",
                    "time": datetime.fromtimestamp(data.get("time", 0)).isoformat(),
                    "raw_desc": "",
                }
            )
            cache[hn_url] = datetime.now().timestamp()
        return items, "OK"
    except Exception as exc:
        return [], str(exc)


async def fetch_v2ex(session, cache: dict):
    try:
        data = await fetch_with_retry(
            session, "https://www.v2ex.com/api/topics/hot.json", timeout=10, is_json=True
        )
        items = []
        for topic in data[:10]:
            url = topic.get("url")
            if not url or url in cache:
                continue
            items.append(
                {
                    "title": topic.get("title", "No Title"),
                    "url": url,
                    "source": "V2EX",
                    "time": datetime.now().isoformat(),
                    "raw_desc": (topic.get("content") or "")[:500],
                }
            )
            cache[url] = datetime.now().timestamp()
        return items, "OK"
    except Exception as exc:
        return [], str(exc)


async def fetch_github_trending(session, cache: dict):
    try:
        html = await fetch_with_retry(session, "https://github.com/trending", timeout=15)
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
                {
                    "title": title_el.get_text(strip=True),
                    "url": url,
                    "source": "GitHub",
                    "time": datetime.now().isoformat(),
                    "raw_desc": desc_el.get_text(strip=True) if desc_el else "",
                }
            )
            cache[url] = datetime.now().timestamp()
        return items, "OK"
    except Exception as exc:
        return [], str(exc)


def load_config() -> tuple[dict, list[dict]]:
    focus = load_json(HUB_DIR / "references" / "strategic_focus.json", {})
    feeds = load_json(HUB_DIR / "references" / "karpathy_feeds.json", [])
    return focus, feeds


def should_exclude(title: str, desc: str, exclude_terms: list[str]) -> bool:
    text = f"{title} {desc}".lower()
    return any(term.lower() in text for term in exclude_terms)


async def scan_all():
    ensure_runtime_dirs()
    init_blackboard()
    update_phase("scan", "running")

    focus, custom_feeds = load_config()
    exclude_terms = focus.get("filters", {}).get("exclude_terms", [])
    cache = load_cache()

    async with aiohttp.ClientSession() as session:
        tasks_meta = [
            ("Hacker News", fetch_hackernews(session, cache)),
            ("GitHub", fetch_github_trending(session, cache)),
            ("V2EX", fetch_v2ex(session, cache)),
            ("HealthIT.gov", parse_rss(session, "https://www.healthit.gov/news/feed", "HealthIT.gov", cache)),
            ("HIMSS", parse_rss(session, "https://www.himss.org/news", "HIMSS", cache)),
            ("Nature Digital Medicine", parse_rss(session, "https://www.nature.com/npjdigitalmed.rss", "Nature Digital Medicine", cache, limit=5)),
            ("The Lancet Digital Health", parse_rss(session, "https://www.thelancet.com/rssfeed/landig_current.xml", "The Lancet Digital Health", cache, limit=5)),
            ("NEJM", parse_rss(session, "https://www.nejm.org/action/showFeed?type=etoc&feed=rss&jc=nejm", "NEJM", cache, limit=5)),
            ("Product Hunt", parse_rss(session, "https://www.producthunt.com/feed", "Product Hunt", cache, limit=5)),
        ]
        for feed in custom_feeds:
            tasks_meta.append(
                (feed["name"], parse_rss(session, feed["url"], feed["name"], cache, limit=3))
            )

        results = await asyncio.gather(*[x[1] for x in tasks_meta], return_exceptions=True)

    items = []
    source_meta = {}
    for (name, _), result in zip(tasks_meta, results):
        if isinstance(result, Exception):
            source_meta[name] = str(result)
            continue
        parsed_items, status = result
        source_meta[name] = status
        for item in parsed_items:
            if should_exclude(item["title"], item.get("raw_desc", ""), exclude_terms):
                continue
            items.append(item)

    payload = {
        "generated_at": datetime.now().isoformat(),
        "items": items,
        "metadata": {"sources": source_meta, "item_count": len(items)},
    }
    dump_json(LATEST_SCAN_PATH, payload)
    dump_json(CURRENT_SCAN_PATH, payload)
    save_cache(cache, days=focus.get("filters", {}).get("dedupe_days", 7))
    record_scan_stats(len(source_meta), len(items))
    update_phase("scan", "completed")
    print(f"[OK] scan saved to {LATEST_SCAN_PATH}")


if __name__ == "__main__":
    asyncio.run(scan_all())
