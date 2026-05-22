from __future__ import annotations

import json
import re
from datetime import datetime

from blackboard import append_signal, update_phase
from history_manager import is_redundant
from hub_utils import HUB_DIR, LATEST_SCAN_PATH, REFINED_PATH, clean_json_output, dump_json, ensure_runtime_dirs, has_llm_runner, load_json, run_llm


FOCUS_PATH = HUB_DIR / "references" / "strategic_focus.json"
PROMPT_PATH = HUB_DIR / "references" / "prompts" / "v1_refine_system.md"


def load_inputs() -> tuple[dict, dict]:
    scan_data = load_json(LATEST_SCAN_PATH, {})
    focus_data = load_json(FOCUS_PATH, {})
    if not scan_data.get("items"):
        raise RuntimeError(f"No scan data found at {LATEST_SCAN_PATH}")
    return scan_data, focus_data


def score_item(item: dict, focus_data: dict) -> tuple[int, list[str]]:
    text = (item.get("title", "") + " " + item.get("raw_desc", "")).lower()
    score = 0
    matched = []
    for entry in focus_data.get("strategic_keywords", []):
        kw = entry["keyword"].lower()
        if kw in text:
            score += entry["weight"]
            matched.append(entry["keyword"])
    source_weight = focus_data.get("priority_sources", {}).get(item.get("source", ""), 0)
    score += source_weight
    return score, matched


def confidence_from_source(source: str, focus_data: dict) -> str:
    conf = focus_data.get("source_confidence", {})
    if source in conf.get("high", []):
        return "high"
    if source in conf.get("medium", []):
        return "medium"
    return "medium"


def level_from_score(score: int, runner_available: bool) -> str:
    if score >= 8:
        return "L3"
    if score >= 4:
        return "L2"
    return "L1"


def make_candidate(item: dict, score: int, matched: list[str], runner_available: bool, focus_data: dict) -> dict:
    summary = item.get("raw_desc", "").strip() or item.get("title", "")
    summary = summary[:220]
    connection = "、".join(matched[:3]) if matched else "与当前战略重心关联较弱，但建议观察"
    level = level_from_score(score, runner_available)
    return {
        "title": item.get("title", "Untitled"),
        "title_zh": item.get("title", "Untitled"),
        "url": item.get("url", ""),
        "source": item.get("source", "Unknown"),
        "date": item.get("time", "Unknown")[:10],
        "strategic_score": score,
        "summary_zh": summary,
        "reason": f"匹配主题: {connection}",
        "fact": item.get("title", "No fact"),
        "connection": connection,
        "deduction": "需要结合现有布局判断其是否形成结构性变化。",
        "actionability": "加入观察清单，若连续出现则升级跟踪。",
        "confidence": confidence_from_source(item.get("source", ""), focus_data),
        "intelligence_level": level,
        "intel_grade": level,
    }


def heuristics(scan_data: dict, focus_data: dict) -> dict:
    runner_available = has_llm_runner()
    scored = []
    for item in scan_data["items"]:
        if is_redundant(item.get("url", ""), item.get("title", ""), item.get("source", "")):
            continue
        score, matched = score_item(item, focus_data)
        scored.append((score, make_candidate(item, score, matched, runner_available, focus_data)))
    scored.sort(key=lambda x: x[0], reverse=True)

    max_top10 = focus_data.get("filters", {}).get("max_top10", 10)
    min_score = focus_data.get("filters", {}).get("min_score_for_top10", 4)
    top_candidates = [candidate for score, candidate in scored if score >= min_score][:max_top10]

    for candidate in top_candidates:
        append_signal(
            {
                "title": candidate["title"],
                "url": candidate["url"],
                "score": candidate["strategic_score"],
                "level": candidate["intelligence_level"],
            }
        )

    urgent_signals = [
        {"title": c["title"], "action": c["actionability"]}
        for c in top_candidates
        if c["intelligence_level"] == "L4"
    ][:3]

    action_levers = [
        {
            "domain": candidate["connection"].split("、")[0] if candidate.get("connection") else "通用",
            "task": candidate["actionability"],
        }
        for candidate in top_candidates[:5]
    ]

    translations = {
        candidate["url"]: {"title_zh": candidate["title_zh"], "desc_zh": candidate["summary_zh"]}
        for candidate in top_candidates
    }

    return {
        "generated_at": datetime.now().isoformat(),
        "status": "COMPLETED",
        "model_used": "heuristic" if not runner_available else "hybrid",
        "punchline": top_candidates[0]["deduction"] if top_candidates else "暂无足够高价值信号。",
        "insights": "\n".join(
            f"- **{c['title']}**: {c['connection']} -> {c['deduction']}" for c in top_candidates[:5]
        ) or "- 暂无高价值洞察",
        "digest": "\n".join(
            f"- {c['title']}: {c['actionability']}" for c in top_candidates[:5]
        ) or "- 暂无动作建议",
        "market": "\n".join(f"- {c['title']}" for c in top_candidates[:8]) or "- 数据不足",
        "urgent_signals": urgent_signals,
        "action_levers": action_levers[:5],
        "top_10": top_candidates,
        "translations": translations,
        "adversarial_audit_required": any(c["intelligence_level"] == "L4" for c in top_candidates),
    }


def maybe_model_refine(base_output: dict) -> dict:
    if not has_llm_runner():
        return base_output
    prompt_text = PROMPT_PATH.read_text(encoding="utf-8") if PROMPT_PATH.exists() else ""
    lightweight_prompt = (
        prompt_text
        + "\n\n请在不破坏既有 JSON 结构的前提下，强化 punchline、insights、digest、market。同时，请务必将 top_10 列表中的 fact, connection, deduction, actionability, summary_zh, title_zh 字段翻译并基于二阶推演改写为高质量的中文描述。"
        + "\n对于 top_10 中的情报，请严格依据质量标准，仅当情报属“非共识、可直接触发动作”时，将其 intelligence_level 提升为 'L4'，并在 reason 中说明理由。绝不可滥用 L4。"
        + "\n请提取并总结真实的 action_levers (包含 domain 和 task)。如果没有实质性的动作杠杆，请宁缺毋滥，不要生成废话。"
        + "\n输入候选 JSON:\n"
        + json.dumps(base_output, ensure_ascii=False)
    )
    try:
        model_output = json.loads(run_llm(lightweight_prompt))
        for key in ["punchline", "insights", "digest", "market", "action_levers", "urgent_signals", "top_10"]:
            if key in model_output and model_output[key]:
                if key == "top_10":
                    for i, model_item in enumerate(model_output["top_10"]):
                        if i < len(base_output["top_10"]):
                            base_output["top_10"][i].update(model_item)
                else:
                    base_output[key] = model_output[key]
        base_output["model_used"] = "runner+heuristic"
    except Exception as e:
        print(f"[WARN] LLM refinement failed: {e}")
        pass
    return base_output


def enforce_entity_linking(text: str, entities: list[str]) -> str:
    if not text:
        return text
    for entity in entities:
        if len(entity) >= 2:
            pattern = re.compile(rf"(?<!\[\[)({re.escape(entity)})(?!\]\])", flags=re.IGNORECASE)
            text = pattern.sub(r"[[\1]]", text)
    return text


def post_process_entities(output: dict, focus_data: dict) -> dict:
    competitors = focus_data.get("competitors", [])
    keywords = [kw["keyword"] for kw in focus_data.get("strategic_keywords", [])]
    entities = sorted(list(set(competitors + keywords)), key=len, reverse=True)
    
    for candidate in output.get("top_10", []):
        if "summary_zh" in candidate:
            candidate["summary_zh"] = enforce_entity_linking(candidate["summary_zh"], entities)
        if "title_zh" in candidate:
            candidate["title_zh"] = enforce_entity_linking(candidate["title_zh"], entities)
        if "deduction" in candidate:
            candidate["deduction"] = enforce_entity_linking(candidate["deduction"], entities)
    return output


def refine() -> None:
    ensure_runtime_dirs()
    update_phase("refine", "running")
    scan_data, focus_data = load_inputs()
    output = heuristics(scan_data, focus_data)
    output = maybe_model_refine(output)
    output = post_process_entities(output, focus_data)
    dump_json(REFINED_PATH, output)
    update_phase("refine", "completed")
    print(f"[OK] refined output saved to {REFINED_PATH}")


if __name__ == "__main__":
    refine()
