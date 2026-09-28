#!/usr/bin/env python3
"""Render one run directory into a stable Markdown report.

Why this exists: every run hand-wrote its own report structure, so runs could not
be compared and the same numbers were transcribed by hand.

Boundaries: the renderer adds no judgement — it only formats values found in the
run's JSON artifacts and names every missing artifact as a gap.  Output is
deterministic (no render timestamp), so two renders of the same run are
byte-identical and can be hashed or diffed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "pia_run_report_v1"
DECISION_SCOPE = "research_only"
ARTIFACTS = (
    ("daily_run_summary", "out/daily_run_summary.json"),
    ("weights", "out/weights.json"),
    ("watchlist", "out/watchlist_results.json"),
    ("quotes", "out/quotes.json"),
    ("daily_sync", "out/daily_sync.json"),
    ("scenario", "out/scenario_result.json"),
    ("risk_diagnostic", "out/risk_diagnostic.json"),
)


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def fmt(value: Any, digits: int = 4) -> str:
    if isinstance(value, bool) or value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return str(value)


def pct(value: Any, digits: int = 2) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value * 100:.{digits}f}%"
    return "—"


def render(run_dir: Path, artifacts: dict[str, dict[str, Any] | None],
           hashes: dict[str, str]) -> str:
    summary = artifacts.get("daily_run_summary")
    weights = artifacts.get("weights")
    watchlist = artifacts.get("watchlist")
    quotes = artifacts.get("quotes")
    scenario = artifacts.get("scenario")

    run_id = run_dir.name
    epoch = (summary or weights or {}).get("evaluation_epoch")
    status = (summary or weights or {}).get("status")
    lines: list[str] = []
    lines.append(f"# 运行报告：{run_id}")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 运行目录 | {run_dir} |")
    lines.append(f"| 运行状态 | {fmt(status)}（{fmt((summary or weights or {}).get('detail_status'))}） |")
    lines.append(f"| 评估时点(epoch) | {fmt(epoch)} |")
    lines.append(f"| 生成时点 | {fmt((summary or {}).get('generated_at'))} |")
    lines.append(f"| 持仓输入哈希 | {fmt((summary or {}).get('positions_input_sha256'))} |")
    lines.append(f"| 决策范围 | {DECISION_SCOPE}（由渲染器声明；不下单、不改持仓） |")
    lines.append("")

    lines.append("## 阶段状态")
    lines.append("")
    stages = (summary or {}).get("stages") or []
    if stages:
        lines.append("| 阶段 | 状态 | 详情 | 退出码 | 制品数 |")
        lines.append("|---|---|---|---|---|")
        for stage in stages:
            lines.append("| {stage} | {status} | {detail} | {exit_code} | {count} |".format(
                stage=fmt(stage.get("stage")), status=fmt(stage.get("status")),
                detail=fmt(stage.get("detail_status")), exit_code=fmt(stage.get("exit_code")),
                count=len(stage.get("artifacts") or [])))
    else:
        lines.append("缺口：缺少 out/daily_run_summary.json 的 stages（无法渲染阶段表）")
    lines.append("")

    lines.append("## 行情覆盖与时效")
    lines.append("")
    audit = ((quotes or {}).get("portfolio_batch_audit") or {})
    if audit:
        lines.append(f"- 请求/返回/身份匹配/预期：{fmt(audit.get('requested_count'))} / "
                     f"{fmt(audit.get('result_record_count'))} / "
                     f"{fmt(audit.get('portfolio_matched_count'))} / "
                     f"{len(audit.get('expected_active_symbols') or [])}")
        lines.append(f"- coverage_complete：{fmt(audit.get('coverage_complete'))}；"
                     f"strict_quote_contract：{fmt(audit.get('strict_quote_contract'))}")
        contracts = audit.get("quote_freshness_contracts") or {}
        if contracts:
            lines.append("")
            lines.append("| 标的 | 市场状态 | 报价年龄(s) | 上限(s) | 状态 |")
            lines.append("|---|---|---|---|---|")
            for symbol in sorted(contracts):
                row = contracts[symbol] or {}
                lines.append(f"| {symbol} | {fmt(row.get('market_state'))} | "
                             f"{fmt(row.get('quote_age_seconds'), 1)} | "
                             f"{fmt(row.get('applied_max_age_seconds'), 0)} | "
                             f"{fmt(row.get('status'))} |")
    else:
        lines.append("缺口：缺少 out/quotes.json（无法渲染行情覆盖与时效）")
    lines.append("")

    lines.append("## 当前权重")
    lines.append("")
    rows = (weights or {}).get("current_weights") or []
    if rows:
        ordered = sorted(rows, key=lambda row: -(row.get("current_weight") or 0))
        lines.append("| # | 标的 | 权重 | 市值(基础币种) | 币种 | 报价时点 |")
        lines.append("|---|---|---|---|---|---|")
        for index, row in enumerate(ordered, 1):
            lines.append(f"| {index} | {fmt(row.get('symbol'))} | {pct(row.get('current_weight'))} | "
                         f"{fmt(row.get('market_value_base'), 2)} | {fmt(row.get('currency'))} | "
                         f"{fmt((row.get('quote') or {}).get('as_of'))} |")
    else:
        lines.append("缺口：缺少 out/weights.json 的 current_weights（无法渲染权重）")
    lines.append("")

    lines.append("## 观察边界")
    lines.append("")
    if isinstance(watchlist, dict) and watchlist:
        lines.append("| 标的 | 状态 | 详情 | 越界边界 |")
        lines.append("|---|---|---|---|")
        for symbol in sorted(watchlist):
            entry = watchlist[symbol] or {}
            categories = entry.get("categories") or {}
            crossed = (categories.get("downside_boundary_crossed") or []) + \
                      (categories.get("upside_boundary_crossed") or [])
            lines.append(f"| {symbol} | {fmt(entry.get('status'))} | "
                         f"{fmt(entry.get('detail_status'))} | "
                         f"{', '.join(crossed) if crossed else '—'} |")
    else:
        lines.append("缺口：缺少 out/watchlist_results.json（观察边界未评估，不等于未越界）")
    lines.append("")

    lines.append("## 情景（如已运行）")
    lines.append("")
    if scenario:
        for result in scenario.get("scenario_results") or []:
            lines.append(f"- {fmt(result.get('name'))}：组合收益 "
                         f"{pct(result.get('portfolio_return_before_cost'))}"
                         f"（成本后 {pct(result.get('portfolio_return_after_cost'))}）")
        for policy in scenario.get("bucket_policy_results") or []:
            for bucket in policy.get("buckets") or []:
                lines.append(f"- 桶 {fmt(bucket.get('id'))}：范围内权重 "
                             f"{pct(bucket.get('weight_within_scope'))}，目标 "
                             f"{pct(bucket.get('target_weight'))}，偏离 "
                             f"{pct(bucket.get('deviation'))}")
    else:
        lines.append("缺口：本运行未产出 out/scenario_result.json")
    lines.append("")

    lines.append("## 风险诊断（部分覆盖）")
    lines.append("")
    risk = artifacts.get("risk_diagnostic")
    if risk and isinstance(risk.get("coverage"), dict):
        coverage = risk["coverage"]
        lines.append(f"- 覆盖：{coverage.get('covered_count')} / "
                     f"{coverage.get('active_non_cash_count')} 个非现金标的；"
                     f"覆盖非现金市值 {pct(coverage.get('covered_share_of_non_cash_value'))}")
        lines.append(f"- 声明：{coverage.get('statement')}")
        excluded = coverage.get("excluded_symbols") or []
        if excluded:
            lines.append("- 排除：" + "；".join(f"{row.get('symbol')}（{row.get('reason')}）"
                                                   for row in excluded))
        contributions = risk.get("risk_contribution_within_subset") or {}
        volatilities = risk.get("annualized_volatility") or {}
        if contributions:
            lines.append("")
            lines.append("| 标的 | 子集内权重 | 年化波动 | 子集内风险贡献 |")
            lines.append("|---|---|---|---|")
            weights_map = risk.get("renormalized_weights_within_subset") or {}
            for symbol in sorted(contributions, key=lambda item: -(contributions[item] or 0)):
                lines.append(f"| {symbol} | {pct(weights_map.get(symbol))} | "
                             f"{pct(volatilities.get(symbol))} | {pct(contributions.get(symbol))} |")
        window = risk.get("observation_window") or {}
        lines.append(f"- 观测窗口：{fmt(window.get('first'))} 至 {fmt(window.get('last'))}"
                     f"（共同观测 {fmt(window.get('common_observations'))}）")
        value_coverage = risk.get("value_coverage") or {}
        if value_coverage:
            lines.append("")
            lines.append("| 组合市值分部 | 占比 |")
            lines.append("|---|---|")
            lines.append(f"| 已测量权益子集 | "
                         f"{pct(value_coverage.get('equity_covered_share_of_portfolio_value'))} |")
            lines.append(f"| 已建模外币现金（汇率） | "
                         f"{pct(value_coverage.get('fx_modelled_cash_share_of_portfolio_value'))} |")
            lines.append(f"| 本币现金（无汇率风险） | "
                         f"{pct(value_coverage.get('base_currency_cash_share_of_portfolio_value'))} |")
            lines.append(f"| 未测量（权益缺口 + 未建模现金） | "
                         f"{pct(value_coverage.get('unmeasured_share_of_portfolio_value'))} |")
        cash = risk.get("cash_fx_risk") or {}
        if cash:
            lines.append("")
            lines.append("现金汇率风险（本币=" + fmt(risk.get("base_currency")) + "）")
            lines.append("")
            legs = cash.get("legs") or []
            if legs:
                lines.append("| 现金 | 币对 | 组合占比 | 汇率年化波动 | 独立加权波动 |")
                lines.append("|---|---|---|---|---|")
                for leg in legs:
                    lines.append(f"| {leg.get('symbol')} | {leg.get('pair')} | "
                                 f"{pct(leg.get('weight_of_portfolio_value'))} | "
                                 f"{pct(leg.get('annualized_fx_volatility'))} | "
                                 f"{pct(leg.get('standalone_weighted_volatility'))} |")
            else:
                lines.append("- 无已建模的汇率腿")
            for item in cash.get("base_currency_cash") or []:
                lines.append(f"- {item.get('symbol')}：本币现金，不承担汇率风险")
            for item in cash.get("unmeasured_cash") or []:
                lines.append(f"- 未测量：{item.get('symbol')}（{item.get('reason')}）")
            combination = cash.get("measured_legs_combination") or {}
            bounds = combination.get("correlation_bounds") or {}
            if bounds:
                lines.append(f"- 仅合并已测量腿：权益腿 {pct((combination.get('equity_leg') or {}).get('weighted'))}、"
                             f"汇率腿 {pct((combination.get('fx_leg') or {}).get('weighted_sum_of_standalone_legs'))}；"
                             f"零相关点估计 {pct(combination.get('assumed_zero_correlation_point_estimate'))}，"
                             f"相关系数 [−1, 1] 区间 [{pct(bounds.get('lower'))}, {pct(bounds.get('upper'))}]")
                uncovered = combination.get("excluded_from_this_combination") or []
                if uncovered:
                    lines.append(f"- 未纳入区间：{'、'.join(uncovered)}")
                if combination.get("statement"):
                    lines.append(f"- 声明：{combination.get('statement')}")
    else:
        lines.append("缺口：本运行未产出 out/risk_diagnostic.json")
    lines.append("")

    lines.append("## 缺口与制品")
    lines.append("")
    missing = [relative for key, relative in ARTIFACTS
               if artifacts.get(key) is None]
    if missing:
        for relative in missing:
            lines.append(f"- 缺口：缺少 {relative}")
    else:
        lines.append("- 未发现缺失的已知制品")
    lines.append("")
    lines.append("| 制品 | SHA-256 |")
    lines.append("|---|---|")
    for key, relative in ARTIFACTS:
        if artifacts.get(key) is None:
            continue
        lines.append(f"| {relative} | {hashes.get(key, '—')} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render one run directory to Markdown.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.is_dir():
        print(json.dumps({"status": "failed", "detail_status": "run_dir_missing",
                          "decision_scope": DECISION_SCOPE, "errors": [str(run_dir)]},
                         ensure_ascii=False, indent=2))
        return 3
    artifacts: dict[str, dict[str, Any] | None] = {}
    hashes: dict[str, str] = {}
    for key, relative in ARTIFACTS:
        path = run_dir / relative
        artifacts[key] = load_json(path)
        if path.is_file():
            hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    rendered = render(run_dir, artifacts, hashes)
    if args.out:
        target = Path(args.out).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(rendered.encode("utf-8"))
        print(json.dumps({"status": "complete", "detail_status": "report_rendered",
                          "decision_scope": DECISION_SCOPE, "schema_version": SCHEMA_VERSION,
                          "run_id": run_dir.name, "report_file": str(target),
                          "report_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
                          "missing_artifacts": [relative for key, relative in ARTIFACTS
                                                if artifacts.get(key) is None]},
                         ensure_ascii=False, indent=2))
        return 0
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
