"""
<!-- Intelligence Hub: Reconnaissance Engine V4.0 -->
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
import time
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
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
def fetch_with_retry(url, *, headers=None, timeout=15, proxies=None, max_retries=2):
    """HTTP GET with exponential backoff retry."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            import requests
            resp = requests.get(url, headers=headers, timeout=timeout, proxies=proxies)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                wait = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(wait)
    raise last_error


# --- Parsers ---
def parse_rss(url, name, limit=10, proxy=None, cache=None):
    """Generic RSS/Atom feed parser."""
    try:
        proxies = {"http": proxy, "https": proxy} if proxy else None
        resp = fetch_with_retry(url, headers=get_headers(), timeout=20, proxies=proxies)
        # Strip default namespace for easier parsing
        cleaned_xml = re.sub(r' xmlns="[^"]+"', '', resp.text, count=1)
        root = ET.fromstring(cleaned_xml)

        items = []
        entries = (root.findall('.//item') or root.findall('.//entry'))[:limit]
        for entry in entries:
            title = entry.findtext('title') or "No Title"
            link_el = entry.find('link')
            link = entry.findtext('link') or (
                link_el.attrib.get('href') if link_el is not None else ""
            )

            if cache and link in cache:
                continue  # Incremental fetching

            desc_el = entry.find('description') or entry.find('summary') or entry.find('content')
            description = ""
            if desc_el is not None and desc_el.text:
                description = BeautifulSoup(desc_el.text, 'html.parser').get_text().strip()

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


def fetch_hackernews(limit=10, proxy=None, cache=None):
    """Fetch top stories from Hacker News Firebase API."""
    try:
        proxies = {"http": proxy, "https": proxy} if proxy else None
        resp = fetch_with_retry(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=10, proxies=proxies,
        )
        story_ids = resp.json()[:limit]

        items = []
        for story_id in story_ids:
            hn_url = f"https://news.ycombinator.com/item?id={story_id}"
            if cache and hn_url in cache:
                continue

            try:
                detail = fetch_with_retry(
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                    timeout=5, proxies=proxies, max_retries=1,
                )
                data = detail.json()
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


def fetch_github_trending(proxy=None, cache=None):
    """Scrape GitHub Trending page with selector fallback."""
    try:
        proxies = {"http": proxy, "https": proxy} if proxy else None
        resp = fetch_with_retry(
            "https://github.com/trending",
            headers=get_headers(), timeout=15, proxies=proxies,
        )
        soup = BeautifulSoup(resp.text, "html.parser")

        # Primary selector (current GitHub DOM)
        articles = soup.select("article.Box-row")
        # Fallback selector if GitHub changed their DOM
        if not articles:
            articles = soup.select("article[class*='Box-row']")
        if not articles:
            articles = soup.select("div.Box article")
        if not articles:
            print("  ⚠️ GitHub Trending: All selectors failed, DOM may have changed.")
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


def fetch_v2ex(proxy=None, cache=None):
    """Fetch hot topics from V2EX API."""
    try:
        proxies = {"http": proxy, "https": proxy} if proxy else None
        resp = fetch_with_retry(
            "https://www.v2ex.com/api/topics/hot.json",
            timeout=10, proxies=proxies,
        )
        data = resp.json()

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


def main():
    parser = argparse.ArgumentParser(description="Intelligence Hub: Multi-Source Reconnaissance Engine")
    parser.add_argument("--output", default="latest_scan.json", help="Output JSON filename")
    parser.add_argument("--proxy", help="Proxy URL (e.g. http://127.0.0.1:7890)")
    args = parser.parse_args()

    proxy = args.proxy or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    cache = load_cache()

    print("Intelligence Hub: Fetching data...")
    tasks = [
        ("hackernews", lambda: fetch_hackernews(10, proxy=proxy, cache=cache)),
        ("github", lambda: fetch_github_trending(proxy=proxy, cache=cache)),
        ("v2ex", lambda: fetch_v2ex(proxy=proxy, cache=cache)),
        ("producthunt", lambda: parse_rss("https://www.producthunt.com/feed", "Product Hunt", proxy=proxy, cache=cache)),
        ("healthit", lambda: parse_rss("https://www.healthit.gov/news/feed", "HealthIT.gov", proxy=proxy, cache=cache)),
        ("himss", lambda: parse_rss("https://www.himss.org/news", "HIMSS", proxy=None, cache=cache)),
        ("ajmc", lambda: parse_rss("https://www.ajmc.com/newsroom", "AJMC", proxy=proxy, cache=cache)),
    ]

    # Load Karpathy Feeds
    karpathy_path = HUB_DIR / "references" / "karpathy_feeds.json"
    if karpathy_path.exists():
        try:
            karpathy_feeds = json.loads(karpathy_path.read_text(encoding="utf-8"))
            for feed in karpathy_feeds:
                tasks.append((
                    feed["name"],
                    lambda url=feed["url"], name=feed["name"]: parse_rss(
                        url, name, limit=3, proxy=proxy, cache=cache
                    ),
                ))
        except Exception as exc:
            print(f"Error loading Karpathy feeds: {exc}")

    results = []
    stats = {}
    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_name = {executor.submit(func): name for name, func in tasks}
        for future in as_completed(future_to_name):
            source_name = future_to_name[future]
            try:
                items, status = future.result()
                results.extend(items)
                stats[source_name] = status
            except Exception as exc:
                stats[source_name] = str(exc)

    print(f"  - Total sources scanned: {len(tasks)}")
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
