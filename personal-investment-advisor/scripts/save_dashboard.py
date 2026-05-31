import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from advice_journal import append_entry
from dashboard_gate import validate_dashboard


def safe_print(message: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def render_markdown(data, raw_json):
    stock_name = data.get("stock_name", "Unknown")
    stock_code = data.get("stock_code", "Unknown")
    market_type = data.get("market_type", "")
    trend = data.get("trend_prediction", "")
    advice = data.get("operation_advice", "")
    confidence = data.get("confidence_level", "")
    tags = data.get("tags", [])

    db = data.get("dashboard", {})
    cc = db.get("core_conclusion", {})
    qa = db.get("qualitative_analysis", {})
    dp = db.get("data_perspective", {})
    intel = db.get("intelligence", {})
    bp = db.get("battle_plan", {})
    portfolio = data.get("portfolio_context", {})
    portfolio_summary = data.get("portfolio_summary", {})
    portfolio_risk = data.get("portfolio_risk", {})
    portfolio_fit = data.get("portfolio_fit", {})
    position_advice = data.get("position_advice", {})
    confidence_details = data.get("confidence_details", {})
    freshness_flags = data.get("freshness_flags", {})
    earnings_snapshot = data.get("earnings_snapshot", {})
    catalyst_map = data.get("catalyst_map", {})
    evidence_items = data.get("evidence_items", [])
    watchlist_alerts = data.get("watchlist_alerts", [])

    md = "---\n"
    md += f"title: {stock_name} ({stock_code}) 深度研究报告\n"
    md += f"date: {datetime.now().strftime('%Y-%m-%d')}\n"
    md += "status: archived\n"
    md += "author: stock_analyzer\n"
    if tags:
        md += f"tags: [{', '.join(tags)}]\n"
    md += "---\n\n"

    md += f"# 决策仪表盘: {stock_name} ({stock_code} - {market_type})\n\n"
    md += f"> 本报告由 `stock_analyzer` 基于结构化行情数据生成。置信度：**{confidence}**\n\n"

    md += "## 🟢 核心判词 (Executive Summary)\n"
    md += f"**{cc.get('one_sentence', '无')}**\n\n"
    md += f"- **信号状态**: {cc.get('signal_type', '无')}\n"
    md += f"- **操作建议**: {advice} (趋势预期: {trend})\n"
    md += f"- **时间窗口**: {cc.get('time_sensitivity', '无')}\n"
    md += f"- **研究模式**: {data.get('research_mode', '无')}\n"
    pos_advice = cc.get("position_advice", {})
    md += f"- **空仓建议**: {pos_advice.get('no_position', '无')}\n"
    md += f"- **持仓建议**: {pos_advice.get('has_position', '无')}\n\n"

    md += "## 🧮 置信度与新鲜度\n"
    md += f"- **综合置信分**: {confidence_details.get('score', '--')}/100\n"
    md += f"- **数据质量**: {confidence_details.get('data_quality', '--')}\n"
    md += f"- **技术一致性**: {confidence_details.get('technical_alignment', '--')}\n"
    md += f"- **估值支撑**: {confidence_details.get('valuation_support', '--')}\n"
    md += f"- **可执行性**: {confidence_details.get('actionability', '--')}\n"
    md += f"- **价格数据新鲜**: {freshness_flags.get('price_data_fresh', '--')}\n"
    md += f"- **基本面数据新鲜**: {freshness_flags.get('info_data_fresh', '--')}\n"
    md += f"- **新闻数据新鲜**: {freshness_flags.get('news_data_fresh', '--')}\n"
    md += f"- **持仓数据新鲜**: {freshness_flags.get('portfolio_data_fresh', '--')}\n"
    stale_inputs = freshness_flags.get("stale_inputs", [])
    if stale_inputs:
        md += "- **过期输入**:\n"
        for item in stale_inputs:
            md += f"  - {item}\n"
    md += "\n"

    if portfolio.get("has_position"):
        pnl_pct = portfolio.get("unrealized_pnl_pct")
        pnl_pct_display = f"{pnl_pct * 100:.2f}%" if isinstance(pnl_pct, (int, float)) else "--"
        md += "## 🧾 持仓者视角 (Position-Aware Advice)\n"
        md += f"- **持仓数量**: {portfolio.get('quantity', '--')}\n"
        md += f"- **持仓成本**: {portfolio.get('avg_cost', '--')}\n"
        md += f"- **当前价格**: {portfolio.get('current_price', '--')}\n"
        md += f"- **持仓市值**: {portfolio.get('market_value', '--')}\n"
        md += f"- **浮盈/浮亏**: {portfolio.get('unrealized_pnl', '--')} ({pnl_pct_display})\n"
        md += f"- **仓位状态**: {portfolio.get('weight_status', '--')}\n"
        md += f"- **持仓结论**: {position_advice.get('holding_view', '无')}\n"
        md += f"- **成本视角**: {position_advice.get('cost_basis_view', '无')}\n"
        md += f"- **对持仓者的动作建议**: {position_advice.get('action_for_holder', '无')}\n"
        md += f"- **核心风险**: {position_advice.get('risk_to_holder', '无')}\n"
        triggers = position_advice.get("next_action_trigger", [])
        if triggers:
            md += "- **动作触发条件**:\n"
            for item in triggers:
                md += f"  - {item}\n"
        md += "\n"

    if portfolio_summary or portfolio_risk or portfolio_fit:
        md += "## 🧩 组合适配度 (Portfolio Fit)\n"
        if portfolio_summary:
            md += f"- **持仓总数**: {portfolio_summary.get('total_positions', '--')}\n"
            md += f"- **已跟踪权重**: {portfolio_summary.get('tracked_weight', '--')}\n"
            md += f"- **集中度分数**: {portfolio_summary.get('concentration_score', '--')} ({portfolio_summary.get('concentration_bucket', '--')})\n"
            md += f"- **市场暴露**: {portfolio_summary.get('market_exposure', {})}\n"
        if portfolio_risk:
            md += f"- **集中度风险**: {portfolio_risk.get('concentration_risk', '--')}\n"
            md += f"- **市场暴露风险**: {portfolio_risk.get('market_exposure_risk', '--')}\n"
            md += f"- **风格漂移风险**: {portfolio_risk.get('style_drift_risk', '--')}\n"
            md += f"- **流动性风险**: {portfolio_risk.get('liquidity_risk', '--')}\n"
        if portfolio_fit:
            md += f"- **组合动作建议**: {portfolio_fit.get('action_in_portfolio', '--')}\n"
            md += f"- **配置影响**: {portfolio_fit.get('allocation_impact', '--')}\n"
            md += f"- **适配理由**: {portfolio_fit.get('rationale', '--')}\n"
        md += "\n"

    ts = dp.get("trend_status", {})
    pp = dp.get("price_position", {})
    va = dp.get("volume_analysis", {})
    cs = dp.get("chip_structure", {})
    md += "## 📊 关键财务与技术锚点 (Data Perspective)\n\n"
    md += "| 指标维度 | 数值 | 状态与描述 |\n|:---|:---|:---|\n"
    md += f"| **当前价格** | {pp.get('current_price', '--')} | 支撑: {pp.get('support_level', '--')} / 压力: {pp.get('resistance_level', '--')} |\n"
    md += f"| **均线排列** | {ts.get('ma_alignment', '--')} | 乖离率状态: {pp.get('bias_status', '--')} |\n"
    md += f"| **RSI (14)** | {ts.get('rsi_14', '--')} | {ts.get('rsi_status', '--')} |\n"
    md += f"| **MACD** | {ts.get('macd_signal', '--')} | 趋势得分: {ts.get('trend_score', '--')}/100 |\n"
    md += f"| **量能分析** | {va.get('volume_status', '--')} | 换手率: {va.get('turnover_rate', '--')} (量比: {va.get('volume_ratio', '--')}) |\n"
    md += f"| **筹码结构** | {cs.get('chip_health', '--')} | 获利比例: {cs.get('profit_ratio', '--')} |\n\n"

    md += "## 🔍 深度逻辑穿透 (Qualitative Analysis)\n\n"
    md += f"**趋势推演**: {qa.get('trend_analysis', '')}\n\n"
    md += f"**基本面/逻辑**: {qa.get('fundamental_analysis', '')}\n\n"
    md += f"**形态与技术**: {qa.get('pattern_analysis', '')}\n\n"
    md += f"**行业地位**: {qa.get('sector_position', '')}\n\n"
    md += f"**核心题材**: {qa.get('hot_topics', '')}\n\n"

    if earnings_snapshot or catalyst_map:
        md += "## 📅 Thesis & Catalyst Map\n\n"
        if earnings_snapshot:
            md += f"- **下次财报**: {earnings_snapshot.get('next_earnings_date', '--')}\n"
            md += f"- **营收增长**: {earnings_snapshot.get('revenue_growth', '--')}\n"
            md += f"- **Trailing PE**: {earnings_snapshot.get('trailing_pe', '--')}\n"
            md += f"- **Forward PE**: {earnings_snapshot.get('forward_pe', '--')}\n"
        if catalyst_map:
            if catalyst_map.get("upcoming"):
                md += "- **即将到来的催化**:\n"
                for item in catalyst_map["upcoming"]:
                    md += f"  - {item}\n"
            if catalyst_map.get("active"):
                md += "- **活跃催化**:\n"
                for item in catalyst_map["active"]:
                    md += f"  - {item}\n"
            if catalyst_map.get("broken"):
                md += "- **thesis 破坏信号**:\n"
                for item in catalyst_map["broken"]:
                    md += f"  - {item}\n"
        md += "\n"

    sp = bp.get("sniper_points", {})
    ps = bp.get("position_strategy", {})
    md += "## 🎯 战术调度指令 (Battle Plan)\n\n"
    md += f"- **理想买点**: {sp.get('ideal_buy', '--')}\n"
    md += f"- **次优买点**: {sp.get('secondary_buy', '--')}\n"
    md += f"- **止损位**: {sp.get('stop_loss', '--')}\n"
    md += f"- **目标位**: {sp.get('take_profit', '--')}\n"
    md += f"- **建议仓位**: {ps.get('suggested_position', '--')}\n"
    md += f"- **建仓策略**: {ps.get('entry_plan', '--')}\n"
    md += f"- **风控熔断**: {ps.get('risk_control', '--')}\n\n"
    md += "**行动检查单**\n"
    for item in bp.get("action_checklist", []):
        md += f"- {item}\n"

    md += "\n## 🔴 情报与风险 (Intelligence)\n\n"
    md += f"**市场情绪**: {intel.get('sentiment_summary', '')}\n\n"
    if intel.get("positive_catalysts"):
        md += "**催化剂**:\n"
        for item in intel["positive_catalysts"]:
            md += f"- {item}\n"
    if intel.get("risk_alerts"):
        md += "\n**核心风险警示 (SPOF)**:\n"
        for item in intel["risk_alerts"]:
            md += f"- ⚠️ {item}\n"

    if evidence_items:
        md += "\n## Evidence Mesh\n\n"
        for idx, item in enumerate(evidence_items, start=1):
            md += f"**证据 {idx}**\n"
            md += f"- Fact: {item.get('fact', '')}\n"
            md += f"- Connection: {item.get('connection', '')}\n"
            md += f"- Deduction: {item.get('deduction', '')}\n"
            md += f"- Source Type: {item.get('source_type', '')}\n"
            md += f"- Freshness: {item.get('freshness', '')}\n"
            md += f"- Confidence: {item.get('confidence', '')}\n"

    if watchlist_alerts:
        md += "\n## Watchlist Alerts\n"
        for item in watchlist_alerts:
            md += f"- {item}\n"

    if data.get("data_gaps"):
        md += "\n## ⚠️ 数据缺口\n"
        for gap in data["data_gaps"]:
            md += f"- {gap}\n"

    md += "\n## 🧠 Mentat 综合分析摘要\n\n"
    md += f"> {data.get('analysis_summary', '')}\n\n"
    md += "\n---\n<details><summary>点击查看原始 JSON 资产</summary>\n\n"
    md += f"```json\n{raw_json}\n```\n</details>\n"
    return md


def save_dashboard():
    parser = argparse.ArgumentParser(description="Save Stock Analysis Dashboard")
    parser.add_argument("--stock", required=True, help="Stock name or symbol")
    parser.add_argument("--content", help="JSON content string. If not provided, reads from stdin.")
    parser.add_argument("--file", help="Path to a JSON file containing the dashboard data.")
    args = parser.parse_args()

    content = args.content
    if args.file:
        content = Path(args.file).read_text(encoding="utf-8")
    elif not content:
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        content = sys.stdin.read()

    if not content:
        print("Error: No content provided.", file=sys.stderr)
        sys.exit(1)

    try:
        parsed = json.loads(content)
        formatted_content = json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON content: {e}. Ensure the agent output is pure JSON.", file=sys.stderr)
        sys.exit(1)

    errors = validate_dashboard(parsed)
    if errors:
        print("Error: dashboard gate blocked archive.", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        sys.exit(1)

    md_content = render_markdown(parsed, formatted_content)
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    safe_stock_name = args.stock.replace(" ", "_").replace("/", "_")
    filename = f"{safe_stock_name}_{date_str}.md"

    base_dir = Path(os.environ.get("PIA_DASHBOARD_DIR", str(Path.home() / ".gemini" / "MEMORY" / "raw" / "stocks")))
    base_dir.mkdir(parents=True, exist_ok=True)
    filepath = base_dir / filename
    filepath.write_text(md_content, encoding="utf-8")
    try:
        append_entry(parsed, archive_path=str(filepath))
    except Exception as exc:
        safe_print(f"Warning: advice journal append failed: {exc}")
    safe_print(f"Successfully saved and rendered Markdown dashboard to {filepath}")


if __name__ == "__main__":
    save_dashboard()
