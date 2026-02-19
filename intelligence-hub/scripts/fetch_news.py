"""
<!-- Input: Source (hackernews/weibo/all/github/36kr), Limit, Keyword (List) -->
<!-- Output: JSON array of news items with status metadata -->
<!-- Pos: scripts/fetch_news.py. Robust multi-source data provider. -->
"""

import argparse
import json
import requests
from bs4 import BeautifulSoup
import sys
import re
import random
import concurrent.futures
from datetime import datetime

# ============================================================================
# Network Config & Robustness
# ============================================================================

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1'
]

def get_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Cache-Control': 'no-cache',
    }

# ============================================================================
# Fetchers (Data Provider Mode)
# ============================================================================

def fetch_hacker_news(limit):
    try:
        res = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10)
        ids = res.json()[:limit]
        items = []
        for id in ids:
            try:
                data = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{id}.json", timeout=5).json()
                items.append({
                    "title": data.get("title"),
                    "url": data.get("url", f"https://news.ycombinator.com/item?id={id}"),
                    "source": "Hacker News",
                    "time": datetime.fromtimestamp(data.get("time", 0)).isoformat(),
                    "raw_desc": ""
                })
            except: continue
        return items, "OK"
    except Exception as e:
        return [], f"Network Error: {str(e)}"

def fetch_36kr(limit):
    try:
        res = requests.get("https://36kr.com/newsflashes", headers=get_headers(), timeout=10)
        state_match = re.search(r'window\.initialState\s*=\s*({.*?});', res.text)
        items = []
        if state_match:
            state = json.loads(state_match.group(1))
            news_list = state.get('newsflashCatalogData', {}).get('data', {}).get('newsflashList', {}).get('data', [])
            for item in news_list[:limit]:
                items.append({
                    "title": item.get('templateData', {}).get('title'),
                    "url": f"https://36kr.com/newsflashes/{item.get('id')}",
                    "source": "36Kr",
                    "time": datetime.now().isoformat(),
                    "raw_desc": item.get('templateData', {}).get('description', '')
                })
            return items, "OK (Regex)"
        
        # BS4 Fallback
        soup = BeautifulSoup(res.text, 'html.parser')
        cards = soup.find_all('div', class_='item-info')
        for card in cards[:limit]:
            title_tag = card.find('a', class_='item-title')
            desc_tag = card.find('div', class_='item-desc')
            if title_tag:
                items.append({
                    "title": title_tag.get_text(),
                    "url": "https://36kr.com" + title_tag['href'],
                    "source": "36Kr",
                    "time": datetime.now().isoformat(),
                    "raw_desc": desc_tag.get_text() if desc_tag else ""
                })
        return items, "OK (BS4)" if items else "Parse Failure"
    except Exception as e:
        return [], f"Network/Auth Error: {str(e)}"

def fetch_weibo():
    try:
        res = requests.get("https://weibo.com/ajax/side/hotSearch", headers=get_headers(), timeout=10)
        data = res.json().get('data', {}).get('realtime', [])
        return [{
            "title": i.get('note', i.get('word')),
            "url": f"https://s.weibo.com/weibo?q=%23{i.get('word')}%23",
            "source": "Weibo",
            "time": datetime.now().isoformat(),
            "raw_desc": f"Category: {i.get('category', 'Hot')}"
        } for i in data[:15]], "OK"
    except Exception as e:
        return [], f"Scraping Blocked: {str(e)}"

def fetch_github_trending():
    try:
        res = requests.get("https://github.com/trending", headers=get_headers(), timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        items = []
        for article in soup.select('article.Box-row')[:10]:
            title_tag = article.select_one('h2 a')
            desc_tag = article.select_one('p')
            if title_tag:
                items.append({
                    "title": title_tag.get_text(strip=True),
                    "url": "https://github.com" + title_tag['href'],
                    "source": "GitHub",
                    "time": datetime.now().isoformat(),
                    "raw_desc": desc_tag.get_text(strip=True) if desc_tag else ""
                })
        return items, "OK"
    except Exception as e:
        return [], f"GitHub Timeout: {str(e)}"

def fetch_v2ex():
    try:
        # V2EX Hot Topics API
        res = requests.get("https://www.v2ex.com/api/topics/hot.json", timeout=10)
        data = res.json()
        return [{
            "title": i.get('title'),
            "url": i.get('url'),
            "source": "V2EX",
            "time": datetime.now().isoformat(),
            "raw_desc": i.get('content')[:200]
        } for i in data[:10]], "OK"
    except Exception as e:
        return [], f"V2EX API Error: {str(e)}"

def fetch_product_hunt():
    try:
        # PH Scraper (using homepage as fallback for API)
        res = requests.get("https://www.producthunt.com/", headers=get_headers(), timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        items = []
        # Look for product titles and links
        for post in soup.select('[data-test="post-item"]')[:10]:
            title_tag = post.select_one('[data-test="post-name"]')
            desc_tag = post.select_one('[data-test="post-tagline"]')
            url_tag = post.select_one('a')
            if title_tag:
                items.append({
                    "title": f"PH: {title_tag.get_text(strip=True)}",
                    "url": "https://www.producthunt.com" + url_tag['href'] if url_tag else "",
                    "source": "Product Hunt",
                    "time": datetime.now().isoformat(),
                    "raw_desc": desc_tag.get_text(strip=True) if desc_tag else ""
                })
        return items, "OK" if items else "PH Scrape Failure"
    except Exception as e:
        return [], f"Product Hunt Error: {str(e)}"

import os

# ============================================================================
# Main Logic (Provider Interface)
# ============================================================================

def save_to_markdown(data):
    today = datetime.now().strftime("%Y%m%d")
    save_path = f"C:\\Users\\shich\\.gemini\\MEMORY\\news\\intelligence_{today}_briefing.md"
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    content = [
        f"# Intelligence Hub: 战略情报二阶推演简报 [{datetime.now().strftime('%Y-%m-%d')}]",
        "",
        "## 1. 扫描元数据 (Scan Metadata)",
        f"- **扫描时间**: {data['metadata']['timestamp']}",
        f"- **信号来源**: {', '.join(data['metadata']['sources'].keys())} (Total {data['metadata']['count']} Items)",
        "- **分析引擎**: Intelligence Hub V3.1",
        "",
        "## 2. 战略锚点：二阶推演 (Digest)",
        "> 💡 [WAITING FOR AGENT REFINEMENT] 请 Agent 基于 memory.md 执行二阶推演。",
        "",
        "## 3. 核心判词 (Punchline)",
        "> 💡 [WAITING FOR AGENT REFINEMENT]",
        "",
        "---",
        "",
        "## 4. 原始信号清单与简介 (Raw Signals & Abstracts)",
        ""
    ]
    
    # Group by source
    by_source = {}
    for item in data['items']:
        src = item['source']
        if src not in by_source: by_source[src] = []
        by_source[src].append(item)
    
    for src, items in by_source.items():
        content.append(f"### {src}")
        for i, item in enumerate(items, 1):
            desc = item.get('raw_desc', '').strip()
            # Clean up desc: remove newlines, truncate
            desc = desc.replace('\r', '').replace('\n', ' ')
            abstract = (desc[:100] + '...') if len(desc) > 100 else (desc if desc else "No description available.")
            content.append(f"{i}. **[{src}]** {item['title']} ({item['url']})")
            content.append(f"   - *简介*: {abstract}")
        content.append("")

    content.append("---")
    content.append("## 📂 归档记录")
    content.append(f"- **归档路径**: {save_path}")
    content.append("- **状态**: Persistent (Pending Digest)")

    with open(save_path, "w", encoding="utf-8") as f:
        f.write("\n".join(content))
    return save_path

def main():
    parser = argparse.ArgumentParser(description="Intelligence Data Provider V3.1")
    parser.add_argument("--source", choices=['hackernews', '36kr', 'weibo', 'github', 'v2ex', 'producthunt', 'all'], default='all')
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--save", action="store_true", help="Auto-save to MEMORY/news/ as Markdown")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    results = []
    status_report = {}
    tasks = []

    mapping = {
        'hackernews': lambda: fetch_hacker_news(args.limit),
        'github': fetch_github_trending,
        'v2ex': fetch_v2ex,
        'producthunt': fetch_product_hunt,
        '36kr': lambda: fetch_36kr(args.limit),
        'weibo': fetch_weibo
    }

    if args.source == 'all':
        # Default strategic quartet
        for name in ['hackernews', 'github', 'v2ex', 'producthunt']:
            tasks.append((name, mapping[name]))
    else:
        tasks.append((args.source, mapping[args.source]))

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        future_to_source = {executor.submit(func): name for name, func in tasks}
        for future in concurrent.futures.as_completed(future_to_source):
            src = future_to_source[future]
            try:
                items, status = future.result()
                results.extend(items)
                status_report[src] = status
            except Exception as e:
                status_report[src] = f"Fatal Exception: {str(e)}"

    # Always output JSON for the Agent to parse
    output_data = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "sources": status_report,
            "count": len(results)
        },
        "items": results
    }
    
    # Save if requested
    if args.save:
        save_path = save_to_markdown(output_data)
        output_data["metadata"]["saved_path"] = save_path
        if args.debug:
            print(f"DEBUG: Saved to {save_path}")

    print(json.dumps(output_data, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
