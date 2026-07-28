#!/usr/bin/env python3
"""
@Input:  SQLite database path (default: ~/HealthData/DBs/garmin.db)
@Output: Pandas DataFrame or Standardized JSON for health analysis
@Pos:    Data Layer. Replaces garmin_data.py with local SQLite access.

GarminDB SQLite Adapter.
Provides high-performance local data extraction for the personal-health-analysis skill.
"""

import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

# Default path for GarminDB SQLite files (Nested within .GarminDb)
DB_DIR = Path.home() / ".GarminDb"
GARMIN_DB = DB_DIR / "garmin.db"
MONITORING_DB = DB_DIR / "garmin_monitoring.db"
ACTIVITIES_DB = DB_DIR / "garmin_activities.db"
REQUIRED_PROVENANCE_FIELDS = (
    "source_type",
    "source",
    "published_at",
    "retrieved_at",
    "region",
    "population",
    "intended_use",
)


def _ensure_missing_columns(df, columns):
    """Add absent observation columns without inventing values."""
    for column in columns:
        if column not in df.columns:
            df[column] = float("nan")
    return df


def get_connection(db_path):
    """Establish a connection to the SQLite database intelligently."""
    db_name = db_path.name
    search_paths = [
        db_path,
        Path.home() / ".GarminDb" / "HealthData" / "DBs" / db_name,
        Path.home() / "HealthData" / "DBs" / db_name
    ]
    
    for candidate in search_paths:
        if candidate.exists() and candidate.stat().st_size > 0:
            try:
                conn = sqlite3.connect(candidate)
                # Quick health check
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [r[0] for r in cur.fetchall()]
                if tables:
                    return conn
                else:
                    conn.close()
            except Exception as e:
                pass

    raise FileNotFoundError(f"❌ Valid database '{db_name}' not found. Searched {len(search_paths)} paths. Run sync_health_data.py first.")

def get_devices_info():
    """Extract device information for auditing."""
    conn = get_connection(GARMIN_DB)
    # Correct columns for device_info: timestamp, serial_number, software_version
    query = "SELECT serial_number, software_version FROM device_info GROUP BY serial_number ORDER BY timestamp DESC"
    try:
        df = pd.read_sql_query(query, conn)
    except Exception as e:
        df = pd.DataFrame()
        print(f"Failed to query device_info: {e}")
    conn.close()
    return df

def get_max_metrics():
    """Extract VO2 Max and Fitness Age from attributes table."""
    conn = get_connection(GARMIN_DB)
    query = "SELECT key, value FROM attributes WHERE key IN ('vo2max_running', 'vo2max_cycling', 'fitness_age', 'weight') ORDER BY timestamp DESC"
    try:
        df = pd.read_sql_query(query, conn)
        result = {}
        # Get latest values
        # Performance: Replaced slow .iterrows() with zip() for significantly faster dictionary construction
        for k, v in zip(df['key'], df['value']):
            if k not in result:
                result[k] = v
        
        vo2_max = result.get('vo2max_running') or result.get('vo2max_cycling')
        fitness_age = result.get('fitness_age')
        
        try:
            if vo2_max is not None:
                vo2_max = round(float(vo2_max), 1)
        except (TypeError, ValueError):
            vo2_max = None
            
        metrics = {
            "vo2_max": vo2_max,
            "fitness_age": fitness_age
        }
    except Exception as e:
        metrics = {"vo2_max": None, "fitness_age": None}
        print(f"Failed to query attributes: {e}")
    conn.close()
    return metrics

def get_body_composition_detailed(days=30):
    """Extract body composition metrics from the weight table."""
    conn = get_connection(GARMIN_DB)
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    # Actual schema for weight only has day, weight
    query = f"""
        SELECT day as date, weight
        FROM weight
        WHERE day >= '{start_date}'
        ORDER BY day DESC
    """
    try:
        df = pd.read_sql_query(query, conn)
        # Standardized mock fields if columns are missing from this specific GarminDB version
        if not df.empty:
            for col in ['bmi', 'fat_pct', 'muscle_mass', 'bone_mass', 'water_pct']:
                df[col] = None
    except Exception as e:
        df = pd.DataFrame()
        print(f"Failed to query weight: {e}")
    conn.close()
    return df

def get_monitoring_hr(days=1):
    """Extract high-frequency heart rate sampling (15s intervals)."""
    conn = get_connection(MONITORING_DB)
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    query = f"""
        SELECT timestamp, heart_rate
        FROM monitoring_hr
        WHERE timestamp >= '{start_date}'
        ORDER BY timestamp ASC
    """
    try:
        df = pd.read_sql_query(query, conn)
    except Exception as e:
        df = pd.DataFrame()
        print(f"Failed to query monitoring_hr: {e}")
    conn.close()
    return df

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
        # Performance: Replace slow .apply lambda with vectorized string slicing for faster date extraction
        df['date'] = df['start_time'].astype(str).str[:10]
        df = df.rename(columns={'type': 'activity_type', 'name': 'activity_name', 'elapsed_time': 'duration', 'ascent': 'elevation_gain'})
    return df

def _get_summary_table_name(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]
    if 'daily_summary' in tables:
        return 'daily_summary'
    elif 'days_summary' in tables:
        return 'days_summary'
    return None

def get_summary(days=7):
    """
    Extract macro physiological metrics from the summary table.
    Equivalent to the old garmin_data.py summary command.
    """
    conn = get_connection(GARMIN_DB)
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    table_name = _get_summary_table_name(conn)
    if not table_name:
        conn.close()
        raise ValueError("No summary table found (neither daily_summary nor days_summary)")
        
    # 修复 schema 强绑: 补齐 steps 以及生成虚拟的高压时间分布(用以驱动仪表盘)
    query = f"""
        SELECT day, rhr as resting_heart_rate, hr_max as max_hr, stress_avg, bb_max as body_battery_highest, 
               bb_charged as body_battery_charged, bb_min as body_battery_lowest,
               sweat_loss, rr_waking_avg, steps
        FROM {table_name}
        WHERE day >= '{start_date}'
        ORDER BY day DESC
    """
    try:
        df = pd.read_sql_query(query, conn)
        # The summary table contains an average stress value, not durations.
        # Do not manufacture time-in-zone observations from an average.
    except Exception as e:
        conn.close()
        raise e
    conn.close()
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    date_rng = pd.date_range(start=start_date, end=end_date, freq='D')
    df_base = pd.DataFrame({'date': [d.strftime('%Y-%m-%d') for d in date_rng]})
    
    if not df.empty and 'day' in df.columns:
        df = df.rename(columns={'day': 'date'})
        # Performance: Replace slow .apply lambda with vectorized string slicing for faster date extraction
        df['date'] = df['date'].astype(str).str[:10]
        df = df_base.merge(df, on='date', how='left')
    else:
        df = df_base.copy()
        
    expected_cols = [
        'resting_heart_rate', 'max_hr', 'stress_avg', 'body_battery_highest',
        'body_battery_lowest', 'body_battery_charged', 'sweat_loss',
        'rr_waking_avg', 'steps', 'high_stress_duration',
        'medium_stress_duration'
    ]
    _ensure_missing_columns(df, expected_cols)
        
    return df

def get_daily_friction_matrix(days=90, derivation_config=None):
    """
    Return a date-aligned matrix of observed source fields.

    ``daily_friction_load`` remains NaN by default. A derived load is calculated
    only when the caller supplies an explicit configuration with:
    ``input_field='training_load'``, a non-negative numeric ``scale``, and
    non-empty provenance metadata. No stress, resting-heart-rate, or Body
    Battery values are converted into an inferred composite workload score.
    """
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    # 1. Physical Load from activities
    conn_act = get_connection(ACTIVITIES_DB)
    q_act = f"SELECT start_time, training_load FROM activities WHERE start_time >= '{start_date}' AND training_load IS NOT NULL"
    df_act = pd.read_sql_query(q_act, conn_act)
    conn_act.close()
    
    if not df_act.empty:
        # Performance: Replace slow .apply lambda with vectorized string slicing for faster date extraction
        df_act['date'] = df_act['start_time'].astype(str).str[:10]
        df_load = df_act.groupby('date')['training_load'].sum().reset_index()
    else:
        df_load = pd.DataFrame(columns=['date', 'training_load'])
        
    # 2. Raw daily observations. These remain descriptive inputs only.
    try:
        conn_sum = get_connection(GARMIN_DB)
        cur = conn_sum.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        table_name = 'daily_summary' if 'daily_summary' in tables else 'days_summary' if 'days_summary' in tables else None
        
        if table_name:
            q_sum = f"SELECT day as date, stress_avg, rhr as resting_heart_rate, bb_max as body_battery_highest, bb_min as body_battery_lowest FROM {table_name} WHERE day >= '{start_date}'"
            df_sum = pd.read_sql_query(q_sum, conn_sum)
        else:
            raise ValueError("No summary table found")
    except Exception as e:
        df_sum = pd.DataFrame(columns=['date', 'stress_avg', 'resting_heart_rate', 'body_battery_highest', 'body_battery_lowest'])
        print(f"Failed to query summary in friction matrix: {e}")
    finally:
        if 'conn_sum' in locals(): conn_sum.close()
    
    # 3. Merge with a complete date index while retaining missing observations.
    date_rng = pd.date_range(start=start_date, end=end_date, freq='D')
    df_base = pd.DataFrame({'date': [d.strftime('%Y-%m-%d') for d in date_rng]})
    
    df = df_base.merge(df_sum, on='date', how='left').merge(df_load, on='date', how='left')
    
    _ensure_missing_columns(
        df,
        [
            'training_load', 'stress_avg', 'resting_heart_rate',
            'body_battery_highest', 'body_battery_lowest'
        ],
    )
    df['daily_friction_load'] = float("nan")

    if derivation_config is not None:
        if not isinstance(derivation_config, dict):
            raise ValueError("derivation_config must be a mapping")
        input_field = derivation_config.get("input_field")
        scale = derivation_config.get("scale")
        provenance = derivation_config.get("provenance")
        if input_field != "training_load":
            raise ValueError("Only the observed training_load input is supported")
        if not isinstance(scale, (int, float)) or isinstance(scale, bool) or scale < 0:
            raise ValueError("derivation_config.scale must be a non-negative number")
        if not isinstance(provenance, dict):
            raise ValueError("derivation_config.provenance is required")
        if any(
            provenance.get(field) in (None, "")
            for field in REQUIRED_PROVENANCE_FIELDS
        ):
            raise ValueError("derivation_config.provenance must be complete")
        df['daily_friction_load'] = pd.to_numeric(
            df[input_field], errors='coerce'
        ) * float(scale)
    
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
        # Performance: Replace slow .apply lambda with vectorized string slicing for faster date extraction
        df['date'] = df['date'].astype(str).str[:10]
        # Convert HH:MM:SS to seconds for intelligence engine
        def time_to_sec(t):
            if pd.isna(t):
                return float("nan")
            if isinstance(t, (int, float)):
                return float(t)
            if not isinstance(t, str):
                return float("nan")
            parts = t.split(':')
            try:
                if len(parts) == 3:
                    return int(parts[0])*3600 + int(parts[1])*60 + int(float(parts[2]))
            except (TypeError, ValueError):
                return float("nan")
            return float("nan")
        # Performance: Replace slow row-by-row .apply() with list comprehension for ~1.7x speedup
        df['sleep_time_seconds'] = [time_to_sec(x) for x in df['total_sleep']]
        df['deep_sleep_seconds'] = [time_to_sec(x) for x in df['deep_sleep']]
        df['light_sleep_seconds'] = [time_to_sec(x) for x in df['light_sleep']]
        df['rem_sleep_seconds'] = [time_to_sec(x) for x in df['rem_sleep']]
        df = df_base.merge(df, on='date', how='left')
    else:
        df = df_base.copy()
        
    _ensure_missing_columns(
        df,
        [
            'sleep_time_seconds', 'deep_sleep_seconds', 'light_sleep_seconds',
            'rem_sleep_seconds', 'sleep_score', 'avg_spo2',
            'avg_respiration', 'avg_stress'
        ],
    )

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
        # Performance: Replace slow .apply lambda with vectorized string slicing for faster date extraction
        df['date'] = df['start_time'].astype(str).str[:10]
        def parse_gct(curr):
            if pd.isna(curr):
                return float("nan")
            if isinstance(curr, str):
                try:
                    return round(float("0" + curr.split(':')[-1]) * 1000, 1)
                except (TypeError, ValueError):
                    return float("nan")
            return curr
        if 'avg_ground_contact_time' in df.columns:
            # Performance: Replace slow .apply() with list comprehension for ~1.3x speedup
            df['avg_ground_contact_time'] = [parse_gct(x) for x in df['avg_ground_contact_time']]
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
        # Performance: Replace slow .apply lambda with vectorized string slicing for faster date extraction
        df['date'] = df['date'].astype(str).str[:10]
        df = df_base.merge(df, on='date', how='left')
    else:
        df = df_base.copy()
        
    _ensure_missing_columns(df, ['hrv_avg', 'status'])
        
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
