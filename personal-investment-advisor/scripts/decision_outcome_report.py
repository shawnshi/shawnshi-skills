import argparse
from datetime import datetime
from pathlib import Path

from advice_journal import load_entries, resolve_journal_path


DEFAULT_REPORT_PATH = Path.home() / ".gemini" / "MEMORY" / "raw" / "stocks" / "strategy_calibration.md"


def build_report(journal_path: str | None = None) -> str:
    entries = load_entries(journal_path)
    total = len(entries)
    reviewed = [entry for entry in entries if entry.get("outcome_return_pct") is not None]
    buys = [entry for entry in reviewed if entry.get("decision_type") == "buy"]
    holds = [entry for entry in reviewed if entry.get("decision_type") == "hold"]
    avg_reviewed = round(sum(entry["outcome_return_pct"] for entry in reviewed) / len(reviewed), 2) if reviewed else None
    avg_buy = round(sum(entry["outcome_return_pct"] for entry in buys) / len(buys), 2) if buys else None
    avg_hold = round(sum(entry["outcome_return_pct"] for entry in holds) / len(holds), 2) if holds else None
    hit_rate = round(sum(1 for entry in reviewed if entry["outcome_return_pct"] > 0) / len(reviewed) * 100, 2) if reviewed else None

    lines = [
        "# Strategy Calibration Report",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 日志文件: {resolve_journal_path(journal_path)}",
        f"- 总建议数: {total}",
        f"- 已回看样本数: {len(reviewed)}",
        f"- 回看平均收益率: {avg_reviewed if avg_reviewed is not None else 'N/A'}",
        f"- 买入建议平均收益率: {avg_buy if avg_buy is not None else 'N/A'}",
        f"- 持有建议平均收益率: {avg_hold if avg_hold is not None else 'N/A'}",
        f"- 正收益命中率: {hit_rate if hit_rate is not None else 'N/A'}%",
        "",
        "## Calibration Notes",
        ""
    ]

    if not reviewed:
        lines.append("- 当前缺少已回看样本，无法形成稳定校准结论。")
    else:
        if hit_rate is not None and hit_rate < 45:
            lines.append("- 建议命中率偏低，说明当前框架可能过度自信或入场时点滞后。")
        if avg_buy is not None and avg_buy < 0:
            lines.append("- 买入建议的平均后验收益为负，优先检查追高和 thesis 证据质量。")
        if avg_hold is not None and avg_hold < 0:
            lines.append("- 持有建议的后验收益偏弱，优先检查止损和减仓纪律是否过松。")
        if hit_rate is not None and hit_rate >= 55:
            lines.append("- 当前策略校准处于可接受区间，但仍需要更多样本分市场复核。")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a calibration report from advice journal.")
    parser.add_argument("--journal-path")
    parser.add_argument("--output-path", default=str(DEFAULT_REPORT_PATH))
    args = parser.parse_args()

    report = build_report(args.journal_path)
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"report written: {output_path}")
