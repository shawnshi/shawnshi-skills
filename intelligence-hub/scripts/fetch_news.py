"""
<!-- Standard Header -->
@Input: references/strategic_focus.json
@Output: tmp/raw_intelligence.json, terminal stdout
@Pos: Phase 1 (Reconnaissance Phase)
@Maintenance Protocol: Parser logic changes must sync SKILL.md.
"""
import argparse, json, requests, re, random, os, xml.etree.ElementTree as ET
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
def get_h(): return {'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}

# --- Incremental Fetch Cache ---
CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "tmp", "fetch_cache.json")
def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}
    return {}

def save_cache(cache):
    # Keep only items from the last 7 days
    cutoff = (datetime.now() - timedelta(days=7)).timestamp()
    new_cache = {url: ts for url, ts in cache.items() if ts > cutoff}
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(new_cache, f)

# --- Parsers ---
def parse_rss(url, name, limit=10, proxy=None, cache=None):
    try:
        proxies = {'http': proxy, 'https': proxy} if proxy else None
        r = requests.get(url, headers=get_h(), timeout=20, proxies=proxies)
        root = ET.fromstring(re.sub(' xmlns="[^"]+"', '', r.text, count=1))
        items = []
        entries = (root.findall('.//item') or root.findall('.//entry'))[:limit]
        for e in entries:
            t = e.findtext('title') or "No Title"
            l = e.findtext('link') or (e.find('link').attrib.get('href') if e.find('link') is not None else "")
            
            if cache and l in cache: continue # Incremental Fetching

            d_e = e.find('description') or e.find('summary') or e.find('content')
            d = BeautifulSoup(d_e.text or "", 'html.parser').get_text().strip() if d_e is not None else ""
            items.append({"title": f"{name}: {t}", "url": l, "source": name, "time": datetime.now().isoformat(), "raw_desc": d})
            if cache: cache[l] = datetime.now().timestamp()
        return items, "OK"
    except Exception as e: return [], str(e)

def f_hn(limit, proxy=None, cache=None):
    try:
        proxies = {'http': proxy, 'https': proxy} if proxy else None
        ids = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10, proxies=proxies).json()[:limit]
        items = []
        for i in ids:
            url = f"https://news.ycombinator.com/item?id={i}"
            if cache and url in cache: continue # Incremental Fetching
            try:
                d = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{i}.json", timeout=5, proxies=proxies).json()
                items.append({"title": d.get("title"), "url": d.get("url", url), "source": "Hacker News", "time": datetime.fromtimestamp(d.get("time", 0)).isoformat(), "raw_desc": ""})
                if cache: cache[url] = datetime.now().timestamp()
            except: continue
        return items, "OK"
    except Exception as e: return [], str(e)

def f_gh(proxy=None, cache=None):
    try:
        proxies = {'http': proxy, 'https': proxy} if proxy else None
        s = BeautifulSoup(requests.get("https://github.com/trending", headers=get_h(), timeout=15, proxies=proxies).text, 'html.parser')
        items = []
        for a in s.select('article.Box-row')[:10]:
            t = a.select_one('h2 a'); d = a.select_one('p')
            url = "https://github.com" + t['href'] if t else ""
            if cache and url in cache: continue # Incremental Fetching
            if t:
                items.append({"title": t.get_text(strip=True), "url": url, "source": "GitHub", "time": datetime.now().isoformat(), "raw_desc": d.get_text(strip=True) if d else ""})
                if cache: cache[url] = datetime.now().timestamp()
        return items, "OK"
    except Exception as e: return [], str(e)

def f_v2ex(proxy=None, cache=None):
    try:
        proxies = {'http': proxy, 'https': proxy} if proxy else None
        d = requests.get("https://www.v2ex.com/api/topics/hot.json", timeout=10, proxies=proxies).json()
        items = []
        for i in d[:10]:
            url = i.get('url')
            if cache and url in cache: continue # Incremental Fetching
            items.append({"title": i.get('title'), "url": url, "source": "V2EX", "time": datetime.now().isoformat(), "raw_desc": i.get('content')[:500]})
            if cache: cache[url] = datetime.now().timestamp()
        return items, "OK"
    except Exception as e: return [], str(e)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true", help="Legacy flag, now triggers JSON dump")
    parser.add_argument("--output", default="latest_scan.json", help="Output JSON path")
    parser.add_argument("--proxy", help="Proxy URL (e.g. http://127.0.0.1:7890)")
    args = parser.parse_args()
    
    proxy = args.proxy or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    cache = load_cache()

    print("Intelligence Hub: Fetching data...")
    tasks = [
        ('hackernews', lambda: f_hn(10, proxy=proxy, cache=cache)), 
        ('github', lambda: f_gh(proxy=proxy, cache=cache)), 
        ('v2ex', lambda: f_v2ex(proxy=proxy, cache=cache)),
        ('producthunt', lambda: parse_rss("https://www.producthunt.com/feed", "Product Hunt", proxy=proxy, cache=cache)),
        ('healthit', lambda: parse_rss("https://www.healthit.gov/news/feed", "HealthIT.gov", proxy=proxy, cache=cache)),
        ('himss', lambda: parse_rss("https://www.himss.org/news", "HIMSS", proxy=None, cache=cache)), # Domestic direct?
        ('ajmc', lambda: parse_rss("https://www.ajmc.com/newsroom", "AJMC", proxy=proxy, cache=cache))
    ]
    
    # Load Karpathy Feeds
    karpathy_path = os.path.join(os.path.dirname(__file__), "..", "references", "karpathy_feeds.json")
    if os.path.exists(karpathy_path):
        try:
            with open(karpathy_path, 'r', encoding='utf-8') as f:
                k_feeds = json.load(f)
                for k in k_feeds:
                    tasks.append((k['name'], lambda url=k['url'], name=k['name']: parse_rss(url, name, limit=3, proxy=proxy, cache=cache)))
        except Exception as e:
            print(f"Error loading Karpathy feeds: {e}")

    res = []; stats = {}
    with ThreadPoolExecutor(max_workers=20) as ex:
        f2n = {ex.submit(f): n for n, f in tasks}
        for f in as_completed(f2n):
            n = f2n[f]
            try:
                it, st = f.result()
                res.extend(it); stats[n] = st
            except Exception as e:
                stats[n] = str(e)

    print(f"  - Total sources scanned: {len(tasks)}")
    print(f"  - Successful sources: {sum(1 for s in stats.values() if s == 'OK')}")
    print(f"  - New items captured: {len(res)}")

    output_data = {
        "metadata": {"timestamp": datetime.now().isoformat(), "sources": stats, "count": len(res)},
        "items": res
    }
    
    save_cache(cache)
    
    tmp_path = os.path.join(os.path.dirname(__file__), "..", "tmp")
    os.makedirs(tmp_path, exist_ok=True)
    out_file = os.path.join(tmp_path, args.output)
    
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"Data snapshot saved to: {out_file}")

if __name__ == "__main__":
    main()
