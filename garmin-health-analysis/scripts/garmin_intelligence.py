#!/usr/bin/env python3
"""
@Input:  --analysis (flu_risk, readiness, audit), --days
@Output: JSON Analysis Report with Actionable Insights
@Pos:    Intelligence Layer. Second-order analysis of raw health data.

!!! Maintenance Protocol: Tune thresholds based on user feedback. 
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# Import data fetcher
sys.path.insert(0, str(Path(__file__).parent))
from garmin_auth import get_client
from garmin_data import fetch_summary

def analyze_flu_risk(summary_data):
    """
    Detect 'The Garmin Flu' pattern:
    1. RHR spike (> 3 bpm above baseline)
    2. HRV drop (> 10% below baseline)
    """
    hrv_data = summary_data.get("hrv", [])
    hr_data = summary_data.get("heart_rate", [])
    
    # Need at least 3 days of data
    if len(hrv_data) < 3 or len(hr_data) < 3:
        return {"status": "insufficient_data"}
        
    # Get latest data (look for last non-null values)
    latest_hrv_entry = next((item for item in reversed(hrv_data) if item.get("last_night_avg")), hrv_data[-1])
    latest_hr_entry = next((item for item in reversed(hr_data) if item.get("resting_hr")), hr_data[-1])
    
    # Calculate simple baseline (avg of previous days)
    prev_hrv = [d.get("last_night_avg") for d in hrv_data if d.get("last_night_avg") and d != latest_hrv_entry]
    prev_rhr = [d.get("resting_hr") for d in hr_data if d.get("resting_hr") and d != latest_hr_entry]
    
    if not prev_hrv or not prev_rhr:
        return {"status": "insufficient_baseline"}
        
    avg_hrv_baseline = sum(prev_hrv) / len(prev_hrv)
    avg_rhr_baseline = sum(prev_rhr) / len(prev_rhr)
    
    current_hrv = latest_hrv_entry.get("last_night_avg") or avg_hrv_baseline
    current_rhr = latest_hr_entry.get("resting_hr") or avg_rhr_baseline
    
    # Thresholds
    hrv_drop_pct = (avg_hrv_baseline - current_hrv) / avg_hrv_baseline * 100
    rhr_spike = current_rhr - avg_rhr_baseline
    
    risk_level = "low"
    reasons = []
    
    if rhr_spike > 5 and hrv_drop_pct > 15:
        risk_level = "HIGH"
        reasons.append(f"Significant RHR spike (+{rhr_spike:.1f} bpm)")
        reasons.append(f"Major HRV drop (-{hrv_drop_pct:.1f}%)")
    elif rhr_spike > 3 and hrv_drop_pct > 10:
        risk_level = "MODERATE"
        reasons.append(f"RHR elevated (+{rhr_spike:.1f} bpm)")
        reasons.append(f"HRV dip (-{hrv_drop_pct:.1f}%)")
        
    return {
        "analysis_type": "bio_entropy_flu_risk",
        "date": latest_hrv_entry["date"],
        "risk_level": risk_level,
        "metrics": {
            "current_rhr": current_rhr,
            "baseline_rhr": round(avg_rhr_baseline, 1),
            "current_hrv": current_hrv,
            "baseline_hrv": round(avg_hrv_baseline, 1)
        },
        "insights": reasons
    }

def analyze_executive_readiness(summary_data):
    """
    Calculate Daily Executive Readiness Score (0-100)
    """
    # Get latest non-null data
    sleep_list = summary_data.get("sleep", [])
    bb_list = summary_data.get("body_battery", [])
    stress_list = summary_data.get("stress", [])

    latest_sleep = next((s for s in reversed(sleep_list) if s.get("sleep_score")), {})
    latest_bb = next((b for b in reversed(bb_list) if b.get("highest")), {})
    latest_stress = next((st for st in reversed(stress_list) if st.get("avg_stress")), {})
    
    sleep_score = latest_sleep.get("sleep_score", 0) or 0
    bb_peak = latest_bb.get("highest", 0) or 0
    avg_stress = latest_stress.get("avg_stress", 50) or 50
    
    readiness_score = (sleep_score * 0.4) + (bb_peak * 0.4) + ((100 - avg_stress) * 0.2)
    
    recommendation = ""
    if readiness_score >= 85:
        recommendation = "Peak State. Ideal for high-stakes decisions and creative strategy."
    elif readiness_score >= 70:
        recommendation = "Optimal. Good for complex execution."
    elif readiness_score >= 50:
        recommendation = "Sub-optimal. Focus on routine tasks. Avoid late-night strategic pivots."
    else:
        recommendation = "Depleted. Defer critical decisions. Focus on recovery."

    return {
        "analysis_type": "executive_readiness",
        "score": round(readiness_score, 1),
        "recommendation": recommendation,
        "components": {
            "sleep_contribution": round(sleep_score * 0.4, 1),
            "body_battery_contribution": round(bb_peak * 0.4, 1),
            "stress_contribution": round((100 - avg_stress) * 0.2, 1)
        }
    }

def main():
    parser = argparse.ArgumentParser(description="Advanced Health Intelligence")
    parser.add_argument("analysis", choices=["flu_risk", "readiness"], help="Analysis type")
    parser.add_argument("--days", type=int, default=7, help="Context window")
    
    args = parser.parse_args()
    
    client = get_client()
    if not client:
        print('{"error": "Not authenticated"}', file=sys.stderr)
        sys.exit(1)
        
    # Fetch all data needed
    summary_data = fetch_summary(client, args.days)
    
    if args.analysis == "flu_risk":
        result = analyze_flu_risk(summary_data)
    elif args.analysis == "readiness":
        result = analyze_executive_readiness(summary_data)
        
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
