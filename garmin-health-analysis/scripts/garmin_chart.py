#!/usr/bin/env python3
"""
@Input:  --chart (type), --days, --output (file path)
@Output: HTML File (Chart.js Visualization) or Browser Open
@Pos:    Presentation Layer. Consumes garmin_data.py logic.
"""

import json
import sys
import argparse
import webbrowser
from pathlib import Path
from datetime import datetime

# Import auth and data helpers
sys.path.insert(0, str(Path(__file__).parent))
from garmin_auth import get_client
from garmin_data import fetch_sleep, fetch_hrv, fetch_body_battery, fetch_heart_rate, fetch_activities, fetch_stress, fetch_summary
from garmin_intelligence import generate_chinese_insight


def generate_html(charts_data, title="Garmin 生物计量审计报告"):
    """Generate HTML with Chart.js visualizations."""
    
    colors = {
        "BLUE": "#0076D6",
        "GREEN": "#44AF69",
        "YELLOW": "#F4B942",
        "ORANGE": "#F58220",
        "RED": "#D8315B",
        "PURPLE": "#8E44AD",
        "DARK_BG": "#0F172A",
        "CARD_BG": "#1E293B",
        "TEXT_PRIMARY": "#F8FAFC",
        "TEXT_SECONDARY": "#94A3B8"
    }

    protocol_styles = {
        "GREEN": {"bg": colors["GREEN"], "icon": "🚀"},
        "RED": {"bg": colors["RED"], "icon": "🛑"},
        "YELLOW": {"bg": colors["YELLOW"], "icon": "⚠️"},
        "ALERT": {"bg": colors["PURPLE"], "icon": "🤒"}
    }
    
    move_type = charts_data.get("audit_data", {}).get("action_protocol", {}).get("type", "YELLOW")
    current_style = protocol_styles.get(move_type, protocol_styles["YELLOW"])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: {colors["DARK_BG"]};
            color: {colors["TEXT_PRIMARY"]};
            padding: 20px;
            line-height: 1.5;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header-title {{ text-align: center; margin-bottom: 30px; }}
        .header-title h1 {{ font-size: 2.5rem; font-weight: 800; }}
        .header-period {{ color: {colors["TEXT_SECONDARY"]}; font-weight: 600; letter-spacing: 1px; }}
        
        .dashboard-top {{ display: grid; grid-template-columns: 1fr 2fr; gap: 20px; margin-bottom: 30px; }}
        .protocol-card {{
            background: {current_style["bg"]};
            border-radius: 20px;
            padding: 25px;
            text-align: center;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }}
        .protocol-icon {{ font-size: 3.5rem; }}
        .protocol-move {{ font-size: 1.8rem; font-weight: 800; margin: 10px 0; }}
        
        .meta-card {{
            background: {colors["CARD_BG"]};
            border-radius: 20px;
            padding: 25px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }}
        .meta-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; }}
        .meta-label {{ color: {colors["TEXT_SECONDARY"]}; font-size: 0.8rem; font-weight: 600; }}
        .meta-value {{ font-size: 1.5rem; font-weight: 700; }}

        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }}
        .stat-card {{
            background: {colors["CARD_BG"]};
            border-radius: 15px;
            padding: 20px;
            border-left: 4px solid {colors["BLUE"]};
        }}
        .stat-label {{ color: {colors["TEXT_SECONDARY"]}; font-size: 0.8rem; margin-bottom: 5px; }}
        .stat-value {{ font-size: 1.8rem; font-weight: 800; }}

        .charts-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(500px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .chart-card {{ background: {colors["CARD_BG"]}; border-radius: 20px; padding: 25px; }}
        .chart-title {{ font-size: 1.1rem; font-weight: 700; margin-bottom: 15px; }}
        .chart-insight {{
            margin-top: 15px; padding: 12px; background: rgba(255,255,255,0.03);
            border-radius: 10px; font-size: 0.85rem; color: {colors["TEXT_SECONDARY"]};
            border-left: 3px solid {colors["BLUE"]};
        }}

        .audit-section {{ 
            background: #1E293B; 
            border-radius: 24px; 
            padding: 45px; 
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: 0 20px 50px rgba(0,0,0,0.4);
            position: relative;
            overflow: hidden;
        }}
        .audit-section::before {{
            content: 'EXPERT STRATEGIC AUDIT';
            position: absolute;
            top: 0;
            left: 0;
            background: #0076D6;
            color: white;
            padding: 5px 25px;
            font-size: 0.75rem;
            font-weight: 900;
            letter-spacing: 2px;
            border-bottom-right-radius: 15px;
        }}
        .audit-content {{ 
            font-size: 1.15rem; 
            line-height: 1.9; 
            margin-bottom: 40px; 
            color: #F1F5F9;
            white-space: pre-line;
        }}
        
        .quant-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 20px; }}
        .bar-bg {{ height: 8px; background: rgba(255,255,255,0.1); border-radius: 4px; overflow: hidden; margin-top: 5px; }}
        .bar-fill {{ height: 100%; transition: width 1s ease; }}
        
        .footer {{ text-align: center; padding: 30px; opacity: 0.5; font-size: 0.8rem; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header-title">
            <h1>BIO-METRIC AUDIT</h1>
            <div class="header-period" id="header-period">PERIOD: --</div>
        </div>

        <div class="dashboard-top">
            <div class="protocol-card">
                <div class="protocol-icon">{current_style["icon"]}</div>
                <div class="protocol-move" id="p-move">--</div>
                <div id="p-desc" style="font-size: 0.9rem; opacity: 0.9;">--</div>
            </div>
            <div class="meta-card">
                <div class="meta-grid">
                    <div><div class="meta-label">VO2 MAX</div><div class="meta-value" id="m-vo2">--</div></div>
                    <div><div class="meta-label">身体年龄</div><div class="meta-value" id="m-age">--</div></div>
                    <div><div class="meta-label">HRV 状态</div><div class="meta-value" id="m-hrv">--</div></div>
                    <div><div class="meta-label">RHR 趋势</div><div class="meta-value" id="m-rhr">--</div></div>
                </div>
            </div>
        </div>

        <div class="stats-grid" id="stats"></div>
        <div class="charts-grid" id="charts"></div>

        <div class="audit-section" id="audit-sec" style="display:none;">
            <div class="audit-content" id="audit-text"></div>
            <div class="quant-grid">
                <div>
                    <div style="display:flex; justify-content:space-between; font-size:0.85rem;"><span>输入 (修复)</span><span id="v-in">0</span></div>
                    <div class="bar-bg"><div class="bar-fill" id="b-in" style="background:{colors["GREEN"]}; width:0%"></div></div>
                </div>
                <div>
                    <div style="display:flex; justify-content:space-between; font-size:0.85rem;"><span>损耗 (应激)</span><span id="v-loss">0</span></div>
                    <div class="bar-bg"><div class="bar-fill" id="b-loss" style="background:{colors["RED"]}; width:0%"></div></div>
                </div>
                <div>
                    <div style="display:flex; justify-content:space-between; font-size:0.85rem;"><span>输出 (身心准备度)</span><span id="v-out">0</span></div>
                    <div class="bar-bg"><div class="bar-fill" id="b-out" style="background:{colors["BLUE"]}; width:0%"></div></div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:8px;">
                        <div class="bar-bg" style="height:4px;"><div class="bar-fill" id="b-cog" style="background:{colors["PURPLE"]}; width:0%"></div></div>
                        <div class="bar-bg" style="height:4px;"><div class="bar-fill" id="b-phy" style="background:{colors["ORANGE"]}; width:0%"></div></div>
                    </div>
                </div>
            </div>
        </div>

        <div class="footer">GARMIN AUDIT SYSTEM &copy; 2026</div>
    </div>

    <script>
        const chartsData = {json.dumps(charts_data, ensure_ascii=False)};
        Chart.defaults.color = '{colors["TEXT_SECONDARY"]}';

        if (chartsData.period) document.getElementById('header-period').textContent = 'PERIOD: ' + chartsData.period;
        if (chartsData.audit_data) {{
            const a = chartsData.audit_data;
            document.getElementById('p-move').textContent = a.action_protocol.move.split(' ')[0];
            document.getElementById('p-desc').textContent = a.action_protocol.description;
            document.getElementById('m-vo2').textContent = a.system_status.vo2_max;
            document.getElementById('m-age').textContent = a.system_status.fitness_age + (a.system_status.fitness_age !== '--' ? ' 岁' : '');
            document.getElementById('m-hrv').textContent = a.system_status.hrv.status;
            document.getElementById('m-rhr').textContent = a.system_status.rhr.status.split(' ')[0];
        }}

        if (chartsData.stats) {{
            const sCont = document.getElementById('stats');
            Object.entries(chartsData.stats).forEach(([l, v]) => {{
                const div = document.createElement('div');
                div.className = 'stat-card';
                div.innerHTML = `<div class="stat-label">${{l}}</div><div class="stat-value">${{v}}</div>`;
                sCont.appendChild(div);
            }});
        }}

        if (chartsData.charts) {{
            const cCont = document.getElementById('charts');
            chartsData.charts.forEach(c => {{
                const div = document.createElement('div');
                div.className = 'chart-card';
                div.innerHTML = `<div class="chart-title">${{c.title}}</div><canvas></canvas>${{c.insight ? `<div class="chart-insight"><strong>💡 审计:</strong> ${{c.insight}}</div>` : ''}}`;
                cCont.appendChild(div);
                new Chart(div.querySelector('canvas'), c.chart);
            }});
        }}

        if (chartsData.overall_insight) {{
            document.getElementById('audit-sec').style.display = 'block';
            document.getElementById('audit-text').textContent = chartsData.overall_insight;
            if (chartsData.quant_scores) {{
                const q = chartsData.quant_scores;
                document.getElementById('v-in').textContent = q.input;
                document.getElementById('b-in').style.width = q.input + '%';
                document.getElementById('v-loss').textContent = q.loss;
                document.getElementById('b-loss').style.width = q.loss + '%';
                document.getElementById('v-out').textContent = q.output;
                document.getElementById('b-out').style.width = q.output + '%';
                document.getElementById('b-cog').style.width = q.cognitive + '%';
                document.getElementById('b-phy').style.width = q.physical + '%';
            }}
        }}
    </script>
</body>
</html>"""
    return html


def create_sleep_chart(sleep_data, insight=""):
    dates = [s["date"] for s in sleep_data if s.get("sleep_time_seconds")]
    hours = [s["sleep_time_seconds"] / 3600 for s in sleep_data if s.get("sleep_time_seconds")]
    scores = [s.get("sleep_score", 0) for s in sleep_data if s.get("sleep_score")]
    avg_h = sum(hours)/len(hours) if hours else 0
    avg_s = sum(scores)/len(scores) if scores else 0
    return {
        "stats": {"平均睡眠": f"{avg_h:.1f}h", "平均分": f"{avg_s:.0f}"},
        "chart": {
            "title": "睡眠修复分析", "insight": insight,
            "chart": {
                "type": "bar",
                "data": {
                    "labels": dates,
                    "datasets": [
                        {"label": "时长", "data": hours, "backgroundColor": "#0076D6", "yAxisID": "y"},
                        {"label": "得分", "data": scores, "type": "line", "borderColor": "#F4B942", "yAxisID": "y1"}
                    ]
                },
                "options": { "scales": { "y": { "position": "left" }, "y1": { "position": "right", "max": 100 } } }
            }
        }
    }

def create_body_battery_chart(bb_data, insight=""):
    dates = [b["date"] for b in bb_data if b.get("highest")]
    highest = [b.get("highest", 0) for b in bb_data if b.get("highest")]
    return {
        "stats": {"最高电量": f"{max(highest) if highest else 0}"},
        "chart": {
            "title": "身体电量 (Body Battery)", "insight": insight,
            "chart": {
                "type": "bar",
                "data": { "labels": dates, "datasets": [{"label": "峰值", "data": highest, "backgroundColor": "#44AF69"}] },
                "options": { "scales": { "y": { "max": 100 } } }
            }
        }
    }

def create_hrv_chart(hrv_data, hr_data, insight=""):
    dates = [h["date"] for h in hrv_data if h.get("last_night_avg")]
    hrv = [h.get("last_night_avg", 0) for h in hrv_data if h.get("last_night_avg")]
    hr_map = {h["date"]: h.get("resting_hr") for h in hr_data if h.get("resting_hr")}
    rhr = [hr_map.get(d, 0) for d in dates]
    avg_hrv = sum(hrv)/len(hrv) if hrv else 0
    avg_rhr = sum(rhr)/len(rhr) if rhr else 0
    return {
        "stats": {"平均HRV": f"{avg_hrv:.0f}ms", "平均RHR": f"{avg_rhr:.0f}bpm"},
        "chart": {
            "title": "HRV & 静息心率趋势", "insight": insight,
            "chart": {
                "type": "line",
                "data": {
                    "labels": dates,
                    "datasets": [
                        {"label": "HRV", "data": hrv, "borderColor": "#8E44AD", "tension": 0.4},
                        {"label": "RHR", "data": rhr, "borderColor": "#D8315B", "tension": 0.4}
                    ]
                }
            }
        }
    }

def create_activities_chart(activities_data, insight=""):
    types = {}
    for a in activities_data:
        t = a.get("activity_type", "Unknown")
        types[t] = types.get(t, 0) + 1
    return {
        "stats": {"总运动": f"{len(activities_data)}"},
        "chart": {
            "title": "活动分布", "insight": insight,
            "chart": {
                "type": "bar",
                "data": { "labels": list(types.keys()), "datasets": [{"label": "次数", "data": list(types.values()), "backgroundColor": "#F58220"}] }
            }
        }
    }

def create_stress_chart(stress_data, insight=""):
    dates = [s["date"] for s in stress_data if s.get("avg_stress")]
    stress = [s.get("avg_stress", 0) for s in stress_data if s.get("avg_stress")]
    avg_s = sum(stress)/len(stress) if stress else 0
    return {
        "stats": {"平均压力": f"{avg_s:.0f}"},
        "chart": {
            "title": "全天压力趋势", "insight": insight,
            "chart": {
                "type": "line",
                "data": { "labels": dates, "datasets": [{"label": "压力值", "data": stress, "borderColor": "#F58220", "fill": True, "backgroundColor": "rgba(245,130,32,0.1)"}] },
                "options": { "scales": { "y": { "max": 100 } } }
            }
        }
    }

def create_load_chart(ts_data, insight=""):
    if not ts_data or ts_data.get("status") == "无数据": return None
    acute = ts_data.get("acute_load", 0) or 0
    return {
        "stats": {"急性负荷": f"{acute}", "状态": ts_data.get("status")},
        "chart": {
            "title": "训练状态", "insight": insight,
            "chart": {
                "type": "doughnut",
                "data": { "labels": ["负荷", "剩余"], "datasets": [{"data": [acute, max(0, 1000-acute)], "backgroundColor": ["#0076D6", "rgba(255,255,255,0.05)"]}] },
                "options": { "circumference": 180, "rotation": 270 }
            }
        }
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("chart", choices=["sleep", "body_battery", "hrv", "activities", "stress", "load", "dashboard"])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--output")
    args = parser.parse_args()
    client = get_client()
    if not client: sys.exit(1)
    
    summary_data = fetch_summary(client, args.days)
    charts_data = {"stats": {}, "charts": [], "top_insights": [], "overall_insight": "", "audit_data": {}, "quant_scores": {}, "period": ""}
    
    if summary_data:
        res = generate_chinese_insight(summary_data)
        charts_data.update({"top_insights": res["top_insights"], "overall_insight": res["overall_insight"], "audit_data": res["audit_data"], "period": res["period"], "quant_scores": res["quant_scores"]})
        ci = res["chart_insights"]
        
        if args.chart in ["sleep", "dashboard"] and summary_data.get("sleep"):
            r = create_sleep_chart(summary_data["sleep"], ci.get("sleep"))
            charts_data["stats"].update(r["stats"]); charts_data["charts"].append(r["chart"])
        if args.chart in ["body_battery", "dashboard"] and summary_data.get("body_battery"):
            r = create_body_battery_chart(summary_data["body_battery"], ci.get("body_battery"))
            charts_data["stats"].update(r["stats"]); charts_data["charts"].append(r["chart"])
        if args.chart in ["hrv", "dashboard"] and summary_data.get("hrv"):
            r = create_hrv_chart(summary_data["hrv"], summary_data["heart_rate"], ci.get("hrv"))
            charts_data["stats"].update(r["stats"]); charts_data["charts"].append(r["chart"])
        if args.chart in ["stress", "dashboard"] and summary_data.get("stress"):
            r = create_stress_chart(summary_data["stress"], ci.get("stress", ""))
            charts_data["stats"].update(r["stats"]); charts_data["charts"].append(r["chart"])
        if args.chart in ["load", "dashboard"] and summary_data.get("training_status"):
            r = create_load_chart(summary_data["training_status"], ci.get("activities", "")) # Use activities/load context
            if r: charts_data["stats"].update(r["stats"]); charts_data["charts"].append(r["chart"])
        if args.chart in ["activities", "dashboard"] and summary_data.get("activities"):
            r = create_activities_chart(summary_data["activities"], ci.get("activities"))
            charts_data["stats"].update(r["stats"]); charts_data["charts"].append(r["chart"])

    html = generate_html(charts_data)
    if args.output: 
        out_path = Path(args.output)
        out_path.write_text(html, encoding='utf-8')
    else:
        out_dir = Path(r"C:\Users\shich\.gemini\memory\garmin")
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"health_report_{args.chart}_{args.days}days_{timestamp}.html"
        out_path.write_text(html, encoding='utf-8')
        webbrowser.open(f"file://{out_path.resolve()}")

if __name__ == "__main__": main()
