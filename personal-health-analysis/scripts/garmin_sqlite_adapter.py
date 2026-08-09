#!/usr/bin/env python3
"""
@Input:  SQLite database path (default: ~/HealthData/DBs/garmin.db)
@Output: Pandas DataFrame or Standardized JSON for health analysis
@Pos:    Data Layer. Replaces garmin_data.py with local SQLite access.

GarminDB SQLite Adapter.
Provides high-performance local data extraction for the personal-health-analysis skill.
"""

import contextvars
import hashlib
import json
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

# Default path for GarminDB SQLite files (Nested within .GarminDb)
DB_DIR = Path.home() / ".GarminDb"
GARMIN_DB = DB_DIR / "garmin.db"
MONITORING_DB = DB_DIR / "garmin_monitoring.db"
ACTIVITIES_DB = DB_DIR / "garmin_activities.db"
_PINNED_DATABASES = contextvars.ContextVar(
    "garmin_pinned_databases", default=None
)
REQUIRED_PROVENANCE_FIELDS = (
    "source_type",
    "source",
    "published_at",
    "retrieved_at",
    "region",
    "population",
    "intended_use",
)


class LocalDatabaseChangedError(RuntimeError):
    """Raised when a local database changes during one logical analysis."""


class LocalDatabaseReadError(RuntimeError):
    """Machine-readable local schema or query failure without raw SQL details."""


def _candidate_paths(db_path):
    requested = Path(db_path)
    db_name = requested.name
    pinned = _PINNED_DATABASES.get()
    if pinned is not None and db_name in pinned:
        return [pinned[db_name]]
    return [
        requested,
        Path.home() / ".GarminDb" / "HealthData" / "DBs" / db_name,
        Path.home() / "HealthData" / "DBs" / db_name,
    ]


def resolve_database_path(db_path):
    """Resolve one GarminDB file without creating or modifying it."""
    search_paths = _candidate_paths(db_path)
    for candidate in search_paths:
        candidate = Path(candidate).expanduser()
        try:
            if not candidate.is_file() or candidate.stat().st_size <= 0:
                continue
            uri = f"{candidate.resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
            try:
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' LIMIT 1"
                ).fetchall()
            finally:
                connection.close()
            if tables:
                return candidate.resolve()
        except (OSError, sqlite3.Error):
            continue
    raise FileNotFoundError(
        f"Valid database '{Path(db_path).name}' not found. "
        f"Searched {len(search_paths)} read-only paths."
    )


def _hash_file_stably(path):
    path = Path(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise LocalDatabaseChangedError(
            f"Local database '{path.name}' changed while its fingerprint was read."
        )
    return {
        "sha256": digest.hexdigest(),
        "size_bytes": after.st_size,
        "mtime_ns": after.st_mtime_ns,
    }


def fingerprint_database(db_path):
    """Return a path-free content, metadata, sidecar and schema fingerprint."""
    path = resolve_database_path(db_path)
    uri = f"{path.as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        schema_rows = connection.execute(
            """
            SELECT type, name, tbl_name, COALESCE(sql, '')
            FROM sqlite_master
            WHERE type IN ('table', 'index', 'view', 'trigger')
            ORDER BY type, name, tbl_name, sql
            """
        ).fetchall()
    finally:
        connection.close()
    schema_payload = json.dumps(
        schema_rows, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    main = _hash_file_stably(path)
    storage_digest = hashlib.sha256()
    storage_digest.update(path.name.encode("utf-8"))
    storage_digest.update(main["sha256"].encode("ascii"))
    sidecars = []
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")
        if not sidecar.is_file():
            continue
        item = _hash_file_stably(sidecar)
        storage_digest.update(sidecar.name.encode("utf-8"))
        storage_digest.update(item["sha256"].encode("ascii"))
        sidecars.append(
            {
                "name": sidecar.name,
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"],
                "mtime_ns": item["mtime_ns"],
            }
        )
    return {
        "database": path.name,
        **main,
        "schema_sha256": hashlib.sha256(schema_payload).hexdigest(),
        "storage_sha256": storage_digest.hexdigest(),
        "sidecars": sidecars,
    }


class VerifiedDatabaseReadWindow:
    """Pin database resolution and verify that every file stayed unchanged."""

    def __init__(self, database_paths):
        self._requested_paths = [Path(path) for path in database_paths]
        self._resolved = []
        self._before = []
        self._token = None
        self._verified = False

    def __enter__(self):
        resolved_by_name = {}
        for requested in self._requested_paths:
            resolved = resolve_database_path(requested)
            if (
                resolved.name in resolved_by_name
                and resolved_by_name[resolved.name] != resolved
            ):
                raise ValueError(
                    f"Ambiguous database name in verified read window: {resolved.name}"
                )
            resolved_by_name[resolved.name] = resolved
        self._resolved = [resolved_by_name[name] for name in sorted(resolved_by_name)]
        self._before = [fingerprint_database(path) for path in self._resolved]
        self._token = _PINNED_DATABASES.set(resolved_by_name)
        return self

    def __exit__(self, exc_type, exc, traceback):
        changed = None
        try:
            after = [fingerprint_database(path) for path in self._resolved]
            for before_item, after_item in zip(self._before, after):
                if before_item != after_item:
                    changed = before_item["database"]
                    break
            self._verified = changed is None
        finally:
            if self._token is not None:
                _PINNED_DATABASES.reset(self._token)
                self._token = None
        if changed is not None:
            raise LocalDatabaseChangedError(
                f"Local database '{changed}' changed during the verified read window."
            )
        return False

    def public_summary(self):
        if not self._verified:
            raise RuntimeError("Database read window has not been verified.")
        return {
            "status": "verified_unchanged",
            "databases": [dict(item) for item in self._before],
        }


def verified_database_read_window(database_paths):
    return VerifiedDatabaseReadWindow(database_paths)


def _ensure_missing_columns(df, columns):
    """Add absent observation columns without inventing values."""
    for column in columns:
        if column not in df.columns:
            df[column] = float("nan")
    return df


def _validated_days(days):
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError("days must be a positive integer")
    return days


def _window_start(days, include_time=False):
    days = _validated_days(days)
    start = datetime.now().date() - timedelta(days=days - 1)
    return f"{start.isoformat()} 00:00:00" if include_time else start.isoformat()


def get_connection(db_path):
    """Open the resolved database read-only, honoring an active pinned window."""
    candidate = resolve_database_path(db_path)
    uri = f"{candidate.as_uri()}?mode=ro"
    return sqlite3.connect(uri, uri=True)

def get_devices_info():
    """Extract device information for auditing."""
    conn = get_connection(GARMIN_DB)
    query = """
        WITH ranked AS (
            SELECT timestamp, serial_number, software_version,
                   ROW_NUMBER() OVER (
                       PARTITION BY serial_number
                       ORDER BY timestamp DESC, rowid DESC
                   ) AS row_rank
            FROM device_info
            WHERE serial_number IS NOT NULL
        )
        SELECT serial_number, software_version, timestamp
        FROM ranked
        WHERE row_rank = 1
        ORDER BY serial_number ASC
    """
    try:
        return pd.read_sql_query(query, conn)
    except Exception as exc:
        raise LocalDatabaseReadError("device_info_query_failed") from exc
    finally:
        conn.close()


def get_device_firmware_history():
    """Return deterministic timestamped firmware evidence for epoch checks."""
    conn = get_connection(GARMIN_DB)
    query = """
        SELECT timestamp, serial_number, software_version
        FROM device_info
        WHERE serial_number IS NOT NULL
          AND software_version IS NOT NULL
          AND timestamp IS NOT NULL
        ORDER BY timestamp ASC, serial_number ASC, rowid ASC
    """
    try:
        return pd.read_sql_query(query, conn)
    except Exception as exc:
        raise LocalDatabaseReadError("device_firmware_query_failed") from exc
    finally:
        conn.close()

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
        return metrics
    except Exception as exc:
        raise LocalDatabaseReadError("attributes_query_failed") from exc
    finally:
        conn.close()

def get_body_composition_detailed(days=30):
    """Extract body composition metrics from the weight table."""
    conn = get_connection(GARMIN_DB)
    start_date = _window_start(days)
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
        return df
    except Exception as exc:
        raise LocalDatabaseReadError("weight_query_failed") from exc
    finally:
        conn.close()

def get_monitoring_hr(days=1):
    """Extract high-frequency heart rate sampling (15s intervals)."""
    conn = get_connection(MONITORING_DB)
    start_date = _window_start(days, include_time=True)
    query = f"""
        SELECT timestamp, heart_rate
        FROM monitoring_hr
        WHERE timestamp >= '{start_date}'
        ORDER BY timestamp ASC
    """
    try:
        df = pd.read_sql_query(query, conn)
        return df
    except Exception as exc:
        raise LocalDatabaseReadError("monitoring_hr_query_failed") from exc
    finally:
        conn.close()

def get_activities_data(days=30):
    """Extract activity metrics from the activities table."""
    start_date = _window_start(days)
    conn = get_connection(ACTIVITIES_DB)
    
    query = f"""
        SELECT activity_id, name, type, start_time, elapsed_time, distance, avg_hr, max_hr, calories, avg_speed, ascent, training_load
        FROM activities
        WHERE start_time >= '{start_date}'
        ORDER BY start_time DESC
    """
    try:
        df = pd.read_sql_query(query, conn)
    except Exception as exc:
        raise LocalDatabaseReadError("activities_query_failed") from exc
    finally:
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
    start_date = _window_start(days)
    conn = get_connection(GARMIN_DB)
    
    try:
        table_name = _get_summary_table_name(conn)
        if not table_name:
            raise ValueError("summary_table_missing")
        query = f"""
            SELECT day, rhr as resting_heart_rate, hr_max as max_hr, stress_avg, bb_max as body_battery_highest,
                   bb_charged as body_battery_charged, bb_min as body_battery_lowest,
                   sweat_loss, rr_waking_avg, steps
            FROM {table_name}
            WHERE day >= '{start_date}'
            ORDER BY day DESC
        """
        df = pd.read_sql_query(query, conn)
        # The summary table contains an average stress value, not durations.
        # Do not manufacture time-in-zone observations from an average.
    except Exception as exc:
        raise LocalDatabaseReadError("summary_query_failed") from exc
    finally:
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
    start_date = _window_start(days)
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    # 1. Physical Load from activities
    conn_act = get_connection(ACTIVITIES_DB)
    q_act = f"SELECT start_time, training_load FROM activities WHERE start_time >= '{start_date}' AND training_load IS NOT NULL"
    try:
        df_act = pd.read_sql_query(q_act, conn_act)
    except Exception as exc:
        raise LocalDatabaseReadError("friction_activity_query_failed") from exc
    finally:
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
    except Exception as exc:
        raise LocalDatabaseReadError("friction_summary_query_failed") from exc
    finally:
        if 'conn_sum' in locals():
            conn_sum.close()
    
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
    start_date = _window_start(days)
    conn = get_connection(GARMIN_DB)
    
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
    except Exception as exc:
        raise LocalDatabaseReadError("sleep_query_failed") from exc
    finally:
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
    start_date = _window_start(days)
    conn = get_connection(ACTIVITIES_DB)
    
    query = f"""
        SELECT a.activity_id, a.start_time, a.distance, a.avg_speed, a.anaerobic_training_effect,
               s.avg_ground_contact_time, s.avg_stance_time_percent
        FROM activities a
        LEFT JOIN steps_activities s ON a.activity_id = s.activity_id
        WHERE a.start_time >= '{start_date}' AND s.avg_ground_contact_time IS NOT NULL
        ORDER BY a.start_time DESC
    """
    try:
        df = pd.read_sql_query(query, conn)
    except Exception as exc:
        raise LocalDatabaseReadError("biomechanics_query_failed") from exc
    finally:
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
    start_date = _window_start(days)
    conn = get_connection(GARMIN_DB)
    
    try:
        query = f"SELECT day, last_night_avg as hrv_avg, status FROM hrv WHERE day >= '{start_date}' ORDER BY day DESC"
        df = pd.read_sql_query(query, conn)
    except Exception as exc:
        raise LocalDatabaseReadError("hrv_query_failed") from exc
    finally:
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

def main():
    """Reject direct execution so callers cannot bypass the verified entrypoints."""
    print(
        json.dumps(
            {
                "status": "unsupported_entrypoint",
                "error_code": "use_verified_health_cli",
            },
            ensure_ascii=False,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
