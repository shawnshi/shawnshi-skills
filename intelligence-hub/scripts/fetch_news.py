"""
<!-- Intelligence Hub: Data Fetcher V4.1 -->
<!-- Responsibility: Fetch raw data -> Clean -> Output JSON -->
"""
import argparse, json, requests, re, random, os, xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
def get_h(): return {'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}

# --- Parsers ---
def parse_rss(url, name, limit=10):
    try:
        r = requests.get(url, headers=get_h(), timeout=15)
        root = ET.fromstring(re.sub(' xmlns="[^"]+"', '', r.text, count=1))
        items = []
        for e in (root.findall('.//item') or root.findall('.//entry'))[:limit]:
            t = e.findtext('title') or "No Title"
            l = e.findtext('link') or (e.find('link').attrib.get('href') if e.find('link') is not None else "")
            d_e = e.find('description') or e.find('summary') or e.find('content')
            d = BeautifulSoup(d_e.text or "", 'html.parser').get_text().strip() if d_e is not None else ""
            items.append({"title": f"{name}: {t}", "url": l, "source": name, "time": datetime.now().isoformat(), "raw_desc": d})
        return items, "OK"
    except Exception as e: return [], str(e)

def f_hn(limit):
    try:
        ids = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10).json()[:limit]
        items = []
        for i in ids:
            try:
                d = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{i}.json", timeout=5).json()
                items.append({"title": d.get("title"), "url": d.get("url", f"https://news.ycombinator.com/item?id={i}"), "source": "Hacker News", "time": datetime.fromtimestamp(d.get("time", 0)).isoformat(), "raw_desc": ""})
            except: continue
        return items, "OK"
    except Exception as e: return [], str(e)

def f_gh():
    try:
        s = BeautifulSoup(requests.get("https://github.com/trending", headers=get_h(), timeout=15).text, 'html.parser')
        items = []
        for a in s.select('article.Box-row')[:10]:
            t = a.select_one('h2 a'); d = a.select_one('p')
            if t: items.append({"title": t.get_text(strip=True), "url": "https://github.com" + t['href'], "source": "GitHub", "time": datetime.now().isoformat(), "raw_desc": d.get_text(strip=True) if d else ""})
        return items, "OK"
    except Exception as e: return [], str(e)

def f_v2ex():
    try:
        d = requests.get("https://www.v2ex.com/api/topics/hot.json", timeout=10).json()
        return [{"title": i.get('title'), "url": i.get('url'), "source": "V2EX", "time": datetime.now().isoformat(), "raw_desc": i.get('content')[:500]} for i in d[:10]], "OK"
    except Exception as e: return [], str(e)

def f_hit180():
    try:
        r = requests.get("https://www.hit180.com/", headers=get_h(), timeout=15); r.encoding = 'utf-8'
        s = BeautifulSoup(r.text, 'html.parser')
        items = []
        for a in s.select('article')[:10]:
            t = a.select_one('h2 a'); d = a.select_one('.entry-content')
            if t: items.append({"title": f"HIT180: {t.get_text(strip=True)}", "url": t['href'], "source": "HIT180", "time": datetime.now().isoformat(), "raw_desc": d.get_text(strip=True) if d else ""})
        return items, "OK"
    except Exception as e: return [], str(e)

def f_himss():
    try:
        s = BeautifulSoup(requests.get("https://www.himss.org/news", headers=get_h(), timeout=15).text, 'html.parser')
        items = []
        for c in s.select('.news-card, .views-row')[:10]:
            t = c.select_one('h3 a, .title a'); d = c.select_one('.summary, .description')
            if t: items.append({"title": f"HIMSS: {t.get_text(strip=True)}", "url": "https://www.himss.org" + t['href'] if t['href'].startswith('/') else t['href'], "source": "HIMSS", "time": datetime.now().isoformat(), "raw_desc": d.get_text(strip=True) if d else ""})
        return items, "OK"
    except Exception as e: return [], str(e)

def f_ajmc():
    try:
        s = BeautifulSoup(requests.get("https://www.ajmc.com/newsroom", headers=get_h(), timeout=15).text, 'html.parser')
        items = []
        for r in s.select('.newsroom-item, article')[:10]:
            t = r.select_one('h3 a, h2 a'); d = r.select_one('.summary, p')
            if t: items.append({"title": f"AJMC: {t.get_text(strip=True)}", "url": "https://www.ajmc.com" + t['href'] if t['href'].startswith('/') else t['href'], "source": "AJMC", "time": datetime.now().isoformat(), "raw_desc": d.get_text(strip=True) if d else ""})
        return items, "OK"
    except Exception as e: return [], str(e)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true", help="Legacy flag, now triggers JSON dump")
    parser.add_argument("--output", default="latest_scan.json", help="Output JSON path")
    args = parser.parse_args()
    
    print("Intelligence Hub: Fetching data...")
    tasks = [
        ('hackernews', lambda: f_hn(10)), ('github', f_gh), ('v2ex', f_v2ex),
        ('producthunt', lambda: parse_rss("https://www.producthunt.com/feed", "Product Hunt")),
        ('healthit', lambda: parse_rss("https://www.healthit.gov/news/feed", "HealthIT.gov")),
        ('hit180', f_hit180), ('himss', f_himss), ('ajmc', f_ajmc)
    ]
    
    res = []; stats = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        f2n = {ex.submit(f): n for n, f in tasks}
        for f in as_completed(f2n):
            n = f2n[f]
            try:
                it, st = f.result()
                res.extend(it); stats[n] = st
                print(f"  - {n}: {st}")
            except Exception as e:
                stats[n] = str(e)
                print(f"  - {n}: Error")

    output_data = {
        "metadata": {"timestamp": datetime.now().isoformat(), "sources": stats, "count": len(res)},
        "items": res
    }
    
    # Save Raw Data
    tmp_path = os.path.join(os.path.dirname(__file__), "..", "tmp")
    os.makedirs(tmp_path, exist_ok=True)
    out_file = os.path.join(tmp_path, args.output)
    
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"Data snapshot saved to: {out_file}")

if __name__ == "__main__":
    main()
