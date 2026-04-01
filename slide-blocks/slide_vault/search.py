"""
search.py - 素材检索模块

两种检索模式：
  search_content()    - 语义检索（需要打过标签的内容页）
  search_structural() - 结构检索（按文件名识别 layout / 背景色）

返回格式统一兼容 assembler.py 的 plan：
  {"src": file_path, "page": slide_index, "title": ..., ...}
"""

import sqlite3
import json
import numpy as np
from pathlib import Path

from .config import get_db_path
from .vector_store import get_embedding, cosine_similarity


# ─── 同义词扩展表 ────────────────────────────────────────────────────
# ... (_SYNONYMS, _expand_keywords same as before)
_SYNONYMS: dict[str, list[str]] = {
    "一体化": ["一体"],
    "一体":   ["一体化"],
    "AI":     ["人工智能大模型", "大模型", "人工智能"],
    "人工智能": ["AI", "大模型", "人工智能大模型"],
    "大模型": ["AI", "人工智能", "人工智能大模型"],
    "HIS": ["医院信息系统", "核心业务系统"],
    "EMR": ["电子病历", "电子病历系统", "电子病历应用水平"],
    "电子病历": ["EMR"],
    "CDSS": ["临床决策支持", "临床决策"],
    "临床决策": ["CDSS", "临床决策支持"],
    "互联互通": ["互联互通标准化成熟度", "互通"],
    "DRG": ["疾病诊断相关分组", "诊断组"],
    "DIP": ["按病种分值付费", "病种分值"],
    "信创": ["国产化", "自主可控", "信息技术应用创新"],
}

def _expand_keywords(keywords: list[str]) -> list[str]:
    """将关键词列表展开，加入同义词（去重）"""
    expanded = list(keywords)
    for kw in keywords:
        for syn in _SYNONYMS.get(kw, []):
            if syn not in expanded:
                expanded.append(syn)
    return expanded

# ─── 混合检索核心 ────────────────────────────────────────────────────

def search_hybrid(
    scene: str = None,
    content_type: str = None,
    layout_type: str = None,
    keywords: list[str] = None,
    quality_min: int = None,
    source_file: str = None,
    use_vector: bool = True,
    limit: int = 10,
) -> list[dict]:
    """
    混合检索引擎：结合 SQL 关键词 + 向量语义检索。
    """
    db = get_db_path()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    conditions = ["1=1"]
    params = []

    if scene:
        conditions.append("t.scene = ?")
        params.append(scene)
    if content_type:
        conditions.append("t.content_type = ?")
        params.append(content_type)
    if layout_type:
        conditions.append("t.layout_type = ?")
        params.append(layout_type)
    if quality_min is not None:
        conditions.append("t.quality_score >= ?")
        params.append(quality_min)
    if source_file:
        conditions.append("s.file_name LIKE ?")
        params.append(f"%{source_file}%")

    # 1. 执行 SQL 基础检索
    sql = f"""
        SELECT
            s.id, s.file_path, s.file_name, s.slide_index,
            s.title, s.body_text, s.thumbnail_path,
            t.scene, t.content_type, t.layout_type, t.keywords,
            t.quality_score, t.summary,
            v.embedding as v_blob
        FROM slides s
        JOIN tags t ON s.id = t.slide_id
        LEFT JOIN slide_vectors v ON s.id = v.slide_id
        WHERE {' AND '.join(conditions)}
    """
    rows = conn.execute(sql, params).fetchall()
    
    # 2. 计算混合得分
    query_text = " ".join(keywords) if keywords else ""
    query_vec = get_embedding(query_text) if (use_vector and query_text) else None
    
    expanded_kw = _expand_keywords(keywords) if keywords else []
    
    results = []
    for row in rows:
        data = _format_content_row(row)
        
        # 关键词得分 (0-1)
        kw_score = 0
        if expanded_kw:
            hits = sum(1 for kw in expanded_kw if (kw in (row['title'] or "").lower() or kw in (row['keywords'] or "").lower()))
            kw_score = min(1.0, hits / len(expanded_kw))
        
        # 向量相似度得分 (0-1)
        vec_score = 0
        if query_vec and row['v_blob']:
            vec_score = cosine_similarity(row['v_blob'], query_vec)
        
        # 混合加权
        data['hybrid_score'] = kw_score * 0.4 + vec_score * 0.6
        results.append(data)

    # 3. 排序并截断
    results.sort(key=lambda x: x['hybrid_score'], reverse=True)
    conn.close()
    return results[:limit]

# ─── 结构检索（按文件名）────────────────────────────────────────────
# ... (_LAYOUT_KEYWORDS, search_structural unchanged)
_LAYOUT_KEYWORDS = ["封面页", "过渡页", "目录页", "结尾页", "二分类", "三分类", "四分类"]

def search_structural(
    layout: str = None,
    background: str = None,
    limit: int = 10,
) -> list[dict]:
    """
    按文件名识别结构型素材（封面/过渡页/目录页等）。
    """
    db = get_db_path()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    conditions = ["1=1"]
    params = []

    if layout:
        conditions.append("s.file_name LIKE ?")
        params.append(f"%{layout}%")

    if background:
        conditions.append("s.file_name LIKE ?")
        params.append(f"%{background}%")

    layout_filter = " OR ".join(
        [f"s.file_name LIKE '%{kw}%'" for kw in _LAYOUT_KEYWORDS]
    )
    conditions.append(f"({layout_filter})")

    sql = f"""
        SELECT s.id, s.file_path, s.file_name, s.slide_index, s.title, s.thumbnail_path
        FROM slides s
        WHERE {' AND '.join(conditions)}
        ORDER BY s.file_name, s.slide_index
        LIMIT ?
    """
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    return [_format_structural_row(r) for r in rows]


# ─── 格式化工具 ─────────────────────────────────────────────────────

def _format_content_row(row) -> dict:
    kw_raw = row["keywords"]
    try:
        kw = json.loads(kw_raw) if kw_raw else []
    except Exception:
        kw = [kw_raw] if kw_raw else []

    return {
        "id": row["id"],
        "src": row["file_path"],
        "page": row["slide_index"],
        "title": row["title"],
        "file_name": row["file_name"],
        "thumbnail": row["thumbnail_path"],
        "scene": row["scene"],
        "content_type": row["content_type"],
        "layout_type": row["layout_type"],
        "keywords": kw,
        "quality_score": row["quality_score"],
        "summary": row["summary"],
    }


def _format_structural_row(row) -> dict:
    fname = row["file_name"]
    layout = next((kw for kw in _LAYOUT_KEYWORDS if kw in fname), None)
    background = "深色底" if "深色底" in fname else ("浅色底" if "浅色底" in fname else None)

    return {
        "id": row["id"],
        "src": row["file_path"],
        "page": row["slide_index"],
        "title": row["title"],
        "file_name": fname,
        "thumbnail": row["thumbnail_path"],
        "layout": layout,
        "background": background,
    }

# ─── 兼容性封装 ───────────────────────────────────────────────────

def search_content(*args, **kwargs):
    """保持接口兼容，内部使用混合检索。"""
    return search_hybrid(*args, **kwargs)


# ─── 便捷打印（调试用）──────────────────────────────────────────────

def print_results(results: list[dict], mode: str = "content"):
    if not results:
        print("  （无结果）")
        return

    for i, r in enumerate(results, 1):
        print(f"\n[{i}] {r['file_name']}  第 {r['page']} 页")
        print(f"     标题：{r.get('title') or '（无）'}")
        if r.get('thumbnail'):
            print(f"     预览图：{r['thumbnail']}")

        if mode == "content":
            print(f"     场景：{r.get('scene')}  类型：{r.get('content_type')}  版式：{r.get('layout_type')}")
            print(f"     得分：{r.get('hybrid_score', 0):.2f}  质量：{r.get('quality_score')}")
            summary = r.get("summary", "")
            if summary:
                print(f"     摘要：{summary[:80]}{'...' if len(summary) > 80 else ''}")
        else:
            print(f"     版式：{r.get('layout')}  背景：{r.get('background')}")


# ─── 命令行入口 (CLI) ──────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SlideBlocks 检索客户端")
    parser.add_argument("--mode", choices=["hybrid", "structural"], default="hybrid", help="检索模式")
    
    # 混合检索参数
    parser.add_argument("--scene", help="推荐场景")
    parser.add_argument("--type", dest="content_type", help="内容分类")
    parser.add_argument("--layout", help="版式类型 (对structural模式也适用)")
    parser.add_argument("--keywords", nargs="+", help="关键词列表")
    parser.add_argument("--quality", type=int, help="最低质量分数 (1-5)")
    parser.add_argument("--no-vector", action="store_false", dest="use_vector", help="禁用向量检索，仅依赖关键词")
    parser.add_argument("--source", help="按源文件名过滤")
    
    # 结构检索参数
    parser.add_argument("--bg", dest="background", help="背景颜色过滤 (浅色底/深色底)")
    
    # 通用参数
    parser.add_argument("--limit", type=int, default=10, help="返回数量限制")
    args = parser.parse_args()

    if args.mode == "hybrid":
        results = search_hybrid(
            scene=args.scene,
            content_type=args.content_type,
            layout_type=args.layout,
            keywords=args.keywords,
            quality_min=args.quality,
            source_file=args.source,
            use_vector=args.use_vector,
            limit=args.limit
        )
        print_results(results, mode="content")
    else:
        results = search_structural(
            layout=args.layout,
            background=args.background,
            limit=args.limit
        )
        print_results(results, mode="structural")
