import os
import sys
import json
import argparse
from datetime import datetime

def render_markdown(data, raw_json):
    """Render the JSON data into a beautifully formatted Markdown string."""
    try:
        stock_name = data.get('stock_name', 'Unknown')
        stock_code = data.get('stock_code', 'Unknown')
        market_type = data.get('market_type', '')
        trend = data.get('trend_prediction', '')
        advice = data.get('operation_advice', '')
        confidence = data.get('confidence_level', '')
        tags = data.get('tags', [])
        
        db = data.get('dashboard', {})
        cc = db.get('core_conclusion', {})
        qa = db.get('qualitative_analysis', {})
        dp = db.get('data_perspective', {})
        intel = db.get('intelligence', {})
        bp = db.get('battle_plan', {})
        
        md = f"---\n"
        md += f"title: {stock_name} ({stock_code}) 深度研究报告\n"
        md += f"date: {datetime.now().strftime('%Y-%m-%d')}\n"
        md += f"status: archived\n"
        md += f"author: stock_analyzer\n"
        if tags:
            md += f"tags: [{', '.join(tags)}]\n"
        md += f"---\n\n"
        
        md += f"# 决策仪表盘: {stock_name} ({stock_code} - {market_type})\n\n"
        md += f"> 本报告由 `stock_analyzer` 基于双引擎（Yahoo Finance 量化数据与网络检索）自动生成。置信度：**{confidence}**\n\n"
        
        md += f"## 🟢 核心判词 (Executive Summary)\n"
        md += f"**{cc.get('one_sentence', '无')}**\n\n"
        md += f"- **信号状态**: {cc.get('signal_type', '无')}\n"
        md += f"- **操作建议**: {advice} (趋势预期: {trend})\n"
        md += f"- **时间窗口**: {cc.get('time_sensitivity', '无')}\n"
        
        pos_advice = cc.get('position_advice', {})
        md += f"- **空仓建议**: {pos_advice.get('no_position', '无')}\n"
        md += f"- **持仓建议**: {pos_advice.get('has_position', '无')}\n\n"
        
        md += f"## 📊 关键财务与技术锚点 (Data Perspective)\n\n"
        
        ts = dp.get('trend_status', {})
        pp = dp.get('price_position', {})
        va = dp.get('volume_analysis', {})
        cs = dp.get('chip_structure', {})
        md += f"| 指标维度 | 数值 | 状态与描述 |\\n|:---|:---|:---|\\n"
        md += f"| **当前价格** | {pp.get('current_price', '--')} | 支撑: {pp.get('support_level', '--')} / 压力: {pp.get('resistance_level', '--')} |\n"
        md += f"| **均线排列** | {ts.get('ma_alignment', '--')} | 乖离率状态: {pp.get('bias_status', '--')} |\n"
        md += f"| **RSI (14)** | {ts.get('rsi_14', '--')} | {ts.get('rsi_status', '--')} |\n"
        md += f"| **MACD** | {ts.get('macd_signal', '--')} | 趋势得分: {ts.get('trend_score', '--')}/100 |\n"
        md += f"| **量能分析** | {va.get('volume_status', '--')} | 换手率: {va.get('turnover_rate', '--')} (量比: {va.get('volume_ratio', '--')}) |\n"
        md += f"| **筹码结构** | {cs.get('chip_health', '--')} | 获利比例: {cs.get('profit_ratio', '--')} |\n"
        
        md += f"## 🔍 深度逻辑穿透 (Qualitative Analysis)\n\n"
        md += f"**趋势推演**: {qa.get('trend_analysis', '')}\n\n"
        md += f"**基本面/逻辑**: {qa.get('fundamental_analysis', '')}\n\n"
        md += f"**形态与技术**: {qa.get('pattern_analysis', '')}\n\n"
        md += f"**行业地位**: {qa.get('sector_position', '')}\n\n"
        md += f"**核心题材**: {qa.get('hot_topics', '')}\n\n"
        
        md += f"## 🎯 战术调度指令 (Battle Plan)\n\n"
        sp = bp.get('sniper_points', {})
        ps = bp.get('position_strategy', {})
        
        md += f"**1. 狙击点位 (Sniper Points)**\n"
        md += f"- 理想买点: **{sp.get('ideal_buy', '--')}**\n"
        md += f"- 次优买点: **{sp.get('secondary_buy', '--')}**\n"
        md += f"- 止损位: **{sp.get('stop_loss', '--')}**\n"
        md += f"- 目标位: **{sp.get('take_profit', '--')}**\n\n"
        
        md += f"**2. 仓位与风控 (Position & Risk)**\n"
        md += f"- 建议仓位: {ps.get('suggested_position', '--')}\n"
        md += f"- 建仓策略: {ps.get('entry_plan', '--')}\n"
        md += f"- 风控熔断: {ps.get('risk_control', '--')}\n\n"
        
        md += f"**3. 行动检查单 (Checklist)**\n"
        for item in bp.get('action_checklist', []):
            md += f"- {item}\n"
            
        md += f"\n## 🔴 情报与风险 (Intelligence)\n\n"
        md += f"**市场情绪**: {intel.get('sentiment_summary', '')}\n\n"
        if intel.get('positive_catalysts'):
            md += f"**催化剂**:\n"
            for cat in intel.get('positive_catalysts', []):
                md += f"- {cat}\n"
        
        if intel.get('risk_alerts'):
            md += f"\n**核心风险警示 (SPOF)**:\n"
            for alert in intel.get('risk_alerts', []):
                md += f"- ⚠️ {alert}\n"
        
        md += f"\n## 🧠 Mentat 综合分析摘要\n\n"
        md += f"> {data.get('analysis_summary', '')}\n\n"
        
        md += f"\n---\n<details><summary>点击查看原始 JSON 资产</summary>\n\n```json\n{raw_json}\n```\n</details>\n"
        
        return md
    except Exception as e:
        print(f"Markdown rendering error: {e}")
        return None

def save_dashboard():
    parser = argparse.ArgumentParser(description="Save Stock Analysis Dashboard")
    parser.add_argument("--stock", required=True, help="Stock name or symbol")
    parser.add_argument("--content", help="JSON content string. If not provided, reads from stdin.")
    parser.add_argument("--file", help="Path to a JSON file containing the dashboard data.")
    
    args = parser.parse_args()
    
    content = args.content
    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            content = f.read()
    elif not content:
        if hasattr(sys.stdin, 'reconfigure'):
            sys.stdin.reconfigure(encoding='utf-8')
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
        
    # Validation: Anti-Dehydration Lock
    if "dashboard" not in parsed or "battle_plan" not in parsed.get("dashboard", {}):
        print("Error: JSON is severely dehydrated. Missing 'dashboard.battle_plan'. Agent must generate full schema.", file=sys.stderr)
        sys.exit(1)
        
    # Render Markdown
    md_content = render_markdown(parsed, formatted_content)
    if not md_content:
        # Fallback to pure JSON embedded in MD if rendering fails
        md_content = f"# {args.stock}\n\n```json\n{formatted_content}\n```"
        
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    safe_stock_name = args.stock.replace(" ", "_").replace("/", "_")
    filename = f"{safe_stock_name}_{date_str}.md"
    
    base_dir = os.path.join(os.path.expanduser("~"), ".gemini", "MEMORY\raw", "stocks")
    os.makedirs(base_dir, exist_ok=True)
    filepath = os.path.join(base_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    print(f"Successfully saved and rendered Markdown dashboard to {filepath}")

if __name__ == "__main__":
    save_dashboard()
