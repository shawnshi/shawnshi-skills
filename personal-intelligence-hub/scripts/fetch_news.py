"""
<!-- Intelligence Hub: Reconnaissance Engine V5.0 -->
@Input: references/strategic_focus.json, references/karpathy_feeds.json
@Output: tmp/latest_scan.json (raw intelligence)
@Pos: Phase 1 (Multi-Source Reconnaissance)
@Maintenance Protocol: Parser logic changes must sync SKILL.md.
"""
import argparse
import json
import os
import random
import re
import asyncio
import aiohttp
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from pathlib import Path
from utils import HUB_DIR

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

def get_headers():
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


# --- Incremental Fetch Cache ---
CACHE_PATH = HUB_DIR / "tmp" / "fetch_cache.json"

def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}

def save_cache(cache: dict):
    """Keep only items from the last 7 days."""
    cutoff = (datetime.now() - timedelta(days=7)).timestamp()
    pruned = {url: ts for url, ts in cache.items() if ts > cutoff}
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(pruned), encoding="utf-8")


# --- Retry Helper ---
async def fetch_with_retry(session: aiohttp.ClientSession, url: str, headers=None, timeout=15, proxy=None, max_retries=2, is_json=False):
    """HTTP GET with exponential backoff retry."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            async with session.get(url, headers=headers, timeout=timeout, proxy=proxy) as resp:
                resp.raise_for_status()
                if is_json:
                    return await resp.json()
                return await resp.text()
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                wait = (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(wait)
    raise last_error


# --- Parsers ---
async def parse_rss(session: aiohttp.ClientSession, url: str, name: str, limit=10, proxy=None, cache=None):
    """Generic RSS/Atom feed parser using feedparser."""
    try:
        text = await fetch_with_retry(session, url, headers=get_headers(), timeout=20, proxy=proxy)
        feed = feedparser.parse(text)
        
        items = []
        for entry in feed.entries[:limit]:
            title = entry.get('title', 'No Title')
            link = entry.get('link', '')
            
            if cache and link in cache:
                continue

            description = ""
            desc_raw = entry.get('summary', '') or entry.get('description', '')
            if desc_raw:
                description = BeautifulSoup(desc_raw, 'html.parser').get_text().strip()

            items.append({
                "title": f"{name}: {title}",
                "url": link,
                "source": name,
                "time": datetime.now().isoformat(),
                "raw_desc": description,
            })
            if cache:
                cache[link] = datetime.now().timestamp()

        return items, "OK"
    except Exception as exc:
        return [], str(exc)


async def fetch_hackernews(session: aiohttp.ClientSession, limit=10, proxy=None, cache=None):
    """Fetch top stories from Hacker News Firebase API."""
    try:
        story_ids = await fetch_with_retry(
            session,
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=10, proxy=proxy, is_json=True
        )
        story_ids = story_ids[:limit]

        items = []
        for story_id in story_ids:
            hn_url = f"https://news.ycombinator.com/item?id={story_id}"
            if cache and hn_url in cache:
                continue

            try:
                data = await fetch_with_retry(
                    session,
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                    timeout=5, proxy=proxy, max_retries=1, is_json=True
                )
                items.append({
                    "title": data.get("title"),
                    "url": data.get("url", hn_url),
                    "source": "Hacker News",
                    "time": datetime.fromtimestamp(data.get("time", 0)).isoformat(),
                    "raw_desc": "",
                })
                if cache:
                    cache[hn_url] = datetime.now().timestamp()
            except Exception:
                continue

        return items, "OK"
    except Exception as exc:
        return [], str(exc)


async def fetch_github_trending(session: aiohttp.ClientSession, proxy=None, cache=None):
    """Scrape GitHub Trending page with selector fallback."""
    try:
        html = await fetch_with_retry(
            session,
            "https://github.com/trending",
            headers=get_headers(), timeout=15, proxy=proxy
        )
        soup = BeautifulSoup(html, "html.parser")

        articles = soup.select("article.Box-row")
        if not articles:
            articles = soup.select("article[class*='Box-row']")
        if not articles:
            articles = soup.select("div.Box article")
        if not articles:
            return [], "SELECTOR_FAILED"

        items = []
        for article in articles[:10]:
            title_el = article.select_one("h2 a") or article.select_one("h1 a")
            desc_el = article.select_one("p")
            if not title_el:
                continue

            url = "https://github.com" + title_el["href"]
            if cache and url in cache:
                continue

            items.append({
                "title": title_el.get_text(strip=True),
                "url": url,
                "source": "GitHub",
                "time": datetime.now().isoformat(),
                "raw_desc": desc_el.get_text(strip=True) if desc_el else "",
            })
            if cache:
                cache[url] = datetime.now().timestamp()

        return items, "OK"
    except Exception as exc:
        return [], str(exc)


async def fetch_v2ex(session: aiohttp.ClientSession, proxy=None, cache=None):
    """Fetch hot topics from V2EX API."""
    try:
        data = await fetch_with_retry(
            session,
            "https://www.v2ex.com/api/topics/hot.json",
            timeout=10, proxy=proxy, is_json=True
        )

        items = []
        for topic in data[:10]:
            url = topic.get("url")
            if cache and url in cache:
                continue

            content_preview = (topic.get("content") or "")[:500]
            items.append({
                "title": topic.get("title"),
                "url": url,
                "source": "V2EX",
                "time": datetime.now().isoformat(),
                "raw_desc": content_preview,
            })
            if cache:
                cache[url] = datetime.now().timestamp()

        return items, "OK"
    except Exception as exc:
        return [], str(exc)

async def scan_all(proxy, cache):
    tasks = []
    
    # We use a custom TCP connector to limit connections if necessary, 
    # but for now default is fine for ~100 sources
    async with aiohttp.ClientSession() as session:
        # Fixed sources tasks
        tasks_meta = [
            ("Hacker News", fetch_hackernews(session, 10, proxy=proxy, cache=cache)),
            ("GitHub", fetch_github_trending(session, proxy=proxy, cache=cache)),
            ("V2EX", fetch_v2ex(session, proxy=proxy, cache=cache)),
            ("Product Hunt", parse_rss(session, "https://www.producthunt.com/feed", "Product Hunt", proxy=proxy, cache=cache)),
            ("HealthIT.gov", parse_rss(session, "https://www.healthit.gov/news/feed", "HealthIT.gov", proxy=proxy, cache=cache)),
            ("HIMSS", parse_rss(session, "https://www.himss.org/news", "HIMSS", proxy=None, cache=cache)),
            ("AJMC", parse_rss(session, "https://www.ajmc.com/newsroom", "AJMC", proxy=proxy, cache=cache)),
            ("Nature Digital Medicine", parse_rss(session, "https://www.nature.com/npjdigitalmed.rss", "Nature Digital Medicine", limit=5, proxy=proxy, cache=cache)),
            ("Science", parse_rss(session, "https://www.science.org/rss/news_current.xml", "Science", limit=5, proxy=proxy, cache=cache)),
            ("The Lancet Digital Health", parse_rss(session, "https://www.thelancet.com/rssfeed/landig_current.xml", "The Lancet Digital Health", limit=5, proxy=proxy, cache=cache)),
            ("NEJM", parse_rss(session, "https://www.nejm.org/action/showFeed?type=etoc&feed=rss&jc=nejm", "NEJM", limit=5, proxy=proxy, cache=cache)),
            ("arXiv Med-AI", parse_rss(session, "http://export.arxiv.org/api/query?search_query=all:medicine+AND+cat:cs.AI&sortBy=lastUpdatedDate&sortOrder=descending&max_results=5", "arXiv Med-AI", limit=5, proxy=proxy, cache=cache)),
        ]

        karpathy_path = HUB_DIR / "references" / "karpathy_feeds.json"
        if karpathy_path.exists():
            try:
                karpathy_feeds = json.loads(karpathy_path.read_text(encoding="utf-8"))
                for feed in karpathy_feeds:
                    tasks_meta.append((
                        feed["name"],
                        parse_rss(session, feed["url"], feed["name"], limit=3, proxy=proxy, cache=cache)
                    ))
            except Exception as exc:
                print(f"Error loading Karpathy feeds: {exc}")

        # Gather all coroutines
        coroutines = [t[1] for t in tasks_meta]
        task_names = [t[0] for t in tasks_meta]
        
        results_arr = await asyncio.gather(*coroutines, return_exceptions=True)
        
        results = []
        stats = {}
        for name, res in zip(task_names, results_arr):
            if isinstance(res, Exception):
                stats[name] = str(res)
            else:
                items, status = res
                results.extend(items)
                stats[name] = status

        return results, stats

def main():
    parser = argparse.ArgumentParser(description="Intelligence Hub: Multi-Source Reconnaissance Engine")
    parser.add_argument("--output", default="latest_scan.json", help="Output JSON filename")
    parser.add_argument("--proxy", help="Proxy URL (e.g. http://127.0.0.1:7890)")
    args = parser.parse_args()

    # Load proxy from environment if not provided
    proxy = args.proxy or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    
    # Optional: on windows aiohttp proxy usually prefers explicit proxy URL (http://...)
    
    cache = load_cache()

    print("Intelligence Hub: Fetching data asynchronously...")
    
    # Handling specific event loop issues on Windows
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    results, stats = asyncio.run(scan_all(proxy, cache))

    print(f"  - Total sources scanned: {len(stats)}")
    print(f"  - Successful sources: {sum(1 for s in stats.values() if s == 'OK')}")
    print(f"  - New items captured: {len(results)}")

    output_data = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "sources": stats,
            "count": len(results),
        },
        "items": results,
    }

    save_cache(cache)

    tmp_path = HUB_DIR / "tmp"
    tmp_path.mkdir(parents=True, exist_ok=True)
    out_file = tmp_path / args.output

    out_file.write_text(
        json.dumps(output_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Data snapshot saved to: {out_file}")


if __name__ == "__main__":
    main()
