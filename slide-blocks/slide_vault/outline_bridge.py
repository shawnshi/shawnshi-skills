# -*- coding: utf-8 -*-
"""
outline_bridge.py - Bridge presentation-architect outlines into SlideBlocks plans.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .commercial import DECK_MODE_PRESETS, infer_commercial_metadata
from .config import get_output_dir
from .planner import _canonicalize_slide_paths  # reuse path normalization
from .search import search_hybrid

try:
    from engine.template_manifest import load_template_manifest, normalize_template_manifest
except Exception:
    from ..engine.template_manifest import load_template_manifest, normalize_template_manifest  # type: ignore

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent / "manifests" / "light-default.json"
DEFAULT_SOURCE_CLUSTERS = Path(__file__).resolve().parent.parent / "references" / "source-clusters.json"
DEFAULT_SOURCE_CLUSTER_SCHEMA = Path(__file__).resolve().parent.parent / "references" / "source-clusters.schema.json"
DEFAULT_BRIDGE_CONFIG = Path(__file__).resolve().parent.parent / "references" / "outline-bridge-config.json"
SLIDE_SPLIT_RE = re.compile(r"(?=^##\s+Slide\s+\d+(?:\s+of\s+\d+|:).*$)", re.MULTILINE)


def _slugify(value: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value.strip(), flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "outline"


def _read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@lru_cache(maxsize=8)
def _load_bridge_settings(path_str: str) -> dict:
    defaults = {
        "version": "1.0.0",
        "confidence": {
            "min_confidence_default": 0.35,
            "high_confidence_threshold": 0.5,
        },
        "search": {
            "enable_query_cache": True,
            "max_source_hints": 3,
            "max_preferred_content_queries": 2,
            "max_preferred_layout_queries": 2,
            "max_preferred_proof_queries": 2,
            "max_search_variants": 18,
            "candidate_cap": 12,
        },
        "scoring": {
            "token_overlap_step": 0.03,
            "token_overlap_cap": 0.18,
            "headline_overlap_step": 0.04,
            "headline_overlap_cap": 0.12,
            "narrative_overlap_step": 0.03,
            "narrative_overlap_cap": 0.12,
            "visual_overlap_step": 0.02,
            "visual_overlap_cap": 0.08,
            "trust_anchor_step": 0.05,
            "trust_anchor_cap": 0.15,
            "source_proof_preference": 0.05,
            "source_layout_preference": 0.05,
            "source_content_preference": 0.05,
            "proof_match": 0.05,
            "layout_match": 0.05,
            "objection_match": 0.03,
            "negative_content_penalty": 0.12,
            "negative_term_penalty_step": 0.08,
            "negative_term_penalty_cap": 0.16,
        },
    }
    path = Path(path_str)
    if not path.exists():
        return defaults
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"Bridge config must be an object: {path}")
    merged = defaults.copy()
    for section in ("confidence", "search", "scoring"):
        merged_section = defaults[section].copy()
        if isinstance(payload.get(section), dict):
            merged_section.update(payload[section])
        merged[section] = merged_section
    merged["version"] = str(payload.get("version", defaults["version"]))
    return merged


DEFAULT_MIN_CONFIDENCE = _load_bridge_settings(str(DEFAULT_BRIDGE_CONFIG.resolve()))["confidence"]["min_confidence_default"]


def _validate_source_clusters_payload(payload: dict, schema_path: Path) -> None:
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("source-clusters.json must be a JSON object")
    for field in schema.get("root_required", []):
        if field not in payload:
            raise ValueError(f"source-clusters.json missing required root field: {field}")
    clusters = payload.get("clusters")
    if not isinstance(clusters, list):
        raise ValueError("source-clusters.json field 'clusters' must be a list")
    required_fields = schema.get("cluster_required", [])
    array_fields = set(schema.get("cluster_array_fields", []))
    for index, cluster in enumerate(clusters):
        if not isinstance(cluster, dict):
            raise ValueError(f"Cluster #{index} must be an object")
        for field in required_fields:
            if field not in cluster:
                raise ValueError(f"Cluster '{cluster.get('name', index)}' missing required field: {field}")
        if not isinstance(cluster.get("name"), str) or not cluster.get("name").strip():
            raise ValueError(f"Cluster #{index} field 'name' must be a non-empty string")
        for field in array_fields:
            value = cluster.get(field)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"Cluster '{cluster.get('name', index)}' field '{field}' must be a list[str]")


@lru_cache(maxsize=4)
def _load_source_clusters(path_str: str) -> list[dict]:
    path = Path(path_str)
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    _validate_source_clusters_payload(payload, DEFAULT_SOURCE_CLUSTER_SCHEMA)
    clusters = payload.get("clusters", []) if isinstance(payload, dict) else []
    normalized = []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        normalized.append(
            {
                "name": cluster.get("name", ""),
                "match_terms": [term for term in cluster.get("match_terms", []) if isinstance(term, str)],
                "source_patterns": [term for term in cluster.get("source_patterns", []) if isinstance(term, str)],
                "preferred_proof_types": [term for term in cluster.get("preferred_proof_types", []) if isinstance(term, str)],
                "preferred_layouts": [term for term in cluster.get("preferred_layouts", []) if isinstance(term, str)],
                "preferred_content_types": [term for term in cluster.get("preferred_content_types", []) if isinstance(term, str)],
                "negative_content_types": [term for term in cluster.get("negative_content_types", []) if isinstance(term, str)],
                "negative_terms": [term for term in cluster.get("negative_terms", []) if isinstance(term, str)],
            }
        )
    return normalized


def _extract_field(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _extract_section(start_marker: str, end_markers: list[str], text: str) -> str | None:
    pattern = re.escape(start_marker) + r"\s*(.*?)(?=" + "|".join(re.escape(m) for m in end_markers) + r"|$)"
    match = re.search(pattern, text, flags=re.DOTALL)
    return match.group(1).strip() if match else None


def _extract_trust_anchor(block: str) -> str:
    match = re.search(r"Trust_Anchor:\s*\[Ref:\s*([^\]]+)\]", block, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"Trust_Anchor\s*:\s*(.+)", block, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _expand_reference_terms(value: str) -> list[str]:
    if not value:
        return []
    normalized = re.sub(r"[_\-]+", " ", value)
    parts = re.split(r"[\s/|]+", normalized)
    tokens = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        tokens.append(part)
        camel_parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", part)
        for camel in camel_parts:
            camel = camel.strip()
            if camel and camel not in tokens:
                tokens.append(camel)
    return tokens


def parse_outline(path: Path) -> dict:
    content = _read_text(path)
    topic = _extract_field(r"^\*\*Topic\*\*:\s*(.+)$", content) or _extract_field(r"^#\s*Slide Deck Outline:\s*(.+)$", content)
    audience = _extract_field(r"^\*\*Audience\*\*:\s*(.+)$", content)
    style = _extract_field(r"^\*\*Style\*\*:\s*(.+)$", content)
    language = _extract_field(r"^\*\*Language\*\*:\s*(.+)$", content)
    slide_count_raw = _extract_field(r"^\*\*Slide Count\*\*:\s*(.+)$", content)
    slide_count = None
    if slide_count_raw:
        m = re.search(r"(\d+)", slide_count_raw)
        slide_count = int(m.group(1)) if m else None

    slide_blocks = [block.strip() for block in SLIDE_SPLIT_RE.split(content) if block.strip().startswith("## Slide")]
    slides = []
    for idx, block in enumerate(slide_blocks, start=1):
        slide_type = _extract_field(r"^\*\*Type\*\*:\s*(.+)$", block)
        title = _extract_field(r"^- \*\*Title\*\*:\s*(.+)$", block) or _extract_field(r"^Headline:\s*(.+)$", block)
        subtitle = _extract_field(r"^- \*\*Subtitle\*\*:\s*(.+)$", block) or _extract_field(r"^Sub-headline:\s*(.+)$", block)
        filename = _extract_field(r"^\*\*Filename\*\*:\s*(.+)$", block)
        narrative_goal = _extract_section("// NARRATIVE GOAL", ["// PUNCHLINE", "// KEY CONTENT", "// VISUAL", "// LAYOUT", "// Script"], block)
        punchline = _extract_section("// PUNCHLINE", ["// KEY CONTENT", "// VISUAL", "// LAYOUT", "// Script"], block)
        visual = _extract_section("// VISUAL", ["// LAYOUT", "// Script"], block)
        layout = _extract_section("// LAYOUT", ["// Script"], block)
        script = _extract_section("// Script", [], block)
        body_block = _extract_section("// KEY CONTENT", ["// VISUAL_CODE", "// VISUAL", "// LAYOUT", "// Script"], block)
        trust_anchor = _extract_trust_anchor(body_block or block)

        body_points = []
        if body_block:
            for bullet in re.findall(r"^-+\s*(.+)$", body_block, flags=re.MULTILINE):
                body_points.append(bullet.strip())
            body_match = re.search(r"Body(?:/Data)?:\s*(.*)", body_block, flags=re.DOTALL)
            if body_match and not body_points:
                raw = body_match.group(1).strip()
                for line in raw.splitlines():
                    line = line.strip().lstrip("-").strip()
                    if line and not line.startswith("Trust_Anchor"):
                        body_points.append(line)

        if not body_points:
            for point in re.findall(r"^- \*\*Point \d+\*\*:\s*(.+)$", block, flags=re.MULTILINE):
                body_points.append(point.strip())

        slides.append(
            {
                "index": idx,
                "type": (slide_type or "").lower(),
                "title": title or f"Slide {idx}",
                "subtitle": subtitle or "",
                "filename": filename,
                "narrative_goal": narrative_goal or "",
                "punchline": punchline or "",
                "body_points": body_points,
                "visual": visual or "",
                "layout": layout or "",
                "script": script or "",
                "trust_anchor": trust_anchor,
                "raw": block,
            }
        )

    return {
        "topic": topic or path.parent.name,
        "audience": audience or "",
        "style": style or "",
        "language": language or "",
        "slide_count": slide_count or len(slides),
        "slides": slides,
    }


def _infer_persona(audience: str) -> str:
    audience = (audience or "").lower()
    if any(token in audience for token in ["董事长", "ceo", "board", "chairman"]):
        return "chairman"
    if any(token in audience for token in ["院长", "president"]):
        return "president"
    if any(token in audience for token in ["cio", "信息", "it"]):
        return "cio"
    if any(token in audience for token in ["临床", "医生", "专家", "clinical"]):
        return "clinical_expert"
    if any(token in audience for token in ["采购", "招标", "procurement"]):
        return "procurement"
    return "president"


def _infer_deck_mode(persona: str) -> str:
    return {
        "chairman": "board_strategy",
        "president": "hospital_leadership",
        "cio": "cio_architecture",
        "clinical_expert": "clinical_expert",
        "procurement": "bid_response",
    }.get(persona, "hospital_leadership")


def _infer_layout_type(slide: dict) -> str | None:
    text = "\n".join([slide.get("title", ""), slide.get("subtitle", ""), slide.get("visual", ""), slide.get("layout", "")]).lower()
    if any(token in text for token in ["架构", "分层", "蓝图", "中台", "飞轮"]):
        return "逻辑架构图"
    if any(token in text for token in ["对比", "矩阵"]):
        return "对比页"
    if any(token in text for token in ["流程", "闭环", "执行", "路径", "链"]):
        return "时间轴/流程"
    if any(token in text for token in ["图表", "数据卡", "坐标", "趋势"]):
        return "图表页"
    return None


def _infer_search_profile(slide: dict, persona: str) -> dict:
    body = "\n".join(slide.get("body_points", []))
    trust_anchor = slide.get("trust_anchor", "")
    trust_terms = _expand_reference_terms(trust_anchor)
    synthetic = {
        "title": slide.get("title"),
        "body_text": "\n".join(
            [
                slide.get("subtitle", ""),
                slide.get("narrative_goal", ""),
                slide.get("punchline", ""),
                trust_anchor,
                body,
                slide.get("visual", ""),
                slide.get("layout", ""),
            ]
        ),
        "summary": body,
    }
    meta = infer_commercial_metadata(synthetic)
    if persona not in meta["buyer_personas"]:
        meta["buyer_personas"].insert(0, persona)
    keywords = [
        slide.get("title", ""),
        slide.get("subtitle", ""),
        slide.get("punchline", ""),
        slide.get("narrative_goal", ""),
        slide.get("visual", ""),
        slide.get("layout", ""),
    ]
    keywords.extend(slide.get("body_points", []))
    keywords.extend(trust_terms)
    tokens = []
    for item in keywords:
        if not item:
            continue
        tokens.extend(re.split(r"[\s，。,；：、/|]+", item))
    tokens = [token.strip() for token in tokens if token.strip()]
    return {
        "keywords": tokens[:18],
        "proof_type": meta["proof_type"],
        "objection_tags": meta["objection_tags"],
        "deal_stage": meta["deal_stage"],
        "layout_type": _infer_layout_type(slide),
        "headline_terms": _tokenize([slide.get("title", ""), slide.get("subtitle", ""), slide.get("punchline", "")]),
        "narrative_terms": _tokenize([slide.get("narrative_goal", ""), *slide.get("body_points", [])]),
        "trust_anchor": trust_anchor,
        "trust_terms": [token.lower() for token in trust_terms],
        "visual_terms": _tokenize([slide.get("visual", ""), slide.get("layout", "")]),
    }


def _tokenize(values: list[str]) -> list[str]:
    tokens = []
    for value in values:
        if not value:
            continue
        parts = re.split(r"[\s，。,；：、/|()（）\-_:]+", value.lower())
        for part in parts:
            part = part.strip()
            if len(part) >= 2:
                tokens.append(part)
    return tokens


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        if not value or value in seen:
            continue
        ordered.append(value)
        seen.add(value)
    return ordered


@lru_cache(maxsize=256)
def _search_hybrid_cached(payload_json: str) -> str:
    payload = json.loads(payload_json)
    results = search_hybrid(**payload)
    return json.dumps(results, ensure_ascii=False)


def _infer_source_profile(profile: dict, explicit_source: str | None, source_clusters_path: Path) -> dict:
    search_space = " ".join(
        [
            explicit_source or "",
            profile.get("trust_anchor", ""),
            " ".join(profile.get("trust_terms", [])),
            " ".join(profile.get("keywords", [])),
        ]
    ).lower()
    patterns = []
    cluster_names = []
    preferred_proof_types = []
    preferred_layouts = []
    preferred_content_types = []
    negative_content_types = []
    negative_terms = []
    if explicit_source:
        patterns.append(explicit_source)
    for rule in _load_source_clusters(str(source_clusters_path.resolve())):
        if any(term.lower() in search_space for term in rule["match_terms"]):
            cluster_names.append(rule.get("name", ""))
            patterns.extend(rule["source_patterns"])
            preferred_proof_types.extend(rule.get("preferred_proof_types", []))
            preferred_layouts.extend(rule.get("preferred_layouts", []))
            preferred_content_types.extend(rule.get("preferred_content_types", []))
            negative_content_types.extend(rule.get("negative_content_types", []))
            negative_terms.extend(rule.get("negative_terms", []))
    return {
        "cluster_names": _dedupe_keep_order(cluster_names),
        "source_patterns": _dedupe_keep_order(patterns),
        "preferred_proof_types": _dedupe_keep_order(preferred_proof_types),
        "preferred_layouts": _dedupe_keep_order(preferred_layouts),
        "preferred_content_types": _dedupe_keep_order(preferred_content_types),
        "negative_content_types": _dedupe_keep_order(negative_content_types),
        "negative_terms": _dedupe_keep_order(negative_terms),
    }


def _bridge_score_breakdown(candidate: dict, profile: dict, source_profile: dict, bridge_settings: dict) -> dict:
    scoring = bridge_settings["scoring"]
    candidate_tokens = _tokenize(
        [
            candidate.get("title", ""),
            candidate.get("summary", ""),
            " ".join(candidate.get("keywords", [])),
            candidate.get("layout_type", ""),
            candidate.get("content_type", ""),
        ]
    )
    candidate_blob = " ".join(
        [
            candidate.get("title", ""),
            candidate.get("summary", ""),
            " ".join(candidate.get("keywords", [])),
            candidate.get("file_name", ""),
            candidate.get("layout_type", ""),
            candidate.get("content_type", ""),
        ]
    ).lower()
    candidate_content_type = candidate.get("content_type", "")
    query_tokens = _tokenize(profile.get("keywords", []))
    overlap = len(set(query_tokens) & set(candidate_tokens))
    headline_overlap = len(set(profile.get("headline_terms", [])) & set(candidate_tokens))
    narrative_overlap = len(set(profile.get("narrative_terms", [])) & set(candidate_tokens))
    visual_overlap = len(set(profile.get("visual_terms", [])) & set(candidate_tokens))
    trust_hits = sum(1 for term in profile.get("trust_terms", []) if term in candidate_blob)
    negative_hits = sum(1 for term in source_profile.get("negative_terms", []) if term.lower() in candidate_blob)
    breakdown = {
        "hybrid_score": round(float(candidate.get("hybrid_score", 0)), 4),
        "token_overlap": min(scoring["token_overlap_cap"], overlap * scoring["token_overlap_step"]),
        "headline_overlap": min(scoring["headline_overlap_cap"], headline_overlap * scoring["headline_overlap_step"]),
        "narrative_overlap": min(scoring["narrative_overlap_cap"], narrative_overlap * scoring["narrative_overlap_step"]),
        "visual_overlap": min(scoring["visual_overlap_cap"], visual_overlap * scoring["visual_overlap_step"]),
        "trust_anchor_match": min(scoring["trust_anchor_cap"], trust_hits * scoring["trust_anchor_step"]),
        "source_proof_preference": 0.0,
        "source_layout_preference": 0.0,
        "source_content_preference": 0.0,
        "proof_match": 0.0,
        "layout_match": 0.0,
        "objection_match": 0.0,
        "negative_content_penalty": 0.0,
        "negative_penalty": min(scoring["negative_term_penalty_cap"], negative_hits * scoring["negative_term_penalty_step"]),
    }
    if candidate.get("proof_type") in source_profile.get("preferred_proof_types", []):
        breakdown["source_proof_preference"] = scoring["source_proof_preference"]
    if candidate.get("layout_type") in source_profile.get("preferred_layouts", []):
        breakdown["source_layout_preference"] = scoring["source_layout_preference"]
    if candidate_content_type in source_profile.get("preferred_content_types", []):
        breakdown["source_content_preference"] = scoring["source_content_preference"]
    if candidate_content_type in source_profile.get("negative_content_types", []):
        breakdown["negative_content_penalty"] = scoring["negative_content_penalty"]
    if candidate.get("proof_type") == profile.get("proof_type"):
        breakdown["proof_match"] = scoring["proof_match"]
    if profile.get("layout_type") and candidate.get("layout_type") == profile.get("layout_type"):
        breakdown["layout_match"] = scoring["layout_match"]
    if set(profile.get("objection_tags", [])) & set(candidate.get("objection_tags", [])):
        breakdown["objection_match"] = scoring["objection_match"]
    breakdown["total"] = round(
        breakdown["hybrid_score"]
        + breakdown["token_overlap"]
        + breakdown["headline_overlap"]
        + breakdown["narrative_overlap"]
        + breakdown["visual_overlap"]
        + breakdown["trust_anchor_match"]
        + breakdown["source_proof_preference"]
        + breakdown["source_layout_preference"]
        + breakdown["source_content_preference"]
        + breakdown["proof_match"]
        + breakdown["layout_match"]
        + breakdown["objection_match"]
        - breakdown["negative_content_penalty"]
        - breakdown["negative_penalty"],
        4,
    )
    return breakdown


def _filter_candidate_rows(rows: list[dict], source_profile: dict) -> tuple[list[dict], dict]:
    negative_content_types = set(source_profile.get("negative_content_types", []))
    if not negative_content_types:
        return rows, {"removed_count": 0, "fallback_used": False}
    filtered = [row for row in rows if row.get("content_type") not in negative_content_types]
    removed_count = max(0, len(rows) - len(filtered))
    if filtered:
        return filtered, {"removed_count": removed_count, "fallback_used": False}
    return rows, {"removed_count": removed_count, "fallback_used": True}


def _confidence_band(value: float, min_confidence: float, bridge_settings: dict) -> str:
    if value >= bridge_settings["confidence"]["high_confidence_threshold"]:
        return "high"
    if value >= min_confidence:
        return "medium"
    return "low"


def _build_decision_audit(
    *,
    status: str,
    reason: str,
    min_confidence: float,
    top_candidate: dict | None,
    alternates: list[dict],
) -> dict:
    top_confidence = top_candidate.get("bridge_confidence") if top_candidate else None
    top_band = top_candidate.get("bridge_confidence_band") if top_candidate else None
    top_title = top_candidate.get("title") if top_candidate else None
    top_type = top_candidate.get("content_type") if top_candidate else None
    if reason == "no_candidates":
        manual_action = "放宽来源限制，或补充更直接的 Trust Anchor / Headline 关键词。"
    elif reason == "below_min_confidence":
        manual_action = "优先审阅 alternates；若仍不合适，再改写该页意图或放宽 min_confidence。"
    elif status == "matched" and top_band == "medium":
        manual_action = "建议人工复核该页，确认叙事、证据类型和来源语境是否真的匹配。"
    else:
        manual_action = "无需额外处理。"
    return {
        "status": status,
        "reason": reason,
        "min_confidence": min_confidence,
        "top_candidate_confidence": top_confidence,
        "top_candidate_band": top_band,
        "top_candidate_title": top_title,
        "top_candidate_type": top_type,
        "alternate_count": len(alternates),
        "manual_action": manual_action,
    }


def _search_slide_candidate(
    slide: dict,
    *,
    persona: str,
    deck_mode: str,
    source: str | None,
    used_ids: set[int],
    limit: int,
    use_vector: bool,
    min_confidence: float,
    source_clusters_path: Path,
    bridge_settings: dict,
) -> tuple[dict | None, dict, list[dict]]:
    profile = _infer_search_profile(slide, persona)
    source_profile = _infer_source_profile(profile, source, source_clusters_path)
    search_settings = bridge_settings["search"]
    source_hints = source_profile["source_patterns"]
    query = {
        "persona": persona,
        "deck_mode": deck_mode,
        "source": source,
        "source_clusters": source_profile["cluster_names"],
        "source_hints": source_hints,
        "preferred_proof_types": source_profile["preferred_proof_types"],
        "preferred_layouts": source_profile["preferred_layouts"],
        "preferred_content_types": source_profile["preferred_content_types"],
        "negative_content_types": source_profile["negative_content_types"],
        "keywords": profile["keywords"],
        "proof_type": profile["proof_type"],
        "objection_tags": profile["objection_tags"],
        "deal_stage": profile["deal_stage"],
        "layout_type": profile["layout_type"],
        "trust_anchor": profile["trust_anchor"],
        "decision_audit": None,
    }
    filter_audit = {
        "filter_runs": 0,
        "negative_content_removed": 0,
        "negative_filter_fallbacks": 0,
        "preferred_content_queries": [],
        "cache_hits": 0,
        "cache_misses": 0,
        "duplicate_queries_skipped": 0,
        "search_specs_generated": 0,
        "search_specs_executed": 0,
        "downsampled_specs": 0,
    }

    query_cache_enabled = bool(search_settings.get("enable_query_cache", True))
    max_source_hints = int(search_settings.get("max_source_hints", 3))
    max_preferred_content_queries = int(search_settings.get("max_preferred_content_queries", 2))
    max_preferred_layout_queries = int(search_settings.get("max_preferred_layout_queries", 2))
    max_preferred_proof_queries = int(search_settings.get("max_preferred_proof_queries", 2))
    max_search_variants = int(search_settings.get("max_search_variants", 18))
    candidate_cap = int(search_settings.get("candidate_cap", 12))
    local_cache: dict[str, list[dict]] = {}

    def _run(
        *,
        source_file=source,
        proof_type=profile["proof_type"],
        layout_type=profile["layout_type"],
        content_type=None,
        objection_tag=None,
        deal_stage=profile["deal_stage"],
    ):
        payload = {
            "keywords": profile["keywords"] or None,
            "source_file": source_file,
            "buyer_persona": persona,
            "proof_type": proof_type,
            "objection_tag": objection_tag,
            "deal_stage": deal_stage,
            "layout_type": layout_type,
            "content_type": content_type,
            "deck_mode": deck_mode,
            "use_vector": use_vector,
            "limit": limit,
        }
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if query_cache_enabled and payload_json in local_cache:
            filter_audit["cache_hits"] += 1
            rows = json.loads(json.dumps(local_cache[payload_json], ensure_ascii=False))
        else:
            if query_cache_enabled:
                before = _search_hybrid_cached.cache_info()
                rows = json.loads(_search_hybrid_cached(payload_json))
                after = _search_hybrid_cached.cache_info()
                if after.hits > before.hits:
                    filter_audit["cache_hits"] += 1
                else:
                    filter_audit["cache_misses"] += 1
            else:
                rows = search_hybrid(**payload)
                filter_audit["cache_misses"] += 1
            local_cache[payload_json] = json.loads(json.dumps(rows, ensure_ascii=False))
        filtered_rows, filter_meta = _filter_candidate_rows(rows, source_profile)
        filter_audit["filter_runs"] += 1
        filter_audit["negative_content_removed"] += filter_meta["removed_count"]
        if filter_meta["fallback_used"]:
            filter_audit["negative_filter_fallbacks"] += 1
        return filtered_rows

    search_specs: list[dict] = []

    def _append_specs_for_sources(
        source_patterns: list[str],
        *,
        proof_type=profile["proof_type"],
        layout_type=profile["layout_type"],
        content_type=None,
        objection_tag=None,
        deal_stage=profile["deal_stage"],
    ) -> None:
        for source_pattern in source_patterns:
            search_specs.append(
                {
                    "source_file": source_pattern,
                    "proof_type": proof_type,
                    "layout_type": layout_type,
                    "content_type": content_type,
                    "objection_tag": objection_tag,
                    "deal_stage": deal_stage,
                }
            )

    limited_source_hints = source_hints[:max_source_hints]
    if source_hints:
        for preferred_content_type in source_profile["preferred_content_types"][:max_preferred_content_queries]:
            filter_audit["preferred_content_queries"].append(preferred_content_type)
            _append_specs_for_sources(limited_source_hints, content_type=preferred_content_type)
        for preferred_layout in source_profile["preferred_layouts"][:max_preferred_layout_queries]:
            _append_specs_for_sources(limited_source_hints, layout_type=preferred_layout)
        for preferred_proof_type in source_profile["preferred_proof_types"][:max_preferred_proof_queries]:
            _append_specs_for_sources(limited_source_hints, proof_type=preferred_proof_type)
        _append_specs_for_sources(source_hints)
        if profile["objection_tags"]:
            _append_specs_for_sources(limited_source_hints[:2], objection_tag=profile["objection_tags"][0])
        _append_specs_for_sources(limited_source_hints[:2], layout_type=None)
        _append_specs_for_sources(limited_source_hints[:2], proof_type=None, layout_type=None)

    search_specs.extend(
        [
            {},
            {"content_type": source_profile["preferred_content_types"][0]} if source_profile["preferred_content_types"] else {},
            {"objection_tag": profile["objection_tags"][0]} if profile["objection_tags"] else {},
            {"layout_type": None},
            {"proof_type": None, "layout_type": None},
            {"source_file": None, "proof_type": None, "layout_type": None, "deal_stage": None},
        ]
    )

    filter_audit["search_specs_generated"] = len(search_specs)
    deduped_specs = []
    seen_signatures = set()
    for spec in search_specs:
        signature = json.dumps(
            {
                "source_file": spec.get("source_file", source),
                "proof_type": spec.get("proof_type", profile["proof_type"]),
                "layout_type": spec.get("layout_type", profile["layout_type"]),
                "content_type": spec.get("content_type"),
                "objection_tag": spec.get("objection_tag"),
                "deal_stage": spec.get("deal_stage", profile["deal_stage"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if signature in seen_signatures:
            filter_audit["duplicate_queries_skipped"] += 1
            continue
        seen_signatures.add(signature)
        deduped_specs.append(spec)
    if len(deduped_specs) > max_search_variants:
        filter_audit["downsampled_specs"] = len(deduped_specs) - max_search_variants
    specs_to_run = deduped_specs[:max_search_variants]
    filter_audit["search_specs_executed"] = len(specs_to_run)

    query["filter_audit"] = {
        "filter_runs": filter_audit["filter_runs"],
        "negative_content_removed": filter_audit["negative_content_removed"],
        "negative_filter_fallbacks": filter_audit["negative_filter_fallbacks"],
        "preferred_content_queries": _dedupe_keep_order(filter_audit["preferred_content_queries"]),
        "cache_hits": filter_audit["cache_hits"],
        "cache_misses": filter_audit["cache_misses"],
        "duplicate_queries_skipped": filter_audit["duplicate_queries_skipped"],
        "search_specs_generated": filter_audit["search_specs_generated"],
        "search_specs_executed": filter_audit["search_specs_executed"],
        "downsampled_specs": filter_audit["downsampled_specs"],
    }

    candidates = []
    seen_candidate_ids = set()
    for spec in specs_to_run:
        rows = _run(**spec)
        for row in rows:
            if row["id"] in used_ids:
                continue
            normalized = _canonicalize_slide_paths(row)
            if normalized["id"] not in seen_candidate_ids:
                candidates.append(normalized)
                seen_candidate_ids.add(normalized["id"])
        if len(candidates) >= candidate_cap:
            break

    query["filter_audit"] = {
        "filter_runs": filter_audit["filter_runs"],
        "negative_content_removed": filter_audit["negative_content_removed"],
        "negative_filter_fallbacks": filter_audit["negative_filter_fallbacks"],
        "preferred_content_queries": _dedupe_keep_order(filter_audit["preferred_content_queries"]),
        "cache_hits": filter_audit["cache_hits"],
        "cache_misses": filter_audit["cache_misses"],
        "duplicate_queries_skipped": filter_audit["duplicate_queries_skipped"],
        "search_specs_generated": filter_audit["search_specs_generated"],
        "search_specs_executed": filter_audit["search_specs_executed"],
        "downsampled_specs": filter_audit["downsampled_specs"],
    }

    if not candidates:
        query["decision_audit"] = _build_decision_audit(
            status="placeholder",
            reason="no_candidates",
            min_confidence=min_confidence,
            top_candidate=None,
            alternates=[],
        )
        return None, query, []

    for candidate in candidates:
        candidate["bridge_score_breakdown"] = _bridge_score_breakdown(candidate, profile, source_profile, bridge_settings)
        candidate["bridge_confidence"] = candidate["bridge_score_breakdown"]["total"]
        candidate["bridge_confidence_band"] = _confidence_band(candidate["bridge_confidence"], min_confidence, bridge_settings)

    candidates.sort(key=lambda row: row.get("bridge_confidence", 0), reverse=True)
    selected = candidates[0]
    alternates = [
        {
            "id": candidate["id"],
            "src": candidate["src"],
            "page": candidate["page"],
            "title": candidate.get("title"),
            "file_name": candidate.get("file_name"),
            "content_type": candidate.get("content_type"),
            "proof_type": candidate.get("proof_type"),
            "layout_type": candidate.get("layout_type"),
            "bridge_confidence": candidate.get("bridge_confidence"),
            "bridge_confidence_band": candidate.get("bridge_confidence_band"),
        }
        for candidate in candidates[1:4]
    ]
    if selected.get("bridge_confidence", 0) < min_confidence:
        query["decision_audit"] = _build_decision_audit(
            status="placeholder",
            reason="below_min_confidence",
            min_confidence=min_confidence,
            top_candidate=selected,
            alternates=alternates,
        )
        return None, query, alternates
    used_ids.add(selected["id"])
    query["decision_audit"] = _build_decision_audit(
        status="matched",
        reason="accepted_match",
        min_confidence=min_confidence,
        top_candidate=selected,
        alternates=alternates,
    )
    return selected, query, alternates


def bridge_outline(
    outline_path: Path,
    *,
    manifest_path: Path,
    source: str | None,
    output_name: str | None,
    limit: int,
    use_vector: bool,
    min_confidence: float,
    source_clusters_path: Path,
    bridge_config_path: Path = DEFAULT_BRIDGE_CONFIG,
) -> tuple[dict, dict]:
    outline = parse_outline(outline_path)
    persona = _infer_persona(outline["audience"])
    deck_mode = _infer_deck_mode(persona)
    bridge_settings = _load_bridge_settings(str(bridge_config_path.resolve()))
    manifest, error = load_template_manifest(manifest_path)
    if error:
        raise FileNotFoundError(error)
    template_config = normalize_template_manifest(manifest)
    roles = template_config["page_roles"]

    used_ids: set[int] = set()
    candidate_rows = []
    plan = []

    for idx, slide in enumerate(outline["slides"], start=1):
        slide_type = slide.get("type", "")
        if idx == len(outline["slides"]) or "back cover" in slide_type or "closing" in slide_type:
            plan.append({"template_page": roles["closing"]})
            candidate_rows.append({"slide_index": idx, "mode": "template", "role": "closing", "query": None, "selected": None})
            continue
        if idx == 1 or slide_type in {"cover", "title slide"} or "title" in slide_type:
            plan.append({"template_page": roles["cover"], "replace_title": slide["title"]})
            candidate_rows.append({"slide_index": idx, "mode": "template", "role": "cover", "query": None, "selected": None})
            continue

        candidate, query, alternates = _search_slide_candidate(
            slide,
            persona=persona,
            deck_mode=deck_mode,
            source=source,
            used_ids=used_ids,
            limit=limit,
            use_vector=use_vector,
            min_confidence=min_confidence,
            source_clusters_path=source_clusters_path,
            bridge_settings=bridge_settings,
        )
        if candidate:
            plan.append({"src": candidate["src"], "page": candidate["page"]})
            candidate_rows.append(
                {
                    "slide_index": idx,
                    "mode": "matched",
                    "role": "content",
                    "headline": slide["title"],
                    "query": query,
                    "selected": candidate,
                    "alternates": alternates,
                }
            )
        else:
            plan.append({"template_page": roles["content_with_title"], "replace_title": slide["title"]})
            candidate_rows.append(
                {
                    "slide_index": idx,
                    "mode": "placeholder",
                    "role": "content",
                    "headline": slide["title"],
                    "query": query,
                    "selected": None,
                    "alternates": alternates,
                }
            )

    plan_payload = {
        "template_path": manifest.get("template_path"),
        "output_path": "{output_dir}/" + f"{_slugify(output_name or outline_path.parent.name)}_bridged.pptx",
        "plan": plan,
    }
    candidates_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "outline_path": str(outline_path),
        "topic": outline["topic"],
        "audience": outline["audience"],
        "persona": persona,
        "deck_mode": deck_mode,
        "source": source,
        "source_clusters_path": str(source_clusters_path),
        "bridge_config_path": str(bridge_config_path),
        "min_confidence": min_confidence,
        "summary": {
            "total_slides": len(outline["slides"]),
            "matched_content_slides": sum(1 for row in candidate_rows if row.get("mode") == "matched"),
            "placeholder_content_slides": sum(1 for row in candidate_rows if row.get("mode") == "placeholder"),
            "high_confidence_matches": sum(
                1 for row in candidate_rows if (row.get("selected") or {}).get("bridge_confidence_band") == "high"
            ),
            "medium_confidence_matches": sum(
                1 for row in candidate_rows if (row.get("selected") or {}).get("bridge_confidence_band") == "medium"
            ),
            "placeholder_due_to_no_candidates": sum(
                1
                for row in candidate_rows
                if ((row.get("query") or {}).get("decision_audit") or {}).get("reason") == "no_candidates"
            ),
            "placeholder_due_to_low_confidence": sum(
                1
                for row in candidate_rows
                if ((row.get("query") or {}).get("decision_audit") or {}).get("reason") == "below_min_confidence"
            ),
        },
        "slides": candidate_rows,
    }
    return candidates_payload, plan_payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _build_review_markdown(payload: dict) -> str:
    lines = [
        f"# Outline Bridge Review",
        "",
        f"- Topic: {payload.get('topic')}",
        f"- Audience: {payload.get('audience')}",
        f"- Persona: {payload.get('persona')}",
        f"- Deck Mode: {payload.get('deck_mode')}",
        f"- Source Filter: {payload.get('source') or 'None'}",
        f"- Bridge Config: {payload.get('bridge_config_path')}",
        f"- Min Confidence: {payload.get('min_confidence')}",
        "",
        "## Summary",
        "",
        f"- Total slides: {payload.get('summary', {}).get('total_slides')}",
        f"- Matched content slides: {payload.get('summary', {}).get('matched_content_slides')}",
        f"- Placeholder content slides: {payload.get('summary', {}).get('placeholder_content_slides')}",
        f"- High-confidence matches: {payload.get('summary', {}).get('high_confidence_matches')}",
        f"- Medium-confidence matches: {payload.get('summary', {}).get('medium_confidence_matches')}",
        f"- Placeholder (no candidates): {payload.get('summary', {}).get('placeholder_due_to_no_candidates')}",
        f"- Placeholder (low confidence): {payload.get('summary', {}).get('placeholder_due_to_low_confidence')}",
        "",
        "## Manual Queue",
        "",
    ]

    queue_rows = []
    for row in payload.get("slides", []):
        query = row.get("query") or {}
        decision = query.get("decision_audit") or {}
        selected = row.get("selected") or {}
        if row.get("mode") == "placeholder":
            queue_rows.append(
                f"- Slide {row.get('slide_index')}: placeholder | reason={decision.get('reason')} | action={decision.get('manual_action')}"
            )
        elif selected.get("bridge_confidence_band") == "medium":
            queue_rows.append(
                f"- Slide {row.get('slide_index')}: medium-confidence match | selected={selected.get('file_name')} p.{selected.get('page')} | action={decision.get('manual_action')}"
            )
    if queue_rows:
        lines.extend(queue_rows)
    else:
        lines.append("- No manual review queue.")
    lines.extend(["", "## Slide Audit", ""])

    for row in payload.get("slides", []):
        lines.append(f"### Slide {row.get('slide_index')}")
        lines.append("")
        lines.append(f"- Mode: {row.get('mode')}")
        lines.append(f"- Role: {row.get('role')}")
        if row.get("headline"):
            lines.append(f"- Headline: {row.get('headline')}")
        query = row.get("query") or {}
        if query.get("trust_anchor"):
            lines.append(f"- Trust Anchor: {query.get('trust_anchor')}")
        if query.get("source_clusters"):
            lines.append(f"- Source Clusters: {', '.join(query.get('source_clusters'))}")
        if query.get("source_hints"):
            lines.append(f"- Source Hints: {', '.join(query.get('source_hints'))}")
        if query.get("preferred_proof_types"):
            lines.append(f"- Preferred Proof Types: {', '.join(query.get('preferred_proof_types'))}")
        if query.get("preferred_layouts"):
            lines.append(f"- Preferred Layouts: {', '.join(query.get('preferred_layouts'))}")
        if query.get("preferred_content_types"):
            lines.append(f"- Preferred Content Types: {', '.join(query.get('preferred_content_types'))}")
        if query.get("negative_content_types"):
            lines.append(f"- Negative Content Types: {', '.join(query.get('negative_content_types'))}")
        decision = query.get("decision_audit") or {}
        filter_audit = query.get("filter_audit") or {}
        if filter_audit:
            lines.append(
                "- Filter Audit: "
                f"runs={filter_audit.get('filter_runs', 0)} "
                f"removed={filter_audit.get('negative_content_removed', 0)} "
                f"fallbacks={filter_audit.get('negative_filter_fallbacks', 0)} "
                f"cache_hits={filter_audit.get('cache_hits', 0)} "
                f"cache_misses={filter_audit.get('cache_misses', 0)} "
                f"dupes_skipped={filter_audit.get('duplicate_queries_skipped', 0)} "
                f"generated={filter_audit.get('search_specs_generated', 0)} "
                f"executed={filter_audit.get('search_specs_executed', 0)} "
                f"downsampled={filter_audit.get('downsampled_specs', 0)}"
            )
            if filter_audit.get("preferred_content_queries"):
                lines.append(
                    f"- Preferred Content Queries: {', '.join(filter_audit.get('preferred_content_queries'))}"
                )
        if decision:
            lines.append(
                f"- Decision: {decision.get('status')} | reason={decision.get('reason')} | manual_action={decision.get('manual_action')}"
            )
            if decision.get("top_candidate_confidence") is not None:
                lines.append(
                    f"- Top Candidate Audit: confidence={decision.get('top_candidate_confidence')} "
                    f"band={decision.get('top_candidate_band')} "
                    f"type={decision.get('top_candidate_type') or '未知'} "
                    f"title={decision.get('top_candidate_title') or '未知'}"
                )
        selected = row.get("selected")
        if selected:
            lines.append(f"- Selected: {selected.get('file_name')} / p.{selected.get('page')}")
            lines.append(
                f"- Selected Type: {selected.get('content_type') or '未知'}"
                f" | Proof: {selected.get('proof_type') or '未知'}"
                f" | Layout: {selected.get('layout_type') or '未知'}"
            )
            lines.append(f"- Confidence: {selected.get('bridge_confidence')} ({selected.get('bridge_confidence_band')})")
            breakdown = selected.get("bridge_score_breakdown") or {}
            if breakdown:
                lines.append(
                    "- Score Breakdown: "
                    f"hybrid={breakdown.get('hybrid_score')} "
                    f"overlap={breakdown.get('token_overlap')} "
                    f"headline={breakdown.get('headline_overlap')} "
                    f"narrative={breakdown.get('narrative_overlap')} "
                    f"visual={breakdown.get('visual_overlap')} "
                    f"trust={breakdown.get('trust_anchor_match')} "
                    f"src_proof={breakdown.get('source_proof_preference')} "
                    f"src_layout={breakdown.get('source_layout_preference')} "
                    f"src_content={breakdown.get('source_content_preference')} "
                    f"proof={breakdown.get('proof_match')} "
                    f"layout={breakdown.get('layout_match')} "
                    f"objection={breakdown.get('objection_match')} "
                    f"negative_content_penalty={breakdown.get('negative_content_penalty')} "
                    f"negative_penalty={breakdown.get('negative_penalty')}"
                )
        else:
            lines.append("- Selected: placeholder template page")

        alternates = row.get("alternates") or []
        if alternates:
            lines.append("- Alternates:")
            for alt in alternates:
                lines.append(
                    f"  - {alt.get('file_name')} / p.{alt.get('page')} "
                    f"[{alt.get('bridge_confidence')} {alt.get('bridge_confidence_band')}] "
                    f"type={alt.get('content_type') or '未知'} "
                    f"proof={alt.get('proof_type') or '未知'} "
                    f"layout={alt.get('layout_type') or '未知'}"
                )
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    parser = argparse.ArgumentParser(description="Bridge presentation outlines into SlideBlocks plans")
    parser.add_argument("outline", help="Path to outline.md")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Template manifest path")
    parser.add_argument("--source", help="Optional source file name filter")
    parser.add_argument("--output-name", help="Override output PPT name stem")
    parser.add_argument("--plan-file", help="Output plan JSON path")
    parser.add_argument("--candidates-file", help="Output candidates JSON path")
    parser.add_argument("--review-file", help="Output markdown review path")
    parser.add_argument("--limit", type=int, default=8, help="Search rows to inspect per slide")
    parser.add_argument("--use-vector", action="store_true", help="Enable vector query generation (disabled by default for offline stability)")
    parser.add_argument("--min-confidence", type=float, help="Minimum confidence required before a match is accepted")
    parser.add_argument("--source-clusters", default=str(DEFAULT_SOURCE_CLUSTERS), help="Path to source cluster configuration JSON")
    parser.add_argument("--bridge-config", default=str(DEFAULT_BRIDGE_CONFIG), help="Path to bridge scoring/search config JSON")
    args = parser.parse_args()

    outline_path = Path(args.outline).resolve()
    if not outline_path.exists():
        raise FileNotFoundError(f"Outline not found: {outline_path}")

    bridge_config_path = Path(args.bridge_config).resolve()
    bridge_settings = _load_bridge_settings(str(bridge_config_path))
    min_confidence = args.min_confidence if args.min_confidence is not None else bridge_settings["confidence"]["min_confidence_default"]

    candidates_payload, plan_payload = bridge_outline(
        outline_path,
        manifest_path=Path(args.manifest).resolve(),
        source=args.source,
        output_name=args.output_name,
        limit=args.limit,
        use_vector=args.use_vector,
        min_confidence=min_confidence,
        source_clusters_path=Path(args.source_clusters).resolve(),
        bridge_config_path=bridge_config_path,
    )

    default_root = Path(__file__).resolve().parent.parent / "tasks"
    if outline_path.is_relative_to(Path(__file__).resolve().parent.parent):
        default_root = outline_path.parent
    stem = _slugify(outline_path.parent.name)
    candidates_path = Path(args.candidates_file).resolve() if args.candidates_file else default_root / f"{stem}_slideblocks_candidates.json"
    plan_path = Path(args.plan_file).resolve() if args.plan_file else default_root / f"{stem}_slideblocks_plan.json"
    review_path = Path(args.review_file).resolve() if args.review_file else default_root / f"{stem}_slideblocks_review.md"
    _write_json(candidates_path, candidates_payload)
    _write_json(plan_path, plan_payload)
    _write_text(review_path, _build_review_markdown(candidates_payload))

    print(f"[+] Bridge candidates written to: {candidates_path}")
    print(f"[+] Bridge plan written to: {plan_path}")
    print(f"[+] Bridge review written to: {review_path}")
    print(f"    Suggested output deck: {get_output_dir() / (Path(plan_payload['output_path']).stem + '.pptx')}")


if __name__ == "__main__":
    main()
