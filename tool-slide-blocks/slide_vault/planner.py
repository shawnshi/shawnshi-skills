# -*- coding: utf-8 -*-
"""
planner.py - Commercial-semantic deck planner for SlideBlocks.

Builds:
1. grouped candidate report for review
2. JSON assembly plan consumable by engine.runner
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from .commercial import DECK_MODE_PRESETS
from .config import get_materials_dir, get_output_dir
from .search import search_hybrid

try:
    from engine.template_manifest import (
        expand_known_placeholders,
        load_template_manifest,
        normalize_template_manifest,
    )
except Exception:
    from ..engine.template_manifest import (  # type: ignore
        expand_known_placeholders,
        load_template_manifest,
        normalize_template_manifest,
    )

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_MANIFESTS = {
    "light": Path(__file__).resolve().parent.parent / "manifests" / "light-default.json",
    "dark": Path(__file__).resolve().parent.parent / "manifests" / "dark-default.json",
}


SECTION_PRESETS = {
    "board_strategy": [
        {
            "id": "why_now",
            "title": "为什么是现在：战略窗口与价值重估",
            "slides": 4,
            "keywords": ["AI", "战略", "降本增效", "回报率", "转型"],
            "proof_types": ["quantitative_outcome", "policy", "case"],
            "evidence_tiers": ["strong", "decisive"],
            "deal_stage": "board_approval",
        },
        {
            "id": "architecture",
            "title": "新基座：AI 原生医院架构",
            "slides": 4,
            "keywords": ["架构", "平台", "中台", "治理", "私有部署"],
            "proof_types": ["architecture", "case"],
            "objection_tags": ["integration_complexity", "data_security", "governance_risk"],
            "deal_stage": "strategy_alignment",
        },
        {
            "id": "scenarios",
            "title": "价值释放：核心场景的效率跃迁",
            "slides": 5,
            "keywords": ["病历", "临床", "智能体", "辅助决策", "质控"],
            "proof_types": ["product", "case", "quantitative_outcome"],
            "objection_tags": ["roi_unclear", "clinical_trust"],
            "deal_stage": "solution_evaluation",
        },
        {
            "id": "proof",
            "title": "外部证明：标杆案例与量化结果",
            "slides": 4,
            "keywords": ["案例", "标杆", "实践", "量化", "效能"],
            "proof_types": ["case", "quantitative_outcome", "research"],
            "evidence_tiers": ["strong", "decisive"],
        },
        {
            "id": "governance",
            "title": "实施路径：风险对冲与组织保障",
            "slides": 4,
            "keywords": ["实施路径", "推进路径", "治理", "合规", "路线图"],
            "proof_types": ["architecture", "case", "policy"],
            "objection_tags": ["implementation_risk", "governance_risk", "data_security"],
            "deal_stage": "pilot_design",
        },
    ],
    "hospital_leadership": [
        {
            "id": "strategic_pressure",
            "title": "高质量发展下的医院管理压力",
            "slides": 4,
            "keywords": ["高质量发展", "医院管理", "效率", "一体化"],
            "proof_types": ["case", "quantitative_outcome", "policy"],
        },
        {
            "id": "capability",
            "title": "能力底座：一体化与智能协同",
            "slides": 4,
            "keywords": ["一体化", "平台", "协同", "管理闭环"],
            "proof_types": ["architecture", "case", "product"],
        },
        {
            "id": "scenarios",
            "title": "临床与管理双轮驱动的落地场景",
            "slides": 5,
            "keywords": ["病历", "护理", "管理", "临床", "质控"],
            "proof_types": ["case", "product", "quantitative_outcome"],
            "objection_tags": ["clinical_trust", "roi_unclear"],
        },
        {
            "id": "implementation",
            "title": "分阶段推进：从试点到院级复制",
            "slides": 4,
            "keywords": ["实施路径", "试点", "复制", "推广", "推进路径"],
            "proof_types": ["case", "architecture"],
            "objection_tags": ["implementation_risk"],
        },
    ],
    "cio_architecture": [
        {
            "id": "target_architecture",
            "title": "目标架构：从烟囱式系统到 AI 原生平台",
            "slides": 5,
            "keywords": ["架构", "平台", "中台", "互联互通", "云原生", "私有部署"],
            "proof_types": ["architecture", "case"],
            "evidence_tiers": ["medium", "strong", "decisive"],
            "deal_stage": "strategy_alignment",
        },
        {
            "id": "governance_security",
            "title": "治理与安全：模型主权、数据主权、集成主权",
            "slides": 4,
            "keywords": ["治理", "数据", "安全", "主权", "信创", "合规"],
            "proof_types": ["architecture", "policy", "case"],
            "objection_tags": ["data_security", "governance_risk", "integration_complexity"],
        },
        {
            "id": "business_scenarios",
            "title": "业务落点：先从高价值场景建立牵引",
            "slides": 4,
            "keywords": ["病历", "报告", "质控", "辅助决策", "智能体"],
            "proof_types": ["product", "case"],
            "objection_tags": ["clinical_trust", "roi_unclear"],
            "deal_stage": "solution_evaluation",
        },
        {
            "id": "proof",
            "title": "证据链：产品能力、标杆验证与量化收益",
            "slides": 4,
            "keywords": ["标杆", "案例", "量化", "效能", "产品"],
            "proof_types": ["case", "quantitative_outcome", "product"],
            "evidence_tiers": ["strong", "decisive"],
        },
        {
            "id": "delivery",
            "title": "交付路径：从试点架构到集团级复制",
            "slides": 4,
            "keywords": ["实施路径", "试点", "复制", "路线图", "交付"],
            "proof_types": ["architecture", "case"],
            "objection_tags": ["implementation_risk", "integration_complexity"],
            "deal_stage": "pilot_design",
        },
    ],
    "clinical_expert": [
        {
            "id": "clinical_problem",
            "title": "临床问题：质量、效率与一致性的三重压力",
            "slides": 4,
            "keywords": ["临床", "医生", "质控", "效率", "一致性"],
            "proof_types": ["research", "case", "quantitative_outcome"],
        },
        {
            "id": "clinical_capability",
            "title": "技术路径：知识增强与临床推理",
            "slides": 4,
            "keywords": ["临床决策", "知识图谱", "RAG", "影像", "诊疗"],
            "proof_types": ["research", "architecture", "product"],
            "objection_tags": ["clinical_trust"],
        },
        {
            "id": "clinical_scenarios",
            "title": "重点专科场景：从病历到辅助决策",
            "slides": 5,
            "keywords": ["病历", "报告", "肿瘤", "VTE", "专科"],
            "proof_types": ["case", "product", "research"],
            "objection_tags": ["clinical_trust"],
        },
        {
            "id": "validation",
            "title": "可信验证：研究证据与落地实绩",
            "slides": 4,
            "keywords": ["期刊", "研究", "评价研究", "案例", "实践"],
            "proof_types": ["research", "case", "quantitative_outcome"],
            "evidence_tiers": ["strong", "decisive"],
        },
    ],
    "bid_response": [
        {
            "id": "vendor_qualification",
            "title": "资质与能力：为什么是我们",
            "slides": 4,
            "keywords": ["建设优势", "领军企业", "资质", "服务体系"],
            "proof_types": ["case", "product", "quantitative_outcome"],
            "objection_tags": ["vendor_differentiation"],
            "deal_stage": "procurement",
        },
        {
            "id": "solution",
            "title": "方案体系：平台、产品与集成能力",
            "slides": 4,
            "keywords": ["方案", "平台", "集成", "架构", "产品"],
            "proof_types": ["architecture", "product", "case"],
            "objection_tags": ["integration_complexity", "data_security"],
        },
        {
            "id": "delivery",
            "title": "交付保障：实施、服务与风险控制",
            "slides": 4,
            "keywords": ["实施", "交付", "服务", "风险", "保障"],
            "proof_types": ["case", "architecture"],
            "objection_tags": ["implementation_risk", "governance_risk"],
            "deal_stage": "pilot_design",
        },
        {
            "id": "proof",
            "title": "案例证明：同类客户与量化成效",
            "slides": 4,
            "keywords": ["案例", "标杆", "量化", "客户", "实践"],
            "proof_types": ["case", "quantitative_outcome"],
            "evidence_tiers": ["strong", "decisive"],
        },
    ],
}


def _slugify(value: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value.strip(), flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "deck"


def _dedupe_keywords(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if not value or value in seen:
            continue
        deduped.append(value)
        seen.add(value)
    return deduped


def _copy_result(result: dict) -> dict:
    data = deepcopy(result)
    if "thumbnail" in data and not data["thumbnail"]:
        data.pop("thumbnail", None)
    return data


def _canonicalize_slide_paths(result: dict) -> dict:
    data = _copy_result(result)
    file_name = data.get("file_name")
    src = data.get("src")
    materials_dir = get_materials_dir()
    if file_name:
        candidate = materials_dir / file_name
        if candidate.exists():
            data["src"] = str(candidate).replace("\\", "/")
    elif isinstance(src, str):
        data["src"] = src.replace("\\", "/")

    thumbnail = data.get("thumbnail")
    if file_name and data.get("page"):
        thumb_candidate = materials_dir.parent / ".thumbnails" / Path(file_name).stem / f"slide_{int(data['page']):03d}.jpg"
        if thumb_candidate.exists():
            data["thumbnail"] = str(thumb_candidate).replace("\\", "/")
        elif isinstance(thumbnail, str):
            data["thumbnail"] = thumbnail.replace("\\", "/")
    elif isinstance(thumbnail, str):
        data["thumbnail"] = thumbnail.replace("\\", "/")
    return data


def _score_candidate(result: dict, section: dict, persona: str | None, objections: list[str]) -> float:
    score = float(result.get("hybrid_score", 0))
    if persona and persona in result.get("buyer_personas", []):
        score += 0.08
    if result.get("proof_type") in section.get("proof_types", []):
        score += 0.06
    if result.get("evidence_tier") in section.get("evidence_tiers", []):
        score += 0.05
    section_objections = set(section.get("objection_tags", []))
    global_objections = set(objections)
    candidate_objections = set(result.get("objection_tags", []))
    if candidate_objections & section_objections:
        score += 0.05
    if candidate_objections & global_objections:
        score += 0.04
    return score


def _merge_candidates(existing: dict, results: list[dict], section: dict, persona: str | None, objections: list[str]):
    for result in results:
        candidate_id = result["id"]
        score = _score_candidate(result, section, persona, objections)
        payload = _canonicalize_slide_paths(result)
        payload["planner_score"] = round(score, 4)
        current = existing.get(candidate_id)
        if current is None or payload["planner_score"] > current["planner_score"]:
            existing[candidate_id] = payload


def _query_variants(
    section: dict,
    *,
    persona: str | None,
    deck_mode: str | None,
    source: str | None,
    global_keywords: list[str],
    global_objections: list[str],
    use_vector: bool,
    limit: int,
) -> list[dict]:
    keywords = _dedupe_keywords(global_keywords + section.get("keywords", []))
    objections = _dedupe_keywords(section.get("objection_tags", []) + global_objections)
    proof_types = section.get("proof_types", []) or [None]

    merged = {}
    stage = section.get("deal_stage")

    def _run_query(
        *,
        proof_type=None,
        objection_tag=None,
        use_keywords=True,
        deal_stage_override=stage,
        source_override=source,
    ):
        query_keywords = keywords if use_keywords else global_keywords
        results = search_hybrid(
            keywords=query_keywords or None,
            source_file=source_override,
            buyer_persona=persona,
            deal_stage=deal_stage_override,
            objection_tag=objection_tag,
            proof_type=proof_type,
            deck_mode=deck_mode,
            use_vector=use_vector,
            limit=limit,
        )
        _merge_candidates(merged, results, section, persona, global_objections)

    for proof_type in proof_types:
        _run_query(proof_type=proof_type)
        for objection in objections[:2]:
            _run_query(proof_type=proof_type, objection_tag=objection)

    if len(merged) < max(section.get("slides", 2) * 2, 6):
        _run_query(use_keywords=True)
    if len(merged) < max(section.get("slides", 2), 4):
        _run_query(use_keywords=False)
    if len(merged) < max(section.get("slides", 2), 4) and stage:
        _run_query(use_keywords=True, deal_stage_override=None)
    if len(merged) < max(section.get("slides", 2), 4) and stage:
        _run_query(use_keywords=False, deal_stage_override=None)
    if len(merged) < max(section.get("slides", 2), 4) and source:
        _run_query(use_keywords=True, source_override=None)
    if len(merged) < max(section.get("slides", 2), 4) and source:
        _run_query(use_keywords=False, source_override=None)

    results = sorted(merged.values(), key=lambda item: item["planner_score"], reverse=True)
    return results


def _pick_unique_candidates(candidates: list[dict], used_slide_ids: set[int], limit: int) -> tuple[list[dict], list[dict]]:
    selected = []
    alternates = []
    for candidate in candidates:
        candidate_id = candidate["id"]
        if candidate_id in used_slide_ids:
            continue
        if len(selected) < limit:
            used_slide_ids.add(candidate_id)
            selected.append(candidate)
        else:
            alternates.append(candidate)
    if len(selected) < limit:
        selected_ids = {candidate["id"] for candidate in selected}
        for candidate in candidates:
            if candidate["id"] in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate["id"])
            if len(selected) >= limit:
                break
    return selected, alternates


def _get_manifest_config(manifest_path: str | Path | None) -> tuple[dict, str | None]:
    if manifest_path is None:
        manifest_path = DEFAULT_MANIFESTS["light"]
    manifest, error = load_template_manifest(manifest_path)
    if error:
        raise FileNotFoundError(error)
    return normalize_template_manifest(manifest), str(Path(manifest_path).resolve())


def _infer_fix_color_flags(file_name: str, manifest_config: dict) -> dict:
    flags = {}
    background_mode = manifest_config.get("background_mode")
    file_name = file_name or ""
    if background_mode == "light" and "深色底" in file_name:
        flags["fix_colors"] = True
    if background_mode == "dark" and "浅色底" in file_name:
        flags["fix_colors_dark"] = True
    return flags


def build_deck_plan(
    *,
    title: str,
    deck_mode: str,
    manifest_path: str | Path | None,
    output_name: str | None,
    source: str | None,
    persona: str | None,
    keywords: list[str],
    objections: list[str],
    use_vector: bool,
    search_limit: int,
) -> dict:
    if deck_mode not in SECTION_PRESETS:
        raise ValueError(f"Unsupported deck mode: {deck_mode}")

    manifest_config, resolved_manifest_path = _get_manifest_config(manifest_path)
    persona = persona or DECK_MODE_PRESETS.get(deck_mode, {}).get("buyer_persona")
    sections = SECTION_PRESETS[deck_mode]
    used_slide_ids: set[int] = set()
    candidate_sections = []

    for section in sections:
        candidates = _query_variants(
            section,
            persona=persona,
            deck_mode=deck_mode,
            source=source,
            global_keywords=keywords,
            global_objections=objections,
            use_vector=use_vector,
            limit=search_limit,
        )
        selected, alternates = _pick_unique_candidates(candidates, used_slide_ids, section.get("slides", 3))
        candidate_sections.append(
            {
                "id": section["id"],
                "title": section["title"],
                "query": {
                    "persona": persona,
                    "source": source,
                    "keywords": _dedupe_keywords(keywords + section.get("keywords", [])),
                    "proof_types": section.get("proof_types", []),
                    "objection_tags": _dedupe_keywords(section.get("objection_tags", []) + objections),
                    "deal_stage": section.get("deal_stage"),
                },
                "selected": selected,
                "alternates": alternates[: min(6, len(alternates))],
            }
        )

    page_roles = manifest_config["page_roles"]
    transition_page = page_roles["transition"]
    cover_page = page_roles["cover"]
    closing_page = page_roles["closing"]
    transition_font_size = manifest_config.get("transition_default_font_size", 40)

    output_stub = _slugify(output_name or f"{deck_mode}_{datetime.now().strftime('%Y%m%d')}")
    output_path = "{output_dir}/" + f"{output_stub}.pptx"
    plan_items = [{"template_page": cover_page, "replace_title": title}]

    for index, section in enumerate(candidate_sections):
        if index > 0:
            plan_items.append(
                {
                    "template_page": transition_page,
                    "replace_title": section["title"],
                    "font_size": transition_font_size,
                }
            )
        for selected in section["selected"]:
            item = {
                "src": selected["src"],
                "page": selected["page"],
            }
            item.update(_infer_fix_color_flags(selected.get("file_name", ""), manifest_config))
            plan_items.append(item)

    plan_items.append({"template_page": closing_page})

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "title": title,
        "deck_mode": deck_mode,
        "persona": persona,
        "source": source,
        "keywords": keywords,
        "objection_tags": objections,
        "manifest_path": resolved_manifest_path,
        "output_path": output_path,
        "candidate_sections": candidate_sections,
        "assembly_plan": {
            "output_path": output_path,
            "plan": plan_items,
        },
    }

    manifest_template_path = manifest_config.get("template_path")
    if manifest_template_path:
        payload["assembly_plan"]["template_path"] = manifest_template_path

    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _build_legacy_grouped_results(candidates_payload: dict) -> dict:
    legacy = {
        "_meta": {
            "generated_at": candidates_payload["generated_at"],
            "title": candidates_payload["title"],
            "deck_mode": candidates_payload["deck_mode"],
            "persona": candidates_payload["persona"],
            "source": candidates_payload["source"],
            "manifest_path": candidates_payload["manifest_path"],
        }
    }
    for section in candidates_payload["sections"]:
        rows = []
        for candidate in section.get("selected", []):
            rows.append(
                {
                    "src": candidate["src"],
                    "page": candidate["page"],
                    "title": candidate.get("title"),
                    "desc": candidate.get("summary"),
                    "thumbnail": candidate.get("thumbnail"),
                    "proof_type": candidate.get("proof_type"),
                    "evidence_tier": candidate.get("evidence_tier"),
                    "buyer_personas": candidate.get("buyer_personas", []),
                    "objection_tags": candidate.get("objection_tags", []),
                }
            )
        legacy[section["id"]] = rows
    return legacy


def _default_output_paths(deck_mode: str, title: str) -> tuple[Path, Path]:
    slug = _slugify(f"{deck_mode}_{title}")
    root = Path(__file__).resolve().parent.parent / "tasks"
    return root / f"{slug}_candidates.json", root / f"{slug}_plan.json"


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SlideBlocks commercial deck planner")
    parser.add_argument("--title", required=True, help="Deck cover title")
    parser.add_argument("--deck-mode", required=True, choices=sorted(SECTION_PRESETS.keys()), help="Commercial deck mode")
    parser.add_argument("--persona", help="Override buyer persona")
    parser.add_argument("--source", help="Filter slides by source file name")
    parser.add_argument("--keywords", nargs="+", default=[], help="Global keywords")
    parser.add_argument("--objection", dest="objections", nargs="+", default=[], help="Global objections to emphasize")
    parser.add_argument("--manifest", help="Manifest path, defaults to manifests/light-default.json")
    parser.add_argument("--output-name", help="Output PPT file name without extension")
    parser.add_argument("--plan-file", help="Path to generated assembly plan JSON")
    parser.add_argument("--candidates-file", help="Path to generated candidate report JSON")
    parser.add_argument("--legacy-results-file", help="Optional grouped search_results-compatible JSON output path")
    parser.add_argument("--search-limit", type=int, default=12, help="Max search rows pulled per query variant")
    parser.add_argument("--no-vector", action="store_false", dest="use_vector", help="Disable vector search")
    return parser


def main():
    args = _build_cli().parse_args()
    candidates_path, plan_path = _default_output_paths(args.deck_mode, args.title)
    if args.candidates_file:
        candidates_path = Path(args.candidates_file)
    if args.plan_file:
        plan_path = Path(args.plan_file)

    payload = build_deck_plan(
        title=args.title,
        deck_mode=args.deck_mode,
        manifest_path=args.manifest,
        output_name=args.output_name,
        source=args.source,
        persona=args.persona,
        keywords=args.keywords,
        objections=args.objections,
        use_vector=args.use_vector,
        search_limit=args.search_limit,
    )

    candidates_payload = {
        "generated_at": payload["generated_at"],
        "title": payload["title"],
        "deck_mode": payload["deck_mode"],
        "persona": payload["persona"],
        "source": payload["source"],
        "keywords": payload["keywords"],
        "objection_tags": payload["objection_tags"],
        "manifest_path": payload["manifest_path"],
        "sections": payload["candidate_sections"],
    }
    _write_json(candidates_path, candidates_payload)
    _write_json(plan_path, payload["assembly_plan"])
    legacy_results_path = Path(args.legacy_results_file) if args.legacy_results_file else None
    if legacy_results_path:
        _write_json(legacy_results_path, _build_legacy_grouped_results(candidates_payload))

    print(f"[+] Candidate report written to: {candidates_path}")
    print(f"[+] Assembly plan written to: {plan_path}")
    if legacy_results_path:
        print(f"[+] Legacy grouped report written to: {legacy_results_path}")
    print(f"    Suggested output deck: {expand_known_placeholders(payload['output_path'])}")


if __name__ == "__main__":
    main()
