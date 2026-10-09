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
# The renderer declares no scope of its own: it reports the scope the run's
# artifacts declare, and refuses to render a single-scope report when they
# disagree.  ``advisory`` is only the pipeline default, never a renderer claim.
SCOPE_UNKNOWN = "unknown"
KNOWN_SCOPES = ("research_only", "advisory", "actionable")
# Authoritative order when several artifacts declare the same scope.
SCOPE_SOURCES = ("daily_run_summary", "weights", "daily_sync")
SECTIONS = (
    ("阶段状态", "daily_run_summary"),
    ("行情覆盖与时效", "quotes"),
    ("备用行情来源（主源失败后替代）", "quotes"),
    ("事件红队（Thesis）", "daily_sync"),
    ("当前权重", "weights"),
    ("仓位限制（策略派生）", "position_limits"),
    ("观察边界", "watchlist"),
    ("情景（如已运行）", "scenario"),
    ("风险诊断（部分覆盖）", "risk_diagnostic"),
    ("覆盖探针（如已运行）", "daily_run_summary"),
    ("可执行性就绪（actionable）", "daily_run_summary"),
)
ARTIFACTS = (
    ("daily_run_summary", "out/daily_run_summary.json"),
    ("weights", "out/weights.json"),
    ("position_limits", "out/position_limits.json"),
    ("watchlist", "out/watchlist_results.json"),
    ("quotes", "out/quotes.json"),
    ("daily_sync", "out/daily_sync.json"),
    ("daily_sync_with_thesis", "out/daily_sync_with_thesis.json"),
    ("scenario", "out/scenario_result.json"),
    ("risk_diagnostic", "out/risk_diagnostic.json"),
)
# Optional and deliberately *not* in ARTIFACTS: the actionability gate is a separate
# invocation, so its absence must not show up as a missing run artifact.  It is read
# only to raise or keep unverified the actionable prerequisites below.
READINESS_ARTIFACT = "out/actionability_assessment.json"
# Prerequisites that can never be closed from a run's own artifacts: they depend on
# account rules and a cost model held outside the run.  They are named as human gates
# instead of being silently counted as unverified evidence.
HUMAN_GATE_PREREQUISITES = ("账户规则与成本模型已由一手来源核验",)


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def fmt(value: Any, digits: int = 4) -> str:
    if isinstance(value, bool):
        # A boolean verdict is a result, not a missing value; "—" would hide it.
        return "true" if value else "false"
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return str(value)


def pct(value: Any, digits: int = 2) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value * 100:.{digits}f}%"
    return "—"


def declared_scopes(artifacts: dict[str, dict[str, Any] | None]) -> dict[str, str]:
    """Return artifact key -> declared decision scope for artifacts that declare one."""
    declared: dict[str, str] = {}
    for key, _relative in ARTIFACTS:
        payload = artifacts.get(key)
        if isinstance(payload, dict):
            value = payload.get("decision_scope")
            if isinstance(value, str) and value:
                declared[key] = value
    return declared


def resolve_scope(declared: dict[str, str]) -> tuple[str, str]:
    """Resolve the run's scope as ``(scope, source)`` without inventing one.

    Returns ``(SCOPE_UNKNOWN, "none")`` when no artifact declares a scope: an
    undeclared run must not inherit the pipeline default.
    """
    for key in SCOPE_SOURCES:
        if key in declared:
            return declared[key], key
    # An artifact-local label such as ``observation_only`` is not a run scope, so
    # a run whose primary artifacts declare nothing stays unknown.
    return SCOPE_UNKNOWN, "none"


def artifact_scope_annotations(declared: dict[str, str],
                               run_scope: str) -> list[dict[str, str]]:
    """Return artifact-local scope labels that are not run-scope declarations.

    ``out/position_limits.json`` labels itself ``observation_only`` because derived
    bounds only trigger research review; that is a property of the artifact, not a
    second decision scope for the run.  Such labels are reported, never silently
    dropped and never allowed to fail an otherwise consistent run.
    """
    annotations = []
    for key in sorted(declared):
        if key in SCOPE_SOURCES or declared[key] == run_scope:
            continue
        annotations.append({
            "artifact": key,
            "declared_scope": declared[key],
            "note": "artifact-local label, not a run decision scope",
        })
    return annotations


def scope_conflict(declared: dict[str, str]) -> list[str]:
    """Return inconsistent or unrecognised *run* scope declarations, if any.

    Only the primary artifacts count: they are the ones whose scope the run itself
    claims, so only they can contradict each other or carry an unknown value.
    """
    declared = {key: value for key, value in declared.items() if key in SCOPE_SOURCES}
    problems: list[str] = []
    values = sorted(set(declared.values()))
    if len(values) > 1:
        detail = ", ".join(f"{key}={declared[key]}" for key in sorted(declared))
        problems.append(f"decision_scope_conflict: {detail}")
    for value in values:
        if value not in KNOWN_SCOPES:
            problems.append(f"decision_scope_unrecognized: {value}")
    return problems


def _render_run_inventory(lines: list[str], summary: dict[str, Any] | None) -> None:
    """Render run validity and the stages that never ran, as gaps rather than blanks."""
    inventory = (summary or {}).get("run_inventory")
    lines.append("### run 清单（范围/时效/未运行阶段）")
    lines.append("")
    if not isinstance(inventory, dict) or not inventory:
        lines.append("缺口：缺少 run_inventory（无法判定本轮有效期与未运行阶段）")
        lines.append("")
        return
    freshness = inventory.get("freshness") or {}
    lines.append("- 声明范围：{scope}（阶段：{scopes}）".format(
        scope=fmt(inventory.get("decision_scope")),
        scopes=fmt(sorted((inventory.get("stage_scopes") or {}).items()))))
    lines.append("- 已运行阶段：{run}".format(run=fmt(inventory.get("stages_run"))))
    lines.append("- 有效期（保守下界）：{valid}（依据 {basis}；最新下界 {latest}）".format(
        valid=fmt(inventory.get("valid_until")),
        basis=fmt(inventory.get("valid_until_basis")),
        latest=fmt(freshness.get("latest_valid_until"))))
    not_run = inventory.get("stages_not_run") or []
    if not_run:
        for entry in not_run:
            reason = str(entry.get("reason") or "")
            extra = ("（调用方显式跳过）" if reason.startswith("skipped_by_flag")
                     else "（上游未完成或未请求）")
            lines.append("- 未运行阶段：{stage}｜{reason}{extra}".format(
                stage=fmt(entry.get("stage")), reason=fmt(reason), extra=extra))
    else:
        lines.append("- 未运行阶段：无")
    consistency = (summary or {}).get("status_consistency")
    if isinstance(consistency, dict):
        lines.append("- 状态一致性：顶层 {top}｜阶段推导 {derived}｜一致={ok}".format(
            top=fmt(consistency.get("top_level_status")),
            derived=fmt(consistency.get("stage_derived_status")),
            ok=fmt(consistency.get("consistent"))))
    lines.append("")


def _render_thesis(lines: list[str], artifacts: dict[str, dict[str, Any] | None],
                   tag: Any = None) -> None:
    """Render the event red-team verdict; an unassessed thesis is a gap, not silence."""
    tag = tag or (lambda _key: "")
    lines.append("## 事件红队（Thesis）" + tag("daily_sync"))
    lines.append("")
    thesis = None
    for key in ("daily_sync_with_thesis", "daily_sync"):
        payload = artifacts.get(key) or {}
        if isinstance(payload, dict) and isinstance(payload.get("thesis_red_team"), dict):
            thesis = payload["thesis_red_team"]
            break
    if not thesis:
        lines.append("缺口：未发现 thesis_red_team（本轮未评估事件红队，不得读作已评估无事件）")
        lines.append("")
        return
    lines.append("- 状态：{status}｜证据：{evidence}｜致命事件：{fatal}".format(
        status=fmt(thesis.get("status")),
        evidence=fmt(thesis.get("evidence_status")),
        fatal=fmt(thesis.get("fatal_event_status"))))
    lines.append("- 评估数：{count}｜证据数：{n}｜最早到期：{due}｜窗口：{start} → {end}".format(
        count=fmt(thesis.get("assessment_count")), n=fmt(thesis.get("evidence_count")),
        due=fmt(thesis.get("earliest_due_date")),
        start=fmt(thesis.get("window_start")), end=fmt(thesis.get("window_end"))))
    fatal_symbols = thesis.get("fatal_symbols") or []
    lines.append("- 已证伪标的：{symbols}".format(
        symbols=fmt(fatal_symbols) if fatal_symbols else "无（不代表没有未核验风险）"))
    assessments = thesis.get("assessments") or []
    if assessments:
        lines.append("")
        lines.append("| 标的 | 结论 | 到期日 | 证据数 | 条件 |")
        lines.append("|---|---|---|---|---|")
        for item in assessments:
            lines.append("| {symbol} | {conclusion} | {due} | {count} | {conditions} |".format(
                symbol=fmt(item.get("symbol")), conclusion=fmt(item.get("conclusion")),
                due=fmt(item.get("due_date")), count=len(item.get("evidence_ids") or []),
                conditions=fmt(item.get("condition_ids") or [])))
    for error in thesis.get("errors") or []:
        lines.append(f"- 错误：{fmt(error)}")
    lines.append("")


def _render_position_limits(lines: list[str], limits: dict[str, Any] | None,
                           tag: Any = None) -> None:
    """Render policy-derived limits; a missing block is a gap, never "no bounds"."""
    tag = tag or (lambda _key: "")
    lines.append("## 仓位限制（策略派生）" + tag("position_limits"))
    lines.append("")
    if not isinstance(limits, dict) or not limits:
        lines.append("缺口：缺少 out/position_limits.json（无法判定仓位上限与上限边界）")
        lines.append("")
        return
    rules = limits.get("rules") or {}
    lines.append("- 规则：单标的上限 {weight}｜单标的损失上限 {loss}｜上行/成本倍数 {multiple}".format(
        weight=fmt(rules.get("max_single_position_weight")),
        loss=fmt(rules.get("max_single_position_loss")),
        multiple=fmt(rules.get("upside_cost_multiple"))))
    generated_from = limits.get("generated_from") or {}
    lines.append("- 派生自：{policy}（sha256 {sha}；评估时点 {epoch}）".format(
        policy=fmt(generated_from.get("policy")),
        sha=str(generated_from.get("policy_sha256") or "—")[:12],
        epoch=fmt(generated_from.get("evaluation_epoch"))))
    positions = limits.get("positions") or []
    if positions:
        lines.append("")
        lines.append("| 标的 | 当前权重 | 权重上限 | 下行边界 | 上行边界 |")
        lines.append("|---|---|---|---|---|")
        for item in positions:
            boundaries = item.get("boundaries") or []
            downside = next((b for b in boundaries
                             if b.get("role") == "downside_boundary"), {})
            upside = next((b for b in boundaries
                           if b.get("role") == "upside_boundary"), {})
            lines.append("| {symbol} | {weight} | {cap} | {down} | {up} |".format(
                symbol=fmt(item.get("display_label") or item.get("symbol")),
                weight=fmt(item.get("current_weight")),
                cap=fmt(rules.get("max_single_position_weight")),
                down=fmt(downside.get("value")), up=fmt(upside.get("value"))))
    if limits.get("note"):
        lines.append(f"\n- 声明：{fmt(limits.get('note'))}")
    lines.append("")


def secondary_quotes(artifacts: dict[str, dict[str, Any] | None]) -> list[dict[str, Any]]:
    """Return the records this run filled from a labelled secondary source."""
    quotes = artifacts.get("quotes") or {}
    records = quotes.get("records") if isinstance(quotes.get("records"), list) else []
    secondary: list[dict[str, Any]] = []
    for record in records:
        provenance = (record.get("quote_provenance")
                      if isinstance(record, dict) and isinstance(record.get("quote_provenance"), dict)
                      else {})
        if str(provenance.get("tier") or "") == "secondary":
            secondary.append(provenance)
    return secondary


def actionable_readiness(artifacts: dict[str, dict[str, Any] | None],
                         assessment: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Derive actionable prerequisites from artifacts already in the run.

    Every row is ``verified`` (true / false / null = unknown).  Nothing here is
    inferred from absence: a prerequisite without evidence stays unverified, so a
    complete-looking run cannot pass itself off as ready to act on.
    """
    summary = artifacts.get("daily_run_summary") or {}
    quotes = artifacts.get("quotes") or {}
    audit = quotes.get("portfolio_batch_audit") or {}
    receipt = quotes.get("provider_receipt")
    if not isinstance(receipt, dict):
        receipt = (artifacts.get("daily_sync") or {}).get("supplied_provider_receipt")
    thesis = None
    for key in ("daily_sync_with_thesis", "daily_sync"):
        payload = artifacts.get(key) or {}
        if isinstance(payload.get("thesis_red_team"), dict):
            thesis = payload["thesis_red_team"]
            break
    unknowns = summary.get("residual_unknowns")
    structural = [item.get("kind") for item in unknowns or []
                  if isinstance(item, dict) and item.get("kind") in
                  ("account_rules_not_verified", "cost_model_not_sourced")]
    contracts = audit.get("quote_freshness_contracts") or {}
    closed = sorted(symbol for symbol, row in contracts.items()
                    if isinstance(row, dict) and row.get("market_state") != "REGULAR")

    rows: list[dict[str, Any]] = []
    rows.append({
        "prerequisite": "本轮整体状态为 complete",
        "verified": (None if not summary else summary.get("status") == "complete"),
        "evidence": f"status={fmt(summary.get('status'))} detail={fmt(summary.get('detail_status'))}",
    })
    rows.append({
        "prerequisite": "行情覆盖闭合",
        "verified": audit.get("coverage_complete") if audit else None,
        "evidence": f"coverage_complete={fmt(audit.get('coverage_complete'))}",
    })
    if isinstance(receipt, dict):
        counts = receipt.get("outcome_counts") or {}
        failed = {k: v for k, v in counts.items() if k != "ok" and v}
        labelled_secondary = secondary_quotes(artifacts)
        evidence = "outcome_counts=" + (json.dumps(counts, ensure_ascii=False) if counts
                                        else "—")
        if labelled_secondary:
            evidence += f"；已用标注的备用源替代 {len(labelled_secondary)} 个标的"
        rows.append({
            "prerequisite": "provider 无传输失败/未因熔断跳过",
            "verified": not failed and bool(counts.get("ok")),
            "evidence": evidence,
        })
    else:
        rows.append({"prerequisite": "provider 无传输失败/未因熔断跳过",
                     "verified": None, "evidence": "未发现 provider_receipt"})
    rows.append({
        "prerequisite": "Thesis 已评估（evidence_status=ok）",
        "verified": (None if thesis is None else thesis.get("evidence_status") == "ok"),
        "evidence": (f"evidence_status={fmt(thesis.get('evidence_status'))}"
                     if thesis else "未发现 thesis_red_team"),
    })
    rows.append({
        "prerequisite": "评估时点市场处于交易时段",
        "verified": (None if not contracts else not closed),
        "evidence": ("非交易时段：" + "、".join(closed)) if closed else
                    ("全部 REGULAR" if contracts else "无行情时效契约"),
    })
    if isinstance(assessment, dict):
        rows.append({
            "prerequisite": "actionability gate 快照裁决为 complete",
            "verified": assessment.get("status") == "complete",
            "evidence": "status={} detail={} actionability={}".format(
                fmt(assessment.get("status")), fmt(assessment.get("detail_status")),
                fmt(assessment.get("actionability") or assessment.get("verdict"))),
        })
    else:
        rows.append({"prerequisite": "actionability gate 快照裁决为 complete",
                     "verified": None,
                     "evidence": f"未提供 {READINESS_ARTIFACT}（本轮未运行 gate）"})
    rows.append({
        "prerequisite": "账户规则与成本模型已由一手来源核验",
        "verified": False if structural else None,
        "evidence": ("未核验：" + "、".join(sorted(set(structural)))) if structural
                    else "未声明 residual_unknowns，无法证明已核验",
    })
    return rows


def readiness_summary(artifacts: dict[str, dict[str, Any] | None],
                      assessment: dict[str, Any] | None, scope: str) -> dict[str, Any]:
    """Machine-readable version of the actionable readiness section.

    ``verdict`` is ``verified`` only when every prerequisite is proven; the two
    standing structural unknowns mean that stays a named outcome, never a silent
    default.  It is a statement of what this run established, not an order.
    """
    rows = actionable_readiness(artifacts, assessment)
    unmet = [row["prerequisite"] for row in rows if row["verified"] is not True]
    return {
        "scope": scope,
        "verdict": "verified" if not unmet else "not_ready",
        "prerequisite_count": len(rows),
        "unmet": unmet,
        "prerequisites": [
            {"prerequisite": row["prerequisite"],
             "verified": row["verified"],
             "evidence": row["evidence"]}
            for row in rows
        ],
        "gate_artifact_present": isinstance(assessment, dict),
        "statement": (
            "a verified prerequisite list is still not an order: execution stays "
            "human_review_required_no_order"
        ),
    }


def _render_actionable_readiness(lines: list[str],
                                 artifacts: dict[str, dict[str, Any] | None],
                                 run_dir: Path, scope: str, tag: Any = None) -> None:
    """List what actionable would require and how much of it is actually proven."""
    tag = tag or (lambda _key: "")
    lines.append("## 可执行性就绪（actionable）" + tag("daily_run_summary"))
    lines.append("")
    assessment = load_json(run_dir / READINESS_ARTIFACT)
    rows = actionable_readiness(artifacts, assessment)
    lines.append("本节只列前置条件与实际核验状态；\"未核验\"不得读作\"可行动\"，"
                 "核验通过也不产生下单授权（human_review_required_no_order）。")
    lines.append("")
    lines.append("| 前置条件 | 核验状态 | 证据 |")
    lines.append("|---|---|---|")
    labels = {True: "已核验", False: "未核验", None: "未提供"}
    for row in rows:
        lines.append("| {p} | {s} | {e} |".format(
            p=fmt(row.get("prerequisite")), s=labels.get(row.get("verified"), "未提供"),
            e=str(fmt(row.get("evidence"))).replace("|", "/")))
    unmet = [row["prerequisite"] for row in rows if row["verified"] is not True]
    if unmet:
        lines.append("")
        lines.append("裁决：本轮声明范围 {}；未核验项 {} 项（{}）→ 无论范围为何，均不得读作就绪。".format(
            fmt(scope), len(unmet), "；".join(unmet)))
    else:
        lines.append("")
        lines.append("裁决：全部前置条件均已核验；核验不等于下单授权。")
    lines.append("")


def _render_secondary_quotes(lines: list[str],
                            artifacts: dict[str, dict[str, Any] | None]) -> None:
    """Render labelled secondary quotes; an unused fallback stays invisible."""
    entries = secondary_quotes(artifacts)
    if not entries:
        return
    lines.append("## 备用行情来源（主源失败后替代）")
    lines.append("")
    lines.append("这些价格来自主源传输失败后的标注备用源，**不计为一次主源成功**；"
                 "未由该源提供的字段（如交易场所、证券类型、时效性）单列为未可核验。")
    lines.append("")
    lines.append("| 标的 | 来源 | 主源结果 | 观测时间 | 未可核验字段 |")
    lines.append("|---|---|---|---|---|")
    for entry in sorted(entries, key=lambda item: str(item.get("symbol"))):
        unverifiable = entry.get("unverifiable") or []
        lines.append("| {symbol} | {source} | {outcome} | {observed} | {fields} |".format(
            symbol=fmt(entry.get("symbol")), source=fmt(entry.get("source")),
            outcome=fmt(entry.get("primary_outcome")),
            observed=fmt(entry.get("observed_at")),
            fields="、".join(str(item) for item in unverifiable) if unverifiable else "—"))
    lines.append("")


def _render_residual_unknowns(lines: list[str], summary: dict[str, Any] | None,
                              tag: Any = None) -> None:
    """Render named unknowns; a summary that lists none is reported as a gap."""
    tag = tag or (lambda _key: "")
    lines.append("## 残余未知（本轮未建立）" + tag("daily_run_summary"))
    lines.append("")
    unknowns = (summary or {}).get("residual_unknowns")
    if not isinstance(unknowns, list):
        lines.append("缺口：缺少 residual_unknowns（无法区分“已验证”与“未核验”）")
        lines.append("")
        return
    if not unknowns:
        lines.append("缺口：residual_unknowns 为空列表（真实运行不存在零未知，按缺口处理）")
        lines.append("")
        return
    lines.append("| 类型 | 阶段 | 详情 | 含义 |")
    lines.append("|---|---|---|---|")
    for item in unknowns:
        if not isinstance(item, dict):
            lines.append("| malformed | — | — | 条目结构非法，按缺口处理 |")
            continue
        lines.append("| {kind} | {stage} | {detail} | {statement} |".format(
            kind=fmt(item.get("kind")), stage=fmt(item.get("stage")),
            detail=fmt(item.get("detail")).replace("|", "/"),
            statement=fmt(item.get("statement")).replace("|", "/")))
    lines.append("")


def _render_coverage_probes(lines: list[str], artifacts: dict[str, dict[str, Any] | None],
                            tag: Any = None) -> None:
    """Render probe verdicts; an unproven probe is data, an absent probe is a gap."""
    tag = tag or (lambda _key: "")
    lines.append("## 覆盖探针（如已运行）" + tag("daily_run_summary"))
    lines.append("")
    stages = ((artifacts.get("daily_run_summary") or {}).get("stages") or [])
    stage = next((item for item in stages
                  if isinstance(item, dict) and item.get("stage") == "coverage-probe"), None)
    if not stage:
        lines.append("- 本轮未运行覆盖探针（未提供探针规格）；不得读作“通道已证明”")
        lines.append("")
        return
    lines.append("- 阶段状态：{status}｜详情：{detail}".format(
        status=fmt(stage.get("status")), detail=fmt(stage.get("detail_status"))))
    probes = stage.get("probes") or []
    if probes:
        lines.append("")
        lines.append("| 通道 | 目标 | 对照 | 判定 | 命中/对照 | 官方覆盖就绪 |")
        lines.append("|---|---|---|---|---|---|")
        for probe in probes:
            lines.append("| {channel} | {target} | {control} | {verdict} | {hits}/{control_hits} | {ready} |".format(
                channel=fmt(probe.get("channel")), target=fmt(probe.get("target")),
                control=fmt(probe.get("control")), verdict=fmt(probe.get("verdict")),
                hits=fmt(probe.get("target_count")), control_hits=fmt(probe.get("control_count")),
                ready=fmt(probe.get("official_coverage_ready"))))
    unproven = stage.get("unproven_probes") or []
    lines.append("")
    if unproven:
        lines.append("- 未证明探针（不得当作已覆盖）：")
        for item in unproven:
            lines.append(f"  - {fmt(item)}")
    else:
        lines.append("- 未证明探针：无")
    lines.append("")


def render(run_dir: Path, artifacts: dict[str, dict[str, Any] | None],
           hashes: dict[str, str], scope: str = SCOPE_UNKNOWN,
           declared: dict[str, str] | None = None,
           annotations: list[dict[str, str]] | None = None) -> str:
    declared = declared or {}
    annotations = annotations or []
    scope_source = resolve_scope(declared)[1]

    local_labels = {item["artifact"]: item["declared_scope"] for item in annotations}

    def tag(key: str) -> str:
        value = declared.get(key)
        if value:
            if key in local_labels:
                return f"（制品自带标签：{value}；非 run 范围）"
            return f"（制品声明范围：{value}）"
        return ""

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
    lines.append(f"| 决策范围 | {fmt(scope)}（来源：{fmt(scope_source)}；渲染器不自称范围，不下单、不改持仓） |")
    lines.append("")

    lines.append("## 阶段状态" + tag("daily_run_summary"))
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
    _render_run_inventory(lines, summary)
    research_scope = (summary or {}).get("analysis_scope")
    held_only = (summary or {}).get("analysis_selection") == "held_only"
    if held_only:
        excluded = (research_scope or {}).get("excluded_unpurchased_symbols") or []
        lines.extend(["## 本次分析范围", "", "仅实仓（held_only）；未购标的为范围外，不称其已评估。",
                      "范围外未购标的：" + (", ".join(map(str, excluded)) or "无"), ""])
    research_stage = next((row for row in stages if row.get("stage") == "unpurchased_analysis"), None)
    if research_stage and held_only:
        lines.extend(["缺口：实仓限定范围与未购阶段声明冲突，不采用未购制品。", ""])
    if research_stage and not held_only:
        lines.extend(["", "## 未购证券：独立研究与计算", "",
                      "未购数量、市值及已投入成本为零；参考成本不计算浮盈亏，不加入实仓分母。"])
        if isinstance(research_scope, dict):
            lines.append("分析范围：实仓 {held} + 未购 {unheld} = {total} 个非现金证券。".format(
                held=research_scope.get("held_non_cash_count", "—"),
                unheld=research_scope.get("unpurchased_count", "—"),
                total=research_scope.get("analysis_non_cash_count", "—")))
        path = run_dir / "out" / "unpurchased_analysis.json"
        if research_stage.get("status") == "failed":
            lines.append("缺口：未购研究阶段失败；不能读取旧制品冒充本轮结果。")
            lines.append("预期证券：" + ", ".join(research_stage.get("expected_symbols") or []))
        elif not path.is_file():
            lines.append("缺口：未购研究制品缺失，未评估不等于未触发。")
        else:
            try:
                research = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as exc:
                lines.append(f"缺口：未购制品读取失败（{type(exc).__name__}）。")
            else:
                if not isinstance(research, dict) or research.get("evaluation_epoch") != epoch:
                    lines.append("缺口：未购制品不是本轮评估时点，不能沿用旧结果。")
                else:
                    lines.extend(["| 标的 | 行情 | 指示性PE | 相对基准估值% | Thesis | 观察边界 |",
                                  "|---|---|---|---|---|---|"])
                    for row in research.get("rows") or []:
                        valuation = row.get("valuation") or {}
                        boundary = row.get("observation_boundaries") or {}
                        lines.append("| {} | {} | {} | {} | {} | {} |".format(
                            fmt(" ".join(str(value) for value in (row.get("symbol"), row.get("name")) if value)),
                            fmt(row.get("quote_status")),
                            fmt(valuation.get("price_to_trailing_eps") if valuation.get("price_to_trailing_eps") is not None
                                else valuation.get("pe_reason")),
                            fmt(valuation.get("price_vs_base_value_pct")),
                            fmt(row.get("thesis_status")), fmt(boundary.get("detail_status") or boundary.get("status"))))
                    lines.append("第三方EPS/PE只作筛查；已计算行情或倍数不证明完整Thesis安全，也不产生买入指令。")

    lines.append("## 行情覆盖与时效" + tag("quotes"))
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
            for symbol in sorted(contracts):
                observation = (contracts[symbol] or {}).get('quote_observation') or {}
                if observation:
                    lines.append(f"- {symbol} 报价口径：{fmt(observation.get('session'))}；"
                                 f"价格字段 {fmt(observation.get('price_field'))}，"
                                 f"时间字段 {fmt(observation.get('timestamp_field'))}；"
                                 "盘前／盘后价格可能面临较低流动性与较宽价差，非可成交保证。")
    else:
        lines.append("缺口：缺少 out/quotes.json（无法渲染行情覆盖与时效）")
    receipt = (quotes or {}).get("provider_receipt")
    if not isinstance(receipt, dict):
        receipt = (artifacts.get("daily_sync") or {}).get("supplied_provider_receipt")
    lines.append("")
    if isinstance(receipt, dict) and receipt:
        lines.append(f"provider 回执：{fmt(receipt.get('provider'))} / {fmt(receipt.get('operation'))}；"
                     f"结果计数 {fmt(receipt.get('outcome_counts'))}；"
                     f"熔断签名 {fmt(receipt.get('circuit_breaker_signature'))}")
        for symbol, outcome in sorted((receipt.get("outcomes") or {}).items()):
            if outcome != "ok":
                lines.append(f"- {symbol}：{fmt(outcome)}（provider 层未取得元数据，不等于无报价）")
        if receipt.get("statement"):
            lines.append(f"- 声明：{receipt.get('statement')}")
    else:
        lines.append("缺口：未发现 provider 回执（无法区分 provider 故障与真实无数据）")
    lines.append("")

    _render_secondary_quotes(lines, artifacts)

    _render_thesis(lines, artifacts, tag)

    _render_position_limits(lines, artifacts.get("position_limits"), tag)

    lines.append("## 当前权重" + tag("weights"))
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

    lines.append("## 观察边界" + tag("watchlist"))
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

    lines.append("## 情景（如已运行）" + tag("scenario"))
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

    lines.append("## 风险诊断（部分覆盖）" + tag("risk_diagnostic"))
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

    _render_coverage_probes(lines, artifacts, tag)

    _render_residual_unknowns(lines, artifacts.get("daily_run_summary"), tag)

    _render_actionable_readiness(lines, artifacts, run_dir, scope, tag)

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
    lines.append("| 制品 | 声明范围 | SHA-256 |")
    lines.append("|---|---|---|")
    for key, relative in ARTIFACTS:
        if artifacts.get(key) is None:
            continue
        lines.append(f"| {relative} | {fmt(declared.get(key, 'undeclared'))} | "
                     f"{hashes.get(key, '—')} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render one run directory to Markdown.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out")
    parser.add_argument(
        "--expect-scope", choices=KNOWN_SCOPES,
        help="Fail closed unless the run's artifacts declare exactly this scope.",
    )
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.is_dir():
        print(json.dumps({"status": "failed", "detail_status": "run_dir_missing",
                          "errors": [str(run_dir)]},
                         ensure_ascii=False, indent=2))
        return 3
    artifacts: dict[str, dict[str, Any] | None] = {}
    hashes: dict[str, str] = {}
    for key, relative in ARTIFACTS:
        path = run_dir / relative
        artifacts[key] = load_json(path)
        if path.is_file():
            hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    summary = artifacts.get("daily_run_summary") or {}
    selection = summary.get("analysis_selection")
    if (selection not in (None, "all", "held_only") or
            selection == "held_only" and any(
                row.get("stage") == "unpurchased_analysis" for row in summary.get("stages") or [])):
        print(json.dumps({"status": "failed", "detail_status": "analysis_scope_conflict",
                          "errors": ["invalid analysis selection or unpurchased stage in held_only run"]},
                         ensure_ascii=False, indent=2))
        return 3
    declared = declared_scopes(artifacts)
    problems = scope_conflict(declared)
    if problems:
        print(json.dumps({"status": "failed", "detail_status": "decision_scope_conflict",
                          "declared_scopes": declared, "errors": problems},
                         ensure_ascii=False, indent=2))
        return 3
    scope, scope_source = resolve_scope(declared)
    annotations = artifact_scope_annotations(declared, scope)
    if args.expect_scope and scope != args.expect_scope:
        print(json.dumps({"status": "failed", "detail_status": "decision_scope_mismatch",
                          "declared_scopes": declared, "expected_scope": args.expect_scope,
                          "resolved_scope": scope,
                          "errors": [f"expected {args.expect_scope}, artifacts declare {scope}"]},
                         ensure_ascii=False, indent=2))
        return 3
    rendered = render(run_dir, artifacts, hashes, scope=scope, declared=declared,
                      annotations=annotations)
    missing = [relative for key, relative in ARTIFACTS if artifacts.get(key) is None]
    if scope == SCOPE_UNKNOWN:
        # A run whose artifacts never declared a scope cannot be presented as a
        # scoped deliverable; the report is still written so the gap is visible.
        scope_status, scope_detail = "incomplete", "decision_scope_unknown"
        exit_code = 1
    else:
        scope_status, scope_detail = "complete", "report_rendered"
        exit_code = 0
    if args.out:
        target = Path(args.out).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(rendered.encode("utf-8"))
        print(json.dumps({"status": scope_status, "detail_status": scope_detail,
                          "decision_scope": scope, "decision_scope_source": scope_source,
                          "schema_version": SCHEMA_VERSION,
                          "run_id": run_dir.name, "report_file": str(target),
                          "report_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
                          "missing_artifacts": missing,
                          "scope_annotations": annotations,
                          "actionable_readiness": readiness_summary(
                              artifacts, load_json(run_dir / READINESS_ARTIFACT), scope),
                          "errors": [] if scope != SCOPE_UNKNOWN else [scope_detail]},
                         ensure_ascii=False, indent=2))
        return exit_code
    print(rendered, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
