from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from blackboard import finalize_briefing, update_phase
from briefing_gate import validate_briefing_data
from history_manager import generate_fingerprint, save_history
from hub_utils import HUB_DIR, LATEST_SCAN_PATH, NEWS_DIR, REFINED_PATH, RUNTIME_DIR, dump_json, ensure_runtime_dirs, load_json


def build_grouped_list(scan_data: dict, focus_data: dict, included_urls: set[str]) -> tuple[dict, int]:
    themes = focus_data.get("themes", [])
    grouped = {theme["name"]: [] for theme in themes}
    grouped["Other Watchlist"] = []
    noise_count = 0
    for item in scan_data.get("items", []):
        if item.get("url") in included_urls:
            continue
        matched = False
        text = (item.get("title", "") + " " + item.get("raw_desc", "")).lower()
        for theme in themes:
            if any(keyword.lower() in text for keyword in theme.get("keywords", [])):
                grouped[theme["name"]].append(
                    {
                        "title": item.get("title", "Untitled"),
                        "url": item.get("url", ""),
                        "date": item.get("time", "Unknown")[:10],
                        "desc": item.get("raw_desc", "")[:150],
                    }
                )
                matched = True
                break
        if not matched:
            desc = item.get("raw_desc", "")
            if not desc:
                noise_count += 1
                continue
            grouped["Other Watchlist"].append(
                {
                    "title": item.get("title", "Untitled"),
                    "url": item.get("url", ""),
                    "date": item.get("time", "Unknown")[:10],
                    "desc": desc[:150],
                }
            )
    return {k: v for k, v in grouped.items() if v}, noise_count


def forge_briefing() -> None:
    ensure_runtime_dirs()
    update_phase("forge", "running")
    scan_data = load_json(LATEST_SCAN_PATH, {})
    refined = load_json(REFINED_PATH, {})
    focus = load_json(HUB_DIR / "references" / "strategic_focus.json", {})

    if not scan_data or not refined:
        print("[FAIL] missing scan or refined data")
        return

    top_10 = refined.get("top_10", [])[: focus.get("filters", {}).get("max_top10", 10)]
    included_urls = {item.get("url") for item in top_10}
    grouped_list, noise_count = build_grouped_list(scan_data, focus, included_urls)

    save_path = NEWS_DIR / f"intelligence_{datetime.now().strftime('%Y%m%d')}_briefing.md"
    template_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "punchline": refined.get("punchline", ""),
        "insights": refined.get("insights", ""),
        "digest": refined.get("digest", ""),
        "market": refined.get("market", ""),
        "urgent_signals": refined.get("urgent_signals", []),
        "action_levers": refined.get("action_levers", []),
        "adversarial_audit": refined.get("adversarial_audit"),
        "top_10": [
            {
                "title": item.get("title_zh", item.get("title", "Untitled")),
                "url": item.get("url", ""),
                "source": item.get("source", "Unknown"),
                "score": item.get("strategic_score", 0),
                "summary": item.get("summary_zh", item.get("summary", "")),
                "reason": item.get("reason", ""),
                "fact": item.get("fact", ""),
                "connection": item.get("connection", ""),
                "deduction": item.get("deduction", ""),
                "actionability": item.get("actionability", ""),
                "confidence": item.get("confidence", "medium"),
                "intelligence_level": item.get("intelligence_level", "L2"),
            }
            for item in top_10
        ],
        "grouped_list": grouped_list,
        "noise_count": noise_count,
        "save_path": str(save_path),
        "runtime_path": str(RUNTIME_DIR),
    }

    errors = validate_briefing_data(template_data)
    if errors:
        print("[FAIL] briefing gate blocked forge")
        for error in errors:
            print(f"- {error}")
        return

    env = Environment(
        loader=FileSystemLoader(str(HUB_DIR / "references")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("briefing_template.md")
    final_md = template.render(**template_data)

    save_path.write_text(final_md, encoding="utf-8")
    snapshot_path = save_path.with_suffix(".json")
    dump_json(snapshot_path, template_data)
    save_history(
        [item["url"] for item in template_data["top_10"]],
        [generate_fingerprint(item["title"], item["source"]) for item in template_data["top_10"]],
    )
    finalize_briefing(str(save_path))
    update_phase("forge", "completed")
    print(f"[OK] briefing saved to {save_path}")


if __name__ == "__main__":
    forge_briefing()
