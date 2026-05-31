#!/usr/bin/env python3
"""
@Input:  --type (hrv, rhr, sleep, stress), --days
@Output: FHIR Bundle (JSON) containing Observation resources
@Pos:    Interface Layer. Standardizes proprietary Garmin data into HL7 FHIR.

!!! Maintenance Protocol: Update LOINC codes if standards change. Sync with garmin_data.py structure.
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
import argparse

# Import data fetcher
sys.path.insert(0, str(Path(__file__).parent))
from garmin_auth import get_client
from garmin_data import fetch_hrv, fetch_heart_rate, fetch_sleep, fetch_stress

# LOINC Code Registry
LOINC_CODES = {
    "hrv": {"code": "8867-4", "display": "Heart rate variability", "unit": "ms"},
    "rhr": {"code": "40443-4", "display": "Resting heart rate", "unit": "/min"},
    "vo2max": {"code": "98044-1", "display": "VO2 max", "unit": "mL/kg/min"},
    "steps": {"code": "55423-8", "display": "Number of steps in 24 hour Measured", "unit": "steps"},
    "sleep_duration": {"code": "93832-4", "display": "Sleep duration", "unit": "h"},
    "sleep_score": {"code": "93831-6", "display": "Sleep quality score", "unit": "{score}"},
    "deep_sleep": {"code": "93833-2", "display": "Deep sleep duration", "unit": "h"},
    "rem_sleep": {"code": "93834-0", "display": "REM sleep duration", "unit": "h"},
    "stress": {"code": "93025-5", "display": "Stress level score", "unit": "{score}"},
}

def create_fhir_bundle(observations):
    """Wrap observations in a FHIR Bundle."""
    return {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "collection",
        "timestamp": datetime.now().isoformat(),
        "total": len(observations),
        "entry": [{"resource": obs} for obs in observations]
    }

def create_observation(value, date_str, metric_type):
    """Create a single FHIR Observation resource."""
    meta = LOINC_CODES.get(metric_type)
    if not meta:
        return None
        
    return {
        "resourceType": "Observation",
        "id": str(uuid.uuid4()),
        "status": "final",
        "code": {
            "coding": [{
                "system": "http://loinc.org",
                "code": meta["code"],
                "display": meta["display"]
            }]
        },
        "subject": {
            "reference": "Patient/Self" 
        },
        "effectiveDateTime": date_str,
        "valueQuantity": {
            "value": round(value, 2) if isinstance(value, float) else value,
            "unit": meta["unit"],
            "system": "http://unitsofmeasure.org",
            "code": meta["unit"]
        }
    }

def convert_hrv(client, days):
    """Convert HRV data to FHIR Observations."""
    data = fetch_hrv(client, days).get("hrv", [])
    observations = []
    for entry in data:
        if entry.get("last_night_avg"):
            obs = create_observation(
                entry["last_night_avg"], 
                entry["date"], 
                "hrv"
            )
            if obs: observations.append(obs)
    return observations

def convert_rhr(client, days):
    """Convert resting heart rate data to FHIR Observations."""
    data = fetch_heart_rate(client, days).get("heart_rate", [])
    observations = []
    for entry in data:
        if entry.get("resting_hr"):
            obs = create_observation(
                entry["resting_hr"], 
                entry["date"], 
                "rhr"
            )
            if obs: observations.append(obs)
    return observations

def convert_sleep(client, days):
    """Convert sleep data to FHIR Observations (duration, score, deep, REM)."""
    data = fetch_sleep(client, days).get("sleep", [])
    observations = []
    for entry in data:
        date = entry["date"]
        
        # Sleep duration
        if entry.get("sleep_time_seconds"):
            hours = round(entry["sleep_time_seconds"] / 3600, 2)
            obs = create_observation(hours, date, "sleep_duration")
            if obs: observations.append(obs)
        
        # Sleep score
        if entry.get("sleep_score") is not None:
            obs = create_observation(entry["sleep_score"], date, "sleep_score")
            if obs: observations.append(obs)
        
        # Deep sleep
        if entry.get("deep_sleep_seconds"):
            hours = round(entry["deep_sleep_seconds"] / 3600, 2)
            obs = create_observation(hours, date, "deep_sleep")
            if obs: observations.append(obs)
        
        # REM sleep
        if entry.get("rem_sleep_seconds"):
            hours = round(entry["rem_sleep_seconds"] / 3600, 2)
            obs = create_observation(hours, date, "rem_sleep")
            if obs: observations.append(obs)
    
    return observations

def convert_stress(client, days):
    """Convert stress data to FHIR Observations."""
    data = fetch_stress(client, days).get("stress", [])
    observations = []
    for entry in data:
        if entry.get("avg_stress") is not None:
            obs = create_observation(
                entry["avg_stress"],
                entry["date"],
                "stress"
            )
            if obs: observations.append(obs)
    return observations

def main():
    parser = argparse.ArgumentParser(description="Export Garmin data to FHIR format")
    parser.add_argument("type", choices=["hrv", "rhr", "sleep", "stress"], help="Metric to export")
    parser.add_argument("--days", type=int, default=7, help="Number of days")
    
    args = parser.parse_args()
    
    client = get_client()
    if not client:
        print('{"error": "Not authenticated"}', file=sys.stderr)
        sys.exit(1)
        
    observations = []
    if args.type == "hrv":
        observations = convert_hrv(client, args.days)
    elif args.type == "rhr":
        observations = convert_rhr(client, args.days)
    elif args.type == "sleep":
        observations = convert_sleep(client, args.days)
    elif args.type == "stress":
        observations = convert_stress(client, args.days)
        
    bundle = create_fhir_bundle(observations)
    print(json.dumps(bundle, indent=2))

if __name__ == "__main__":
    main()
