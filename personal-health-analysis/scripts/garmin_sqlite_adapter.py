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
        df['date'] = df['start_time'].apply(lambda x: str(x).split(' ')[0])
        df = df.rename(columns={'type': 'activity_type', 'name': 'activity_name', 'elapsed_time': 'duration', 'ascent': 'elevation_gain'})
    return df

def get_summary(days=7):
    """
    Extract macro physiological metrics from the daily_summary table.
    Equivalent to the old garmin_data.py summary command.
    """
    conn = get_connection(GARMIN_DB)
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    # 修复 schema 强绑: 补齐 steps 以及生成虚拟的高压时间分布(用以驱动仪表盘)
    query = f"""
        SELECT day, rhr as resting_heart_rate, hr_max as max_hr, stress_avg, bb_max as body_battery_highest, 
               bb_charged as body_battery_charged, bb_min as body_battery_lowest,
               sweat_loss, rr_waking_avg, steps
        FROM daily_summary
        WHERE day >= '{start_date}'
        ORDER BY day DESC
    """
    try:
        df = pd.read_sql_query(query, conn)
        if not df.empty:
            df['high_stress_duration'] = df['stress_avg'].apply(lambda x: max(0, x - 35) * 3600 / 15 if pd.notnull(x) else 0)
            df['medium_stress_duration'] = df['stress_avg'].apply(lambda x: max(0, x - 25) * 3600 / 10 if pd.notnull(x) else 0)
    except Exception as e:
        df = pd.DataFrame()
        print(f"Failed to query summary: {e}")
    conn.close()
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    date_rng = pd.date_range(start=start_date, end=end_date, freq='D')
    df_base = pd.DataFrame({'date': [d.strftime('%Y-%m-%d') for d in date_rng]})
    
    if not df.empty and 'day' in df.columns:
        df = df.rename(columns={'day': 'date'})
        df['date'] = df['date'].apply(lambda x: str(x).split(' ')[0])
        df = df_base.merge(df, on='date', how='left')
    else:
        df = df_base.copy()
        
    if 'stress_avg' in df.columns:
        df['resting_heart_rate'] = df['resting_heart_rate'].ffill().bfill().fillna(60)
        df['max_hr'] = df['max_hr'].ffill().bfill().fillna(160)
        df['stress_avg'] = df['stress_avg'].ffill().bfill().fillna(25)
        df['body_battery_highest'] = df['body_battery_highest'].ffill().bfill().fillna(100)
        df['body_battery_lowest'] = df['body_battery_lowest'].ffill().bfill().fillna(20)
        df['body_battery_charged'] = df['body_battery_charged'].fillna(0)
        df['sweat_loss'] = df['sweat_loss'].fillna(0)
        df['rr_waking_avg'] = df['rr_waking_avg'].ffill().bfill().fillna(14.0)
        df['steps'] = df['steps'].fillna(0)
        df['high_stress_duration'] = df['high_stress_duration'].fillna(0)
        df['medium_stress_duration'] = df['medium_stress_duration'].fillna(0)
        
    return df

def get_daily_friction_matrix(days=90):
    """
    V4.0 API: Provide raw data matrix for PMC (CTL/ATL/TSB) analysis.
    Merges daily physical training load + cognitive shadow load + battery drain.
    Enforces Strict Zero-Padding to prevent mathematical EWMA failures on non-activity days.
    """
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    # 1. Physical Load from activities
    conn_act = get_connection(ACTIVITIES_DB)
    q_act = f"SELECT start_time, training_load FROM activities WHERE start_time >= '{start_date}' AND training_load IS NOT NULL"
    df_act = pd.read_sql_query(q_act, conn_act)
    conn_act.close()
    
    if not df_act.empty:
        df_act['date'] = df_act['start_time'].apply(lambda x: str(x).split(' ')[0])
        df_load = df_act.groupby('date')['training_load'].sum().reset_index()
    else:
        df_load = pd.DataFrame(columns=['date', 'training_load'])
        
    # 2. Physiological Friction (Stress & RHR & Body Battery)
    conn_sum = get_connection(GARMIN_DB)
    q_sum = f"SELECT day as date, stress_avg, rhr as resting_heart_rate, bb_max as body_battery_highest, bb_min as body_battery_lowest FROM daily_summary WHERE day >= '{start_date}'"
    df_sum = pd.read_sql_query(q_sum, conn_sum)
    conn_sum.close()
    
    # 3. Merge with Complete Time Series (Zero-padding)
    date_rng = pd.date_range(start=start_date, end=end_date, freq='D')
    df_base = pd.DataFrame({'date': [d.strftime('%Y-%m-%d') for d in date_rng]})
    
    df = df_base.merge(df_sum, on='date', how='left').merge(df_load, on='date', how='left')
    
    # Fill NAs
    df['training_load'] = df['training_load'].fillna(0)
    # Forward fill missing physiological values to prevent math collapse, then fallback to safe baseline
    mean_stress = df['stress_avg'].mean() if pd.notnull(df['stress_avg'].mean()) else 25
    df['stress_avg'] = df['stress_avg'].ffill().bfill().fillna(mean_stress)
    df['resting_heart_rate'] = df['resting_heart_rate'].ffill().bfill().fillna(60)
    df['body_battery_highest'] = df['body_battery_highest'].fillna(100)
    df['body_battery_lowest'] = df['body_battery_lowest'].fillna(20)
    
    # Compute Executive Shadow Load
    # Formula: Physical + max(0, stress_avg - 25)*2 + (bb_drain * 0.5)
    def compute_total_load(row):
        phys = row['training_load']
        stress = row['stress_avg']
        shadow_stress = max(0, stress - 25) * 2
        bb_drain = max(0, row['body_battery_highest'] - row['body_battery_lowest']) * 0.5
        return phys + shadow_stress + bb_drain
        
    df['daily_friction_load'] = df.apply(compute_total_load, axis=1)
    
    return df


def get_sleep_data(days=14):
    """Extract detailed sleep metrics."""
    conn = get_connection(GARMIN_DB)
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    query = f"""
        SELECT day, total_sleep, deep_sleep, light_sleep, rem_sleep, 
               awake as awake_time, score as sleep_score, avg_rr as avg_respiration, 
               avg_spo2, avg_stress
        FROM sleep
        WHERE day >= '{start_date}'
        ORDER BY day DESC
    """
    try:
        df = pd.read_sql_query(query, conn)
    except Exception as e:
        df = pd.DataFrame()
        print(f"Failed to query sleep: {e}")
    conn.close()
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    date_rng = pd.date_range(start=start_date, end=end_date, freq='D')
    df_base = pd.DataFrame({'date': [d.strftime('%Y-%m-%d') for d in date_rng]})
    
    if not df.empty and 'day' in df.columns:
        df = df.rename(columns={'day': 'date'})
        df['date'] = df['date'].apply(lambda x: str(x).split(' ')[0])
        # Convert HH:MM:SS to seconds for intelligence engine
        def time_to_sec(t):
            if pd.isna(t) or not isinstance(t, str): return 0
            parts = t.split(':')
            if len(parts) == 3: return int(parts[0])*3600 + int(parts[1])*60 + int(float(parts[2]))
            return 0
        df['sleep_time_seconds'] = df['total_sleep'].apply(time_to_sec)
        df['deep_sleep_seconds'] = df['deep_sleep'].apply(time_to_sec)
        df['light_sleep_seconds'] = df['light_sleep'].apply(time_to_sec)
        df['rem_sleep_seconds'] = df['rem_sleep'].apply(time_to_sec)
        df = df_base.merge(df, on='date', how='left')
    else:
        df = df_base.copy()
        
    if 'sleep_time_seconds' in df.columns:
        df['sleep_time_seconds'] = df['sleep_time_seconds'].fillna(0)
        df['deep_sleep_seconds'] = df['deep_sleep_seconds'].fillna(0)
        df['light_sleep_seconds'] = df['light_sleep_seconds'].fillna(0)
        df['rem_sleep_seconds'] = df['rem_sleep_seconds'].fillna(0)
        df['sleep_score'] = df['sleep_score'].ffill().bfill().fillna(0)
        df['avg_spo2'] = df['avg_spo2'].ffill().bfill().fillna(95.0)
        df['avg_respiration'] = df['avg_respiration'].ffill().bfill().fillna(14.0)

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
    
    try:
        query = f"SELECT day, last_night_avg as hrv_avg, status FROM hrv WHERE day >= '{start_date}' ORDER BY day DESC"
        df = pd.read_sql_query(query, conn)
    except Exception as e:
        df = pd.DataFrame()
        print(f"Failed to query hrv: {e}")
        
    conn.close()
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    date_rng = pd.date_range(start=start_date, end=end_date, freq='D')
    df_base = pd.DataFrame({'date': [d.strftime('%Y-%m-%d') for d in date_rng]})
    
    if not df.empty and 'day' in df.columns:
        df = df.rename(columns={'day': 'date'})
        df['date'] = df['date'].apply(lambda x: str(x).split(' ')[0])
        df = df_base.merge(df, on='date', how='left')
    else:
        df = df_base.copy()
        
    if 'hrv_avg' in df.columns:
        df['hrv_avg'] = df['hrv_avg'].ffill().bfill().fillna(40)
        df['status'] = df['status'].fillna('BALANCED')
        
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
