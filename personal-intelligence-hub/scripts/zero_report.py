from __future__ import annotations

from typing import Any


def semantic_data_gaps(
    supplement: dict[str, Any],
    mix: dict[str, Any],
) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    for result in supplement.get("results", []):
        if not isinstance(result, dict):
            continue
        coverage = result.get("coverage") or {}
        failed = int(coverage.get("failed", 0))
        if result.get("status") not in {"degraded", "failed"} and failed == 0:
            continue
        gap_id = str(result.get("gap_id") or "supplement-coverage")
        lane = str(result.get("lane") or "supplement")
        gaps.append(
            {
                "gap_id": gap_id,
                "lane": lane,
                "status": "open",
                "description": f"补检车道状态为 {result.get('status')}，并保留 {failed} 条受阻访问。",
                "impact": "该车道的事件供给与结论覆盖置信度降低。",
            }
        )
    supply = mix.get("supply_exception") or {}
    if supply.get("applied") is True:
        missing = "、".join(str(value) for value in supply.get("missing_domains", []))
        gaps.append(
            {
                "gap_id": "verified-domain-supply",
                "lane": "SemanticEvaluator",
                "status": "open",
                "description": f"登记且已核验的候选供给不足，未达到请求比例：{missing}。",
                "impact": "正式条目领域比例偏离请求比例，不以弱证据补数。",
            }
        )
    return gaps



def zero_report_fields() -> dict[str, Any]:
    """Empty selections describe collection sufficiency, never the market."""
    return {
        "punchline": "本次运行正式入选条目为零，采集与合格证据供给不足以形成资讯简报判断。",
        "insights": "零入选仅描述本次运行的筛选结果，不证明市场静默、没有创新或没有重大事件。",
        "digest": "本次运行没有正式入选事件；具体来源与车道缺口见登记覆盖和 data_gaps，不将零入选等同于所有来源失败。",
        "market": "现有入选证据不足以判断市场活动或趋势，即使来源均成功返回，也只能说明本次运行未产出合格入选事件。",
        "action_levers": [{
            "domain": "coverage",
            "task": "核对登记的覆盖、候选淘汰原因与未闭合缺口；仅在用户授权范围和既有预算内修复采集与证据核验。",
            "owner_type": "情报运营",
            "trigger": "本次运行正式入选条目为零",
            "indicator": "登记缺口与候选处置可追溯；不以弱证据补数，不据此作市场决策。",
        }],
    }


def zero_supply_gap() -> dict[str, str]:
    return {
        "gap_id": "zero-selected-supply",
        "lane": "SemanticEvaluator",
        "status": "open",
        "description": "本次运行通过证据门与语义选择后正式入选事件为零；这不等于所有来源失败，也不等于市场没有事件。",
        "impact": "采集与合格入选证据供给不足，无法据此形成市场结论或业务行动；保留已有用户约束与具体证据缺口。",
    }


def zero_report_data_gaps(
    supplement: dict[str, Any], mix: dict[str, Any], baseline_coverage: dict[str, Any]
) -> list[dict[str, str]]:
    gaps = semantic_data_gaps(supplement, mix)
    for index, reason in enumerate(baseline_coverage.get("reasons", [])):
        gaps.append({
            "gap_id": f"baseline-coverage-{index + 1}",
            "lane": "baseline",
            "status": "open",
            "description": str(reason),
            "impact": "登记的基线覆盖限制仍未闭合。",
        })
    return gaps + [zero_supply_gap()]
