#!/usr/bin/env python3
"""
@Input:  SQLite database path (default: ~/HealthData/DBs/garmin.db)
@Output: Pandas DataFrame or Standardized JSON for health analysis
@Pos:    Data Layer. Replaces garmin_data.py with local SQLite access.

GarminDB SQLite Adapter.
Provides high-performance local data extraction for the personal-health-analysis skill.
"""

import sqlite3
import os
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

# Default path for GarminDB SQLite files (Nested within .GarminDb)
DB_DIR = Path.home() / ".GarminDb" / "HealthData" / "DBs"
GARMIN_DB = DB_DIR / "garmin.db"
SUMMARY_DB = DB_DIR / "garmin_summary.db"
ACTIVITIES_DB = DB_DIR / "garmin_activities.db"

def get_connection(db_path):
    """Establish a connection to the SQLite database."""
    if not db_path.exists():
        raise FileNotFoundError(f"❌ Database not found at {db_path}. Run garmindb_cli.py first.")
    return sqlite3.connect(db_path)

def get_activities_data(days=30):
    """Extract activity metrics from the activities table."""
    conn = get_connection(ACTIVITIES_DB)
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    query = f"""
        SELECT activity_id, name, type, start_time, elapsed_time, distance, avg_hr, max_hr, calories, avg_speed, ascent, training_load
        FROM activities
        WHERE start_time >= '{start_date}'
        ORDER BY start_time DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    # Standardize column names to match the expected format in intelligence layer
    if not df.empty:
        df['date'] = df['start_time'].apply(lambda x: x.split(' ')[0] if isinstance(x, str) else x)
        df = df.rename(columns={'type': 'activity_type', 'name': 'activity_name', 'elapsed_time': 'duration', 'ascent': 'elevation_gain'})
    return df

def get_summary(days=7):
    """
    Extract macro physiological metrics from the daily_summary table.
    Equivalent to the old garmin_data.py summary command.
    """
    conn = get_connection(GARMIN_DB)
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    query = f"""
        SELECT day, resting_heart_rate, stress_avg, body_battery_highest, sleep_score,
               high_stress_duration, medium_stress_duration, rest_stress_duration,
               body_battery_charged, body_battery_lowest,
               sweat_loss, rr_waking_avg
        FROM daily_summary
        WHERE day >= '{start_date}'
        ORDER BY day DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    if not df.empty and 'day' in df.columns:
        df = df.rename(columns={'day': 'date'})
    return df

def get_sleep_data(days=14):
    """Extract detailed sleep metrics."""
    conn = get_connection(GARMIN_DB)
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    query = f"""
        SELECT day, total_sleep, deep_sleep, light_sleep, rem_sleep, awake_time, sleep_score, avg_respiration, avg_spo2, avg_stress
        FROM sleep
        WHERE day >= '{start_date}'
        ORDER BY day DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    if not df.empty and 'day' in df.columns:
        df = df.rename(columns={'day': 'date'})
    return df

def get_biomechanics_data(days=30):
    """Extract advanced running dynamics and biomechanical wear & tear data."""
    conn = get_connection(ACTIVITIES_DB)
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    query = f"""
        SELECT a.activity_id, a.start_time, a.distance, a.avg_speed, a.anaerobic_training_effect,
               s.avg_ground_contact_time, s.avg_stance_time_percent
        FROM activities a
        LEFT JOIN steps_activities s ON a.activity_id = s.activity_id
        WHERE a.start_time >= '{start_date}' AND s.avg_ground_contact_time IS NOT NULL
        ORDER BY a.start_time DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if not df.empty:
        df['date'] = df['start_time'].apply(lambda x: x.split(' ')[0] if isinstance(x, str) else str(x).split(' ')[0])
        def parse_gct(curr):
            if pd.isna(curr): return 0
            if isinstance(curr, str):
                try:
                    return round(float("0" + curr.split(':')[-1]) * 1000, 1)
                except:
                    return 0
            return curr
        if 'avg_ground_contact_time' in df.columns:
            df['avg_ground_contact_time'] = df['avg_ground_contact_time'].apply(parse_gct)
        df = df.where(pd.notnull(df), None)
    return df

def get_hrv_data(days=7):
    """Extract HRV data."""
    conn = get_connection(GARMIN_DB)
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    # Table name might vary depending on GarminDB version (hrv or hrv_summary)
    try:
        query = f"SELECT day, hrv_avg FROM hrv WHERE day >= '{start_date}' ORDER BY day DESC"
        df = pd.read_sql_query(query, conn)
    except:
        query = f"SELECT day, weekly_avg as hrv_avg FROM hrv_summary WHERE day >= '{start_date}' ORDER BY day DESC"
        df = pd.read_sql_query(query, conn)
        
    conn.close()
    if not df.empty and 'day' in df.columns:
        df = df.rename(columns={'day': 'date'})
    return df

if __name__ == "__main__":
    # Test execution
    try:
        print("🔍 Testing Local SQLite Extraction...")
        summary = get_summary(3)
        print("✅ Latest Summary Data:")
        print(summary)
    except Exception as e:
        print(f"⚠️  Test failed: {e}")
