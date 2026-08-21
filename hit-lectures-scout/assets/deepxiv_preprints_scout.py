"""
deepxiv_preprints_scout.py — ArXiv Preprints Recon via deepxiv-sdk
=================================================================
在确认 Python 与 deepxiv-sdk 可用后，可由当前命令环境调用。
输出结构化 Markdown 至 Response_Preprints.md。

Usage:
    python deepxiv_preprints_scout.py [--window DAYS] [--output PATH]
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

Reader = None
APIError = None
RateLimitError = None


def _load_deepxiv_sdk():
    """Defer the optional SDK import until a real retrieval starts."""
    global Reader, APIError, RateLimitError
    if Reader is not None:
        return
    from deepxiv_sdk import (
        Reader as DeepXivReader,
        APIError as DeepXivAPIError,
        RateLimitError as DeepXivRateLimitError,
    )
    Reader = DeepXivReader
    APIError = DeepXivAPIError
    RateLimitError = DeepXivRateLimitError

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
DEFAULT_OUTPUT = os.path.join(
    os.getcwd(),
    "Response_Preprints.md",
)


def build_reader() -> Reader:
    """构建 Reader 实例，优先从环境变量加载 token。"""
    _load_deepxiv_sdk()
    token = os.environ.get("DEEPXIV_TOKEN")
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
        f"> Source: deepxiv-sdk candidate metadata | Queries: {len(SEARCH_QUERIES)} | Categories: {', '.join(CATEGORIES)}",
        f"> Total unique papers: {len(papers)}",
        "> Evidence status: all entries are preprint candidates; verify the source page, version, full text, and any later peer-reviewed publication before drawing conclusions.",
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
        lines.append("- **Review status**: Preprint / not peer reviewed")

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


def main(argv=None):
    parser = argparse.ArgumentParser(description="ArXiv Preprints Recon via deepxiv-sdk")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="检索窗口天数 (default: 7)")
    parser.add_argument(
        "--include-trending",
        action="store_true",
        help="补充热门候选；仅在用户接受扩大候选范围时使用",
    )
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT, help="输出路径")
    args = parser.parse_args(argv)

    try:
        reader = build_reader()
    except ImportError:
        print(
            "deepxiv-sdk is unavailable; use the documented fallback search path.",
            file=sys.stderr,
        )
        return 4
    window = args.window

    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=window)).strftime("%Y-%m-%d")

    print(f"🔍 Recon window: {date_from} ~ {date_to} ({window} days)")
    print(f"🔍 Queries: {len(SEARCH_QUERIES)} | Categories: {CATEGORIES}")

    # Phase 1: Search
    pool = search_phase(reader, date_from, date_to)
    print(f"📊 Search phase: {len(pool)} unique papers")

    # Phase 2: Optional trending supplement
    if args.include_trending:
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
