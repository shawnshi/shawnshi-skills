#!/usr/bin/env python3
"""
@Input:  --chart (dashboard, overlay), --days, --period, --output (file path)
@Output: HTML File (Chart.js Visualization) or Browser Open
@Pos:    Presentation Layer. Consumes garmin_data.py logic.
@Aesthetic: Mentat White Platinum Edition (Light Mode, High Contrast, High Density)
"""

import json
import sys
import argparse
import webbrowser
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from garmin_auth import get_client
from garmin_data import fetch_summary
from garmin_intelligence import generate_chinese_insight, parse_period

def generate_tactical_html(charts_data, title="GARMIN STRATEGIC AUDIT"):
    """Generate high-density light-mode HTML dashboard with strict f-string escaping."""
    
    colors = {
        "BG": "#F5F7FA",
        "PANEL_BG": "#FFFFFF",
        "BORDER": "#E1E8ED",
        "TEXT_MAIN": "#2C3E50",
        "TEXT_MUTED": "#7F8C8D",
        "GREEN": "#27AE60",
        "RED": "#E74C3C",
        "YELLOW": "#F1C40F",
        "BLUE": "#3498DB",
        "PURPLE": "#9B59B6"
    }

    audit = charts_data.get("audit_data", {})
    move_type = audit.get("action_protocol", {}).get("type", "YELLOW")
    
    status_color = colors["YELLOW"]
    if move_type == "GREEN": status_color = colors["GREEN"]
    elif move_type == "RED": status_color = colors["RED"]
    elif move_type == "ALERT": status_color = colors["PURPLE"]

    # Correct data path and robust extraction for DISSIPATION KPI
    ov = charts_data.get("overlay_data", {})
    wd_list = ov.get("weighted_dissipation", [])
    
    # Get the latest non-zero value or just the latest if all are zero
    weighted_val = "--"
    if wd_list:
        # Try to find the latest non-zero value (handle partial sync days)
        latest_valid = [v for v in wd_list if v > 0]
        weighted_val = latest_valid[-1] if latest_valid else wd_list[-1]
        
    json_data = json.dumps(charts_data, ensure_ascii=False)
    json_colors = json.dumps(colors)

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
            font-family: "JetBrains Mono", "Courier New", Courier, monospace;
            background-color: {colors["BG"]};
            color: {colors["TEXT_MAIN"]};
            padding: 15px;
            font-size: 12px;
            line-height: 1.4;
        }}
        .grid-container {{
            display: grid;
            grid-template-columns: repeat(12, 1fr);
            gap: 15px;
            max-width: 1600px;
            margin: 0 auto;
        }}
        .panel {{
            background: {colors["PANEL_BG"]};
            border: 1px solid {colors["BORDER"]};
            border-radius: 4px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }}
        .panel-title {{
            font-size: 11px;
            font-weight: 800;
            color: {colors["TEXT_MUTED"]};
            text-transform: uppercase;
            letter-spacing: 1.5px;
            margin-bottom: 15px;
            border-bottom: 2px solid {colors["BG"]};
            padding-bottom: 8px;
        }}
        
        /* KPI Row */
        .kpi-row {{ grid-column: span 12; display: flex; gap: 15px; flex-wrap: wrap; }}
        .kpi-box {{
            flex: 1;
            min-width: 180px;
            background: {colors["PANEL_BG"]};
            border: 1px solid {colors["BORDER"]};
            border-radius: 4px;
            padding: 15px;
            border-top: 4px solid {colors["BORDER"]};
        }}
        .kpi-val {{ font-size: 28px; font-weight: 900; margin-top: 5px; color: {colors["TEXT_MAIN"]}; }}
        .kpi-sub {{ font-size: 11px; font-weight: bold; color: {colors["TEXT_MUTED"]}; }}
        
        .kpi-box.status {{ border-top-color: {status_color}; }}
        .kpi-box.status .kpi-val {{ color: {status_color}; }}
        
        /* Charts */
        .main-chart {{ grid-column: span 12; height: 380px; }}
        .sub-chart {{ grid-column: span 6; height: 320px; }}
        
        /* Audit Log */
        .audit-log {{ grid-column: span 12; }}
        
        /* Heatmap */
        .heatmap-container {{ grid-column: span 12; display: flex; flex-wrap: wrap; gap: 4px; padding-top: 10px; }}
        .heat-box {{ width: 14px; height: 14px; border-radius: 2px; background: {colors["BORDER"]}; }}
        
        @media (max-width: 1000px) {{
            .sub-chart {{ grid-column: span 12; }}
        }}
    </style>
</head>
<body>
    <div class="grid-container" id="app">
        <!-- Populated by JS -->
    </div>

    <script>
        const data = {json_data};
        const colors = {json_colors};
        
        Chart.defaults.color = colors.TEXT_MUTED;
        Chart.defaults.font.family = '"JetBrains Mono", monospace';
        Chart.defaults.borderColor = colors.BORDER;
        
        function renderDashboard() {{
            const app = document.getElementById('app');
            const a = data.audit_data;
            const q = data.quant_scores;
            
            // KPI ROW
            let html = `<div class="kpi-row">
                <div class="kpi-box status">
                    <div class="panel-title">SYSTEM STATUS</div>
                    <div class="kpi-val">${{a.action_protocol.move.split(' ')[0]}}</div>
                    <div class="kpi-sub">READINESS: ${{q.output}}/100</div>
                </div>
                <div class="kpi-box">
                    <div class="panel-title">FITNESS AGE</div>
                    <div class="kpi-val">${{a.system_status.fitness_age}} <span style="font-size:14px">yrs</span></div>
                    <div class="kpi-sub">BODY VITALITY</div>
                </div>
                <div class="kpi-box">
                    <div class="panel-title">BMI INDEX</div>
                    <div class="kpi-val">${{a.system_status.bmi}}</div>
                    <div class="kpi-sub">BODY COMPOSITION</div>
                </div>
                <div class="kpi-box">
                    <div class="panel-title">RHR BASELINE</div>
                    <div class="kpi-val">${{a.system_status.rhr.current}} <span style="font-size:14px">bpm</span></div>
                    <div class="kpi-sub">BASE: ${{a.system_status.rhr.baseline}}</div>
                </div>
                <div class="kpi-box">
                    <div class="panel-title">DISSIPATION</div>
                    <div class="kpi-val">{weighted_val} <span style="font-size:14px">h</span></div>
                    <div class="kpi-sub">WEIGHTED FRICTION</div>
                </div>
                <div class="kpi-box">
                    <div class="panel-title">SLEEP DEBT</div>
                    <div class="kpi-val">${{a.recovery_loop.sleep_architecture.sleep_debt_h}} <span style="font-size:14px">h</span></div>
                    <div class="kpi-sub">DEEP: ${{a.recovery_loop.sleep_architecture.deep_pct}}%</div>
                </div>
            </div>`;
            
            // CHARTS GRID
            html += `<div class="panel main-chart">
                <div class="panel-title">STRATEGIC OVERLAY (STRESS × ENERGY × RHR)</div>
                <canvas id="overlayChart"></canvas>
            </div>`;

            html += `<div class="panel sub-chart">
                <div class="panel-title">SLEEP PERFORMANCE (HOURS × SCORE)</div>
                <canvas id="sleepChart"></canvas>
            </div>`;
            
            html += `<div class="panel sub-chart">
                <div class="panel-title">ACTIVITY LOAD (CALORIES × DISTANCE)</div>
                <canvas id="activityChart"></canvas>
            </div>`;

            html += `<div class="panel main-chart">
                <div class="panel-title">HEART RATE ENVELOPE (RESTING vs MAX)</div>
                <canvas id="hrChart"></canvas>
            </div>`;

            if (data.heatmap && data.heatmap.length > 0) {{
                html += `<div class="panel" style="grid-column: span 12;">
                    <div class="panel-title">SYSTEMIC CONSISTENCY (SLEEP SCORE HEATMAP)</div>
                    <div class="heatmap-container">
                        ${{data.heatmap.map(d => `<div class="heat-box" title="${{d.date}}: ${{d.score}}" style="background: ${{getHeatColor(d.score)}}"></div>`).join('')}}
                    </div>
                </div>`;
            }}

            html += `<div class="panel audit-log">
                <div class="panel-title">MENTAT STRATEGIC AUDIT LOG</div>
                <div style="white-space: pre-wrap; font-size: 14px; color: ${{colors.TEXT_MAIN}};">${{data.overall_insight}}</div>
            </div>`;
            
            app.innerHTML = html;
            renderCharts();
        }}
        
        function getHeatColor(score) {{
            if (!score) return colors.BORDER;
            if (score >= 80) return colors.GREEN;
            if (score >= 60) return '#82E0AA';
            if (score >= 40) return colors.YELLOW;
            return colors.RED;
        }}

        function renderCharts() {{
            if (!data.overlay_data) return;
            const od = data.overlay_data;
            
            // 1. STRATEGIC OVERLAY
            new Chart(document.getElementById('overlayChart'), {{
                data: {{
                    labels: od.dates,
                    datasets: [
                        {{
                            type: 'bar',
                            label: 'Dissipation (h)',
                            data: od.stress_h,
                            backgroundColor: 'rgba(231, 76, 60, 0.6)',
                            borderColor: colors.RED,
                            borderWidth: 1,
                            yAxisID: 'y',
                            minBarLength: 5
                        }},
                        {{
                            type: 'line',
                            label: 'Body Battery Peak',
                            data: od.bb_peak,
                            borderColor: colors.BLUE,
                            backgroundColor: colors.BLUE,
                            pointRadius: 4,
                            borderWidth: 3,
                            tension: 0.2,
                            yAxisID: 'y1'
                        }},
                        {{
                            type: 'line',
                            label: 'RHR',
                            data: od.rhr,
                            borderColor: colors.YELLOW,
                            borderWidth: 2,
                            borderDash: [5, 5],
                            yAxisID: 'y2'
                        }},
                        {{
                            type: 'line',
                            label: 'READINESS',
                            data: od.readiness,
                            borderColor: colors.GREEN,
                            borderWidth: 3,
                            pointStyle: 'star',
                            pointRadius: 5,
                            tension: 0.3,
                            yAxisID: 'y1'
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {{ mode: 'index', intersect: false }},
                    scales: {{
                        y: {{ type: 'linear', position: 'left', min: 0, suggestedMax: 5, title: {{ display: true, text: 'Hours' }} }},
                        y1: {{ type: 'linear', position: 'right', min: 0, max: 100, title: {{ display: true, text: 'Energy / Readiness' }}, grid: {{ drawOnChartArea: false }} }},
                        y2: {{ type: 'linear', position: 'right', title: {{ display: true, text: 'bpm' }}, grid: {{ drawOnChartArea: false }} }}
                    }}
                }}
            }});

            // 2. SLEEP PERFORMANCE
            new Chart(document.getElementById('sleepChart'), {{
                data: {{
                    labels: od.dates,
                    datasets: [
                        {{
                            type: 'bar',
                            label: 'Sleep Hours',
                            data: od.sleep_h,
                            backgroundColor: 'rgba(52, 152, 219, 0.5)',
                            yAxisID: 'y'
                        }},
                        {{
                            type: 'line',
                            label: 'Sleep Score',
                            data: od.sleep_score,
                            borderColor: colors.GREEN,
                            borderWidth: 3,
                            yAxisID: 'y1'
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {{
                        y: {{ type: 'linear', position: 'left', title: {{ display: true, text: 'Hours' }} }},
                        y1: {{ type: 'linear', position: 'right', min: 0, max: 100, title: {{ display: true, text: 'Score' }}, grid: {{ drawOnChartArea: false }} }}
                    }}
                }}
            }});

            // 3. ACTIVITY LOAD
            new Chart(document.getElementById('activityChart'), {{
                data: {{
                    labels: od.dates,
                    datasets: [
                        {{
                            type: 'bar',
                            label: 'Calories',
                            data: od.calories,
                            backgroundColor: 'rgba(155, 89, 182, 0.5)',
                            yAxisID: 'y'
                        }},
                        {{
                            type: 'line',
                            label: 'Distance (km)',
                            data: od.distance,
                            borderColor: colors.YELLOW,
                            borderWidth: 3,
                            yAxisID: 'y1'
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {{
                        y: {{ type: 'linear', position: 'left', title: {{ display: true, text: 'Calories' }} }},
                        y1: {{ type: 'linear', position: 'right', title: {{ display: true, text: 'km' }}, grid: {{ drawOnChartArea: false }} }}
                    }}
                }}
            }});

            // 4. HR ENVELOPE + HRV
            new Chart(document.getElementById('hrChart'), {{
                data: {{
                    labels: od.dates,
                    datasets: [
                        {{
                            type: 'line',
                            label: 'Max HR',
                            data: od.max_hr,
                            borderColor: colors.RED,
                            backgroundColor: 'rgba(231, 76, 96, 0.1)',
                            fill: true,
                            tension: 0.3,
                            yAxisID: 'y'
                        }},
                        {{
                            type: 'line',
                            label: 'Resting HR',
                            data: od.rhr,
                            borderColor: colors.YELLOW,
                            backgroundColor: 'rgba(241, 196, 15, 0.1)',
                            fill: true,
                            tension: 0.3,
                            yAxisID: 'y'
                        }},
                        {{
                            type: 'line',
                            label: 'HRV (ms)',
                            data: od.hrv,
                            borderColor: colors.BLUE,
                            borderWidth: 2,
                            pointStyle: 'rectRot',
                            pointRadius: 5,
                            tension: 0.1,
                            yAxisID: 'y1'
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {{
                        y: {{ type: 'linear', position: 'left', title: {{ display: true, text: 'HR (bpm)' }} }},
                        y1: {{ type: 'linear', position: 'right', title: {{ display: true, text: 'HRV (ms)' }}, grid: {{ drawOnChartArea: false }} }}
                    }}
                }}
            }});
        }}
        
        renderDashboard();
    </script>
</body>
</html>"""
    return html

def build_overlay_data(summary_data):
    """Extract and align arrays for the multi-dimensional chart."""
    dates = [s["date"] for s in summary_data.get("sleep", []) if s.get("date")]
    if not dates: return None
    
    stress_map = {s["date"]: ((s.get("high_stress_duration") or 0) + (s.get("medium_stress_duration") or 0))/3600 for s in summary_data.get("stress", [])}
    bb_map = {b["date"]: b.get("highest") or 0 for b in summary_data.get("body_battery", [])}
    rhr_map = {h["date"]: h.get("resting_hr") or 0 for h in summary_data.get("heart_rate", [])}
    max_hr_map = {h["date"]: h.get("max_hr") or 0 for h in summary_data.get("heart_rate", [])}
    
    sleep_h_map = {s["date"]: (s.get("sleep_time_seconds") or 0)/3600 for s in summary_data.get("sleep", [])}
    sleep_score_map = {s["date"]: s.get("sleep_score") or 0 for s in summary_data.get("sleep", [])}
    hrv_map = {h["date"]: h.get("last_night_avg") or 0 for h in summary_data.get("hrv", [])}
    hrv_status_map = {h["date"]: h.get("status") for h in summary_data.get("hrv", [])}
    
    act_cal_map = {}
    act_dist_map = {}
    for act in summary_data.get("activities", []):
        d = act["date"]
        act_cal_map[d] = act_cal_map.get(d, 0) + (act.get("calories") or 0)
        act_dist_map[d] = act_dist_map.get(d, 0) + (act.get("distance_meters") or 0) / 1000
    
    # Calculate daily Readiness proxy & Precise Dissipation
    readiness_list = []
    weighted_dissipation_map = {}
    
    for d in dates:
        # Raw durations in seconds
        stress_entry = next((s for s in summary_data.get("stress", []) if s["date"] == d), {})
        high_sec = stress_entry.get("high_stress_duration") or 0
        med_sec = stress_entry.get("medium_stress_duration") or 0
        
        # Weighted Dissipation (Mentat Intelligence Standard)
        weighted_h = (high_sec + (med_sec * 0.5)) / 3600
        weighted_dissipation_map[d] = round(weighted_h, 1)
        
        ss = sleep_score_map.get(d, 0)
        bb = bb_map.get(d, 0)
        hrv_stat = hrv_status_map.get(d, "BALANCED")
        
        # Base Score (Weighted Sleep + Battery)
        score = (ss * 0.4) + (bb * 0.4)
        # HRV Bonus
        if hrv_stat == "BALANCED": score += 20
        elif hrv_stat == "UNBALANCED": score += 5
        # Weighted Dissipation Penalty
        score -= (weighted_h * 4)
        
        readiness_list.append(round(max(0, min(100, score)), 1))

    return {
        "dates": dates,
        "stress_h": [stress_map.get(d, 0) for d in dates], # Visual bars (total)
        "bb_peak": [bb_map.get(d, 0) for d in dates],
        "rhr": [rhr_map.get(d, 0) for d in dates],
        "max_hr": [max_hr_map.get(d, 0) for d in dates],
        "sleep_h": [sleep_h_map.get(d, 0) for d in dates],
        "sleep_score": [sleep_score_map.get(d, 0) for d in dates],
        "hrv": [hrv_map.get(d, 0) for d in dates],
        "calories": [act_cal_map.get(d, 0) for d in dates],
        "distance": [act_dist_map.get(d, 0) for d in dates],
        "readiness": readiness_list,
        "weighted_dissipation": [weighted_dissipation_map.get(d, 0) for d in dates]
    }

def build_heatmap_data(summary_data):
    sleep = summary_data.get("sleep", [])
    return [{"date": s["date"], "score": s.get("sleep_score", 0)} for s in sleep]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("chart", choices=["dashboard", "overlay"])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--period", type=str, help="Period (e.g. 90d, YTD)")
    parser.add_argument("--output")
    args = parser.parse_args()
    
    days = parse_period(args.period, args.days)
    client = get_client()
    if not client: sys.exit(1)
    
    summary_data = fetch_summary(client, days)
    charts_data = {}
    
    if summary_data:
        res = generate_chinese_insight(summary_data)
        charts_data.update({
            "overall_insight": res["overall_insight"], 
            "audit_data": res["audit_data"], 
            "period": res["period"], 
            "quant_scores": res["quant_scores"]
        })
        charts_data["overlay_data"] = build_overlay_data(summary_data)
        if days >= 14:
            charts_data["heatmap"] = build_heatmap_data(summary_data)

    html = generate_tactical_html(charts_data)
    
    if args.output: 
        out_path = Path(args.output)
        out_path.write_text(html, encoding='utf-8')
    else:
        out_dir = Path(r"C:\Users\shich\.gemini\memory\garmin")
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"tactical_board_light_{days}days_{timestamp}.html"
        out_path.write_text(html, encoding='utf-8')
        webbrowser.open(f"file://{out_path.resolve()}")

if __name__ == "__main__": main()
