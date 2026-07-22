import argparse
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from advice_journal import load_entries, resolve_journal_path


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def calculate_calibration(entries: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        entry
        for entry in entries
        if entry.get("executed") is True
        and entry.get("calibration_eligible") is True
        and entry.get("net_excess_return_pct") is not None
    ]
    observed = [
        entry
        for entry in eligible
        if entry.get("calibration_quality") != "assumption_based_conservative"
    ]
    assumption_based = [
        entry
        for entry in eligible
        if entry.get("calibration_quality") == "assumption_based_conservative"
    ]
    net_returns = [float(entry["net_excess_return_pct"]) for entry in observed]
    assumption_returns = [float(entry["net_excess_return_pct"]) for entry in assumption_based]
    by_horizon: dict[int, list[float]] = defaultdict(list)
    by_confidence: dict[str, list[float]] = defaultdict(list)
    for entry in observed:
        horizon = int(entry["investment_horizon_days"])
        by_horizon[horizon].append(float(entry["net_excess_return_pct"]))
        by_confidence[str(entry.get("confidence_level") or "unknown")].append(
            float(entry["net_excess_return_pct"])
        )
    exclusion_reasons = Counter(
        str(entry.get("calibration_exclusion_reason") or "not eligible")
        for entry in entries
        if entry not in eligible
    )
    return {
        "eligible": eligible,
        "eligible_count": len(eligible),
        "observed_count": len(observed),
        "assumption_based_count": len(assumption_based),
        "excluded_count": len(entries) - len(eligible),
        "average_net_excess_return_pct": _mean(net_returns),
        "assumption_based_average_net_excess_return_pct": _mean(assumption_returns),
        "positive_excess_hit_rate_pct": (
            round(sum(value > 0 for value in net_returns) / len(net_returns) * 100, 2)
            if net_returns
            else None
        ),
        "by_horizon": {
            horizon: {"count": len(values), "average_net_excess_return_pct": _mean(values)}
            for horizon, values in sorted(by_horizon.items())
        },
        "by_confidence": {
            confidence: {"count": len(values), "average_net_excess_return_pct": _mean(values)}
            for confidence, values in sorted(by_confidence.items())
        },
        "exclusion_reasons": dict(exclusion_reasons),
    }


def build_report(journal_path: str | None = None) -> str:
    entries = load_entries(journal_path)
    calibration = calculate_calibration(entries)
    average = calibration["average_net_excess_return_pct"]
    hit_rate = calibration["positive_excess_hit_rate_pct"]
    lines = [
        "# Strategy Calibration Report",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 日志文件: {resolve_journal_path(journal_path)}",
        f"- 总样本数: {len(entries)}",
        f"- 可校准样本数: {calibration['eligible_count']}",
        f"- 观测型样本数: {calibration['observed_count']}",
        f"- 保守假设样本数: {calibration['assumption_based_count']}",
        f"- 排除样本数: {calibration['excluded_count']}",
        f"- 观测型平均净超额收益率: {f'{average:+.2f}%' if average is not None else 'N/A'}",
        f"- 正净超额收益命中率: {f'{hit_rate:.2f}%' if hit_rate is not None else 'N/A'}",
        "",
        "> 主指标只统计观测型样本；日线双触发且缺少可判序盘中数据时，按保守止损优先单独统计，不与主指标混合。",
        "",
        "## 分期限校准",
        "",
        "| 期限（天） | 样本数 | 平均净超额收益率 |",
        "|---:|---:|---:|",
    ]
    if calibration["by_horizon"]:
        for horizon, item in calibration["by_horizon"].items():
            lines.append(
                f"| {horizon} | {item['count']} | {item['average_net_excess_return_pct']:+.2f}% |"
            )
    else:
        lines.append("| - | 0 | N/A |")

    lines.extend(["", "## 置信度校准", "", "| 置信度 | 样本数 | 平均净超额收益率 |", "|:---|---:|---:|"])
    if calibration["by_confidence"]:
        for confidence, item in calibration["by_confidence"].items():
            lines.append(
                f"| {confidence} | {item['count']} | {item['average_net_excess_return_pct']:+.2f}% |"
            )
    else:
        lines.append("| - | 0 | N/A |")

    lines.extend(["", "## 样本排除原因", ""])
    if calibration["exclusion_reasons"]:
        for reason, count in sorted(calibration["exclusion_reasons"].items()):
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- 无")

    lines.extend(
        [
            "",
            "## 可校准样本",
            "",
            "| 日期 | 标的 | 方向 | 期限 | 质量 | 解析方法 | 标的收益 | 基准收益 | 净超额收益 |",
            "|:---|:---|:---:|---:|:---|:---|---:|---:|---:|",
        ]
    )
    for entry in sorted(calibration["eligible"], key=lambda item: item.get("created_at", ""), reverse=True):
        lines.append(
            "| {date} | {symbol} | {direction} | {horizon} | {quality} | {method} | {asset:+.2f}% | {benchmark:+.2f}% | {excess:+.2f}% |".format(
                date=str(entry.get("created_at", ""))[:10],
                symbol=entry.get("stock_name") or entry.get("stock_code"),
                direction=entry.get("position_direction"),
                horizon=entry.get("investment_horizon_days"),
                quality=entry.get("calibration_quality") or "observed",
                method=entry.get("outcome_resolution_method") or "legacy",
                asset=float(entry.get("outcome_return_pct", 0)),
                benchmark=float(entry.get("benchmark_return_pct", 0)),
                excess=float(entry.get("net_excess_return_pct", 0)),
            )
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate benchmark-aware calibration from an advice journal.")
    parser.add_argument("--journal-path")
    parser.add_argument(
        "--output-path",
        default=os.environ.get("PIA_CALIBRATION_REPORT"),
        help="Required output path; alternatively set PIA_CALIBRATION_REPORT.",
    )
    args = parser.parse_args()
    if not args.output_path:
        parser.error("output path is required; pass --output-path or set PIA_CALIBRATION_REPORT")
    report = build_report(args.journal_path)
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"report written: {output_path}")
