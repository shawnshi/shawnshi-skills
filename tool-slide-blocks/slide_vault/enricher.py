# -*- coding: utf-8 -*-
"""
enricher.py - 素材库增强器 (Unified Tagger & Vectorizer)
集成文本语义 (Gemini 3.1)、视觉版式 (Gemini 2.0 Vision) 与语义向量 (Embedding 2)。
"""

import os
import sys
import json
import sqlite3
import argparse
import time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

# ─── 容错机制 ───────────────────────────────────────────────────────────
from slide_vault.utils import with_retry

# 路径引导
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))


def _safe_console_text(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="backslashreplace").decode(encoding)


def _safe_print(text: str) -> None:
    print(_safe_console_text(text))

from slide_vault.config import get_db_path, load_config
from slide_vault.commercial import (
    BUYER_PERSONAS,
    DEAL_STAGES,
    EVIDENCE_TIERS,
    OBJECTION_TAGS,
    PROOF_TYPES,
    ensure_tag_columns,
    infer_commercial_metadata,
)
from slide_vault.vector_store import get_embedding, save_vector

try:
    from google import genai
    from google.genai import types
except ImportError:
    _safe_print("[错误] 请运行: pip install google-genai")
    sys.exit(1)

# 初始化 API 客户端
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    _safe_print("[错误] 未找到 GEMINI_API_KEY 环境变量。")
    sys.exit(1)

client = genai.Client(api_key=api_key)
DB_PATH = get_db_path()

# ─── 配置与 Schema ─────────────────────────────────────────────────────────

_cfg = load_config().get("models", {})
TAG_MODEL = _cfg.get("text_tagging", "gemini-3.1-flash-lite-preview")
FALLBACK_TAG_MODEL = _cfg.get("text_tagging_fallback", "gemini-2.0-flash")
VISION_MODEL = _cfg.get("vision_tagging", "gemini-2.0-flash")

TAG_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "scene": { "type": "STRING", "description": "适用场景，如：售前汇报、行业会议。" },
        "content_type": { 
            "type": "STRING", 
            "enum": ["战略规划", "解决方案", "产品功能", "客户案例", "技术架构", "数据洞察", "行业背景", "公司介绍", "项目管理"],
            "description": "基于 MSL 规范的强制内容分类。" 
        },
        "industries": { "type": "ARRAY", "items": { "type": "STRING" } },
        "keywords": { 
            "type": "ARRAY", 
            "items": { 
                "type": "STRING",
                "enum": ["HIS", "EMR", "CDSS", "Agentic", "闭环质控", "大模型", "多智能体", "数据中台", "智慧服务", "智慧管理", "医疗质量", "互联网医院", "专科专病", "互联互通", "信创", "云原生"]
            },
            "description": "基于 MSL 规范的原子化医疗词汇，只能在此列表中多选。"
        },
        "quality_score": { "type": "INTEGER", "minimum": 1, "maximum": 5 },
        "summary": { "type": "STRING", "description": "高度压缩的一句话总结。" }
        ,
        "buyer_personas": {
            "type": "ARRAY",
            "items": {
                "type": "STRING",
                "enum": BUYER_PERSONAS
            },
            "description": "这页最适合打动的决策对象，可多选。"
        },
        "deal_stage": {
            "type": "STRING",
            "enum": DEAL_STAGES,
            "description": "这页最适合使用的商业推进阶段。"
        },
        "objection_tags": {
            "type": "ARRAY",
            "items": {
                "type": "STRING",
                "enum": OBJECTION_TAGS
            },
            "description": "这页最适合回应的商业异议。"
        },
        "proof_type": {
            "type": "STRING",
            "enum": PROOF_TYPES,
            "description": "这页提供的证据类型。"
        },
        "evidence_tier": {
            "type": "STRING",
            "enum": EVIDENCE_TIERS,
            "description": "这页证据强度等级。"
        }
    },
    "required": [
        "scene",
        "content_type",
        "industries",
        "keywords",
        "quality_score",
        "summary",
        "buyer_personas",
        "deal_stage",
        "objection_tags",
        "proof_type",
        "evidence_tier"
    ]
}

VISION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "layout_type": {
            "type": "STRING",
            "enum": ["封面", "过渡页", "目录", "纯文字页", "图表页", "逻辑架构图", "对比页", "时间轴/流程", "地图页", "封底", "其他"]
        },
        "visual_description": { "type": "STRING", "description": "简短描述页面的视觉构成。" }
    },
    "required": ["layout_type", "visual_description"]
}

# ─── 核心逻辑：文本打标 ─────────────────────────────────────────────────────

@with_retry(max_retries=4)
def _generate_text_tags(prompt, model):
    return client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=TAG_SCHEMA,
            temperature=0.1
        )
    )

def enrich_text(slide):
    prompt = (
        "分析这页医疗数字化商业演示幻灯片。"
        "除了主题标签外，还要判断它最适合的决策对象、商业推进阶段、最能回应的异议、证据类型和证据强度。"
        f"标题：{slide['title']}。内容：{slide['body_text']}"
    )
    try:
        try:
            res = _generate_text_tags(prompt, TAG_MODEL)
        except Exception as e:
            # 优雅降级
            _safe_print(f"  [Fallback] 主模型失败，尝试降级到 {FALLBACK_TAG_MODEL}...")
            res = _generate_text_tags(prompt, FALLBACK_TAG_MODEL)
            
        data = json.loads(res.text)
        return {"id": slide['id'], "data": data}
    except Exception as e:
        _safe_print(f"  [!] 文本打标最终失败 (ID {slide['id']}): {e}")
        return None

# ─── 核心逻辑：视觉打标 ─────────────────────────────────────────────────────

@with_retry(max_retries=3)
def _generate_vision_tags(prompt, img):
    return client.models.generate_content(
        model=VISION_MODEL,
        contents=[prompt, img],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=VISION_SCHEMA,
            temperature=0.1
        )
    )

def enrich_vision(slide):
    thumb_path = slide.get('thumbnail_path')
    if not thumb_path or not os.path.exists(thumb_path): return False

    try:
        img = Image.open(thumb_path)
        prompt = f"识别此幻灯片的视觉版式。标题参考：{slide['title']}"
        res = _generate_vision_tags(prompt, img)
        data = json.loads(res.text)
        return {"id": slide['id'], "layout_type": data['layout_type'], "visual_description": data['visual_description']}
    except Exception as e:
        _safe_print(f"  [!] 视觉分析失败 (ID {slide['id']}): {e}")
        return None

# ─── 核心逻辑：向量化 ───────────────────────────────────────────────────────

def enrich_vector(slide):
    text = f"标题: {slide['title']}\n正文: {slide['body_text']}"
    if len(text.strip()) < 5: return False

    try:
        emb = get_embedding(text)
        if emb:
            return {"id": slide['id'], "vector": emb}
    except Exception:
        pass
    return None


def enrich_commercial(slide):
    data = infer_commercial_metadata(slide)
    return {"id": slide["id"], "data": data}

# ─── 执行器 ───────────────────────────────────────────────────────────────

def run_enrichment(mode, max_workers=5):
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    ensure_tag_columns(conn)

    if mode == "text":
        sql = """
            SELECT s.*
            FROM slides s
            LEFT JOIN tags t ON s.id = t.slide_id
            WHERE t.slide_id IS NULL
               OR t.buyer_personas IS NULL OR t.buyer_personas = ''
               OR t.deal_stage IS NULL OR t.deal_stage = ''
               OR t.objection_tags IS NULL OR t.objection_tags = ''
               OR t.proof_type IS NULL OR t.proof_type = ''
               OR t.evidence_tier IS NULL OR t.evidence_tier = ''
        """
        worker = enrich_text
    elif mode == "vision":
        sql = "SELECT s.* FROM slides s JOIN tags t ON s.id = t.slide_id WHERE s.thumbnail_path IS NOT NULL AND (t.layout_type IS NULL OR t.layout_type = '')"
        worker = enrich_vision
    elif mode == "vector":
        sql = "SELECT s.* FROM slides s LEFT JOIN slide_vectors v ON s.id = v.slide_id WHERE v.slide_id IS NULL"
        worker = enrich_vector
    elif mode == "commercial":
        sql = """
            SELECT s.*, t.summary
            FROM slides s
            JOIN tags t ON s.id = t.slide_id
            WHERE t.buyer_personas IS NULL OR t.buyer_personas = ''
               OR t.deal_stage IS NULL OR t.deal_stage = ''
               OR t.objection_tags IS NULL OR t.objection_tags = ''
               OR t.proof_type IS NULL OR t.proof_type = ''
               OR t.evidence_tier IS NULL OR t.evidence_tier = ''
        """
        worker = enrich_commercial
    else:
        return

    slides = [dict(r) for r in conn.execute(sql).fetchall()]

    if not slides:
        _safe_print(f"[{mode.upper()}] 无需处理。")
        conn.close()
        return

    _safe_print(f"[{mode.upper()}] 正在处理 {len(slides)} 条记录...")
    ok = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(worker, s): s for s in slides}
        for i, f in enumerate(as_completed(futures), 1):
            res = f.result()
            if res:
                ok += 1
                if mode == "text":
                    data = res["data"]
                    conn.execute("""
                        INSERT INTO tags
                        (
                            slide_id, scene, content_type, industries, keywords,
                            quality_score, summary, buyer_personas, deal_stage,
                            objection_tags, proof_type, evidence_tier, tagged_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(slide_id) DO UPDATE SET
                            scene = excluded.scene,
                            content_type = excluded.content_type,
                            industries = excluded.industries,
                            keywords = excluded.keywords,
                            quality_score = excluded.quality_score,
                            summary = excluded.summary,
                            buyer_personas = excluded.buyer_personas,
                            deal_stage = excluded.deal_stage,
                            objection_tags = excluded.objection_tags,
                            proof_type = excluded.proof_type,
                            evidence_tier = excluded.evidence_tier,
                            tagged_at = excluded.tagged_at
                    """, (
                        res['id'], data['scene'], data['content_type'],
                        json.dumps(data['industries'], ensure_ascii=False),
                        json.dumps(data['keywords'], ensure_ascii=False),
                        data['quality_score'], data['summary'],
                        json.dumps(data['buyer_personas'], ensure_ascii=False),
                        data['deal_stage'],
                        json.dumps(data['objection_tags'], ensure_ascii=False),
                        data['proof_type'],
                        data['evidence_tier'],
                    ))
                elif mode == "vision":
                    conn.execute("""
                        UPDATE tags SET layout_type = ?, 
                        summary = summary || ' [视觉构成: ' || ? || ']'
                        WHERE slide_id = ?
                    """, (res['layout_type'], res['visual_description'], res['id']))
                elif mode == "vector":
                    save_vector(DB_PATH, res['id'], res['vector'])
                elif mode == "commercial":
                    data = res["data"]
                    conn.execute("""
                        UPDATE tags
                        SET buyer_personas = ?,
                            deal_stage = ?,
                            objection_tags = ?,
                            proof_type = ?,
                            evidence_tier = ?
                        WHERE slide_id = ?
                    """, (
                        json.dumps(data["buyer_personas"], ensure_ascii=False),
                        data["deal_stage"],
                        json.dumps(data["objection_tags"], ensure_ascii=False),
                        data["proof_type"],
                        data["evidence_tier"],
                        res["id"],
                    ))
                 
                if mode in ["text", "vision", "commercial"]:
                    conn.commit()

            if i % 20 == 0:
                _safe_print(f"  进度: {i}/{len(slides)} (成功: {ok})")
    
    conn.close()
    _safe_print(f"[{mode.upper()}] 完成！成功: {ok}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SlideBlocks 素材库全能增强器")
    parser.add_argument("--all", action="store_true", help="运行所有增强任务")
    parser.add_argument("--text", action="store_true", help="运行文本语义打标")
    parser.add_argument("--vision", action="store_true", help="运行视觉版式识别")
    parser.add_argument("--vector", action="store_true", help="运行语义向量化")
    parser.add_argument("--commercial", action="store_true", help="运行商业语义回填（本地规则）")
    args = parser.parse_args()

    if args.all or args.text: run_enrichment("text")
    if args.all or args.vision: run_enrichment("vision", max_workers=3)
    if args.all or args.vector: run_enrichment("vector")
    if args.all or args.commercial: run_enrichment("commercial")
