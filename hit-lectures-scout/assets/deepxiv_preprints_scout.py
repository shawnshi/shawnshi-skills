"""
deepxiv_preprints_scout.py — ArXiv Preprints Recon via deepxiv-sdk
=================================================================
由 hit-lectures-scout SKILL Phase 1 通过 run_shell_command 调用。
输出结构化 Markdown 至 Response_Preprints.md。

Usage:
    python deepxiv_preprints_scout.py [--window DAYS] [--output PATH]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

try:
    from deepxiv_sdk import Reader, APIError, RateLimitError
except ImportError:
    print("❌ deepxiv-sdk 未安装。请执行: pip install deepxiv-sdk", file=sys.stderr)
    sys.exit(1)

# ============================================================
# 检索配置 — 可通过 task_preprints_config.md 同步维护
# ============================================================
SEARCH_QUERIES = [
    "clinical AI large language model",
    "medical foundation model multimodal",
    "healthcare reasoning agent workflow",
    "biomedical knowledge graph LLM",
    "digital health federated learning",
    "radiology AI diagnostic imaging",
    "EHR clinical NLP transformer",
]

CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "q-bio.QM"]

MAX_PER_QUERY = 15          # 每个 query 拉取上限
TOP_N_ENRICH = 30           # brief() 提纯数量上限
DEFAULT_WINDOW = 7          # 默认检索窗口 (天)
FALLBACK_WINDOW = 14        # 弹性降维窗口

DEFAULT_OUTPUT = os.path.join(
    os.path.expanduser("~"),
    ".gemini", "tmp", "playgrounds", "Response_Preprints.md",
)


def build_reader() -> Reader:
    """构建 Reader 实例，优先从环境变量加载 token。"""
    token = os.environ.get("DEEPXIV_TOKEN")
    if not token:
        # 尝试从 ~/.env 手动解析
        env_path = os.path.join(os.path.expanduser("~"), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DEEPXIV_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        break
    if not token:
        print("⚠️  DEEPXIV_TOKEN 未配置。将尝试免认证模式（功能受限）。", file=sys.stderr)
    return Reader(token=token, timeout=45, max_retries=3)


def search_phase(reader: Reader, date_from: str, date_to: str) -> dict:
    """Phase 1: 多关键词行走 + 按 arxiv_id 先验去重。"""
    pool: dict = {}  # arxiv_id -> paper_dict
    for q in SEARCH_QUERIES:
        try:
            results = reader.search(
                query=q,
                size=MAX_PER_QUERY,
                search_mode="hybrid",
                categories=CATEGORIES,
                date_from=date_from,
                date_to=date_to,
            )
            for paper in results.get("results", []):
                aid = paper.get("arxiv_id")
                if aid and aid not in pool:
                    paper["_source_query"] = q
                    pool[aid] = paper
        except RateLimitError:
            print(f"⚠️  Rate limit hit on query '{q}', skipping remaining queries.", file=sys.stderr)
            break
        except APIError as e:
            print(f"⚠️  Search error for '{q}': {e}", file=sys.stderr)
    return pool


def trending_phase(reader: Reader, pool: dict) -> dict:
    """Phase 2: 热门论文补充。"""
    try:
        trending = reader.trending(days=7, limit=30)
        for paper in trending.get("papers", []):
            aid = paper.get("arxiv_id")
            if aid and aid not in pool:
                paper["_source_query"] = "__trending__"
                pool[aid] = paper
    except APIError as e:
        print(f"⚠️  Trending fetch error: {e}", file=sys.stderr)
    return pool


def enrich_phase(reader: Reader, pool: dict) -> list:
    """Phase 3: brief() 批量提纯 Top N 论文。"""
    # 排序: citation desc, score desc
    sorted_papers = sorted(
        pool.values(),
        key=lambda p: (
            p.get("citations", p.get("citation", 0)),
            p.get("score", 0),
        ),
        reverse=True,
    )[:TOP_N_ENRICH]

    enriched = []
    for paper in sorted_papers:
        aid = paper.get("arxiv_id")
        try:
            brief_data = reader.brief(aid)
            paper.update(brief_data)
        except APIError:
            pass  # brief 失败不影响主流程
        enriched.append(paper)
    return enriched


def render_markdown(papers: list, date_from: str, date_to: str) -> str:
    """Phase 4: 渲染结构化 Markdown 报告。"""
    lines = [
        f"# ArXiv Preprints Recon ({date_from} ~ {date_to})",
        "",
        f"> Generated: {datetime.now().isoformat()}",
        f"> Source: deepxiv-sdk v0.2.4 | Queries: {len(SEARCH_QUERIES)} | Categories: {', '.join(CATEGORIES)}",
        f"> Total unique papers: {len(papers)}",
        "",
    ]

    for i, p in enumerate(papers, 1):
        aid = p.get("arxiv_id", "N/A")
        lines.append(f"## {i}. {p.get('title', 'N/A')}")
        lines.append(f"- **arXiv ID**: [{aid}](https://arxiv.org/abs/{aid})")
        lines.append(f"- **Citations**: {p.get('citations', p.get('citation', 0))}")

        cats = p.get("categories", "N/A")
        if isinstance(cats, list):
            cats = ", ".join(cats)
        lines.append(f"- **Categories**: {cats}")

        lines.append(f"- **Published**: {p.get('publish_at', 'N/A')}")

        if p.get("tldr"):
            lines.append(f"- **TLDR**: {p['tldr']}")
        if p.get("abstract"):
            abstract = p["abstract"][:300].replace("\n", " ")
            lines.append(f"- **Abstract (excerpt)**: {abstract}...")
        if p.get("github_url"):
            lines.append(f"- **GitHub**: {p['github_url']}")
        if p.get("src_url"):
            lines.append(f"- **PDF**: {p['src_url']}")
        if p.get("keywords"):
            kw = p["keywords"]
            if isinstance(kw, list):
                kw = ", ".join(kw)
            lines.append(f"- **Keywords**: {kw}")

        source = p.get("_source_query", "")
        if source == "__trending__":
            lines.append("- **Signal**: 🔥 Trending")
        elif source:
            lines.append(f"- **Matched Query**: {source}")

        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="ArXiv Preprints Recon via deepxiv-sdk")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="检索窗口天数 (default: 7)")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT, help="输出路径")
    args = parser.parse_args()

    reader = build_reader()
    window = args.window

    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=window)).strftime("%Y-%m-%d")

    print(f"🔍 Recon window: {date_from} ~ {date_to} ({window} days)")
    print(f"🔍 Queries: {len(SEARCH_QUERIES)} | Categories: {CATEGORIES}")

    # Phase 1: Search
    pool = search_phase(reader, date_from, date_to)
    print(f"📊 Search phase: {len(pool)} unique papers")

    # 弹性降维: 若不足 5 篇，扩大窗口
    if len(pool) < 5 and window < FALLBACK_WINDOW:
        print(f"⚠️  不足 5 篇，自动扩大窗口至 {FALLBACK_WINDOW} 天")
        date_from = (datetime.now() - timedelta(days=FALLBACK_WINDOW)).strftime("%Y-%m-%d")
        pool = search_phase(reader, date_from, date_to)
        print(f"📊 扩展检索后: {len(pool)} unique papers")

    # Phase 2: Trending supplement
    pool = trending_phase(reader, pool)
    print(f"📊 After trending: {len(pool)} unique papers")

    # Phase 3: Enrich
    enriched = enrich_phase(reader, pool)
    print(f"📊 Enriched top {len(enriched)} papers")

    # Phase 4: Render
    report = render_markdown(enriched, date_from, date_to)

    # Write output
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"✅ Report written to {args.output}")


if __name__ == "__main__":
    main()
