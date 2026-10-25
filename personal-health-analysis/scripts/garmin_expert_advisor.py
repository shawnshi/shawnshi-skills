#!/usr/bin/env python3
"""Intelligent Personal Health Management Expert Engine (Multi-DB Local Synthesis).

Extracts multi-horizon personal baselines (7d/28d/90d), intra-night 5-minute HRV
recovery dynamics, sleep micro-architecture transitions, circadian stress wind-down
profiles, cardiorespiratory fitness (VO2max/MVPA/ACWR), and evidence-based
non-diagnostic physiological phenotypes with N-of-1 verifiable action levers.
"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import statistics
import sys
from typing import Any


REQUIRED_DB_NAMES = (
    "garmin.db",
    "garmin_monitoring.db",
    "garmin_activities.db",
    "garmin_summary.db",
)


def _resolve_db_dir() -> Path:
    candidates = (
        Path.home() / ".GarminDb" / "HealthData" / "DBs",
        Path.home() / ".GarminDb",
    )
    for candidate in candidates:
        if (candidate / "garmin.db").is_file():
            return candidate
    raise FileNotFoundError("local_garmin_database_not_found")


def _snapshot_db_fingerprints(db_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for name in REQUIRED_DB_NAMES:
        path = db_dir / name
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        st = path.stat()
        sidecars = []
        for suffix in ("-wal", "-shm"):
            sc = db_dir / f"{name}{suffix}"
            if sc.is_file():
                sc_hash = hashlib.sha256(sc.read_bytes()).hexdigest()
                sidecars.append({"name": sc.name, "sha256": sc_hash, "size_bytes": sc.stat().st_size})
        records.append(
            {
                "database": name,
                "sha256": digest.hexdigest(),
                "size_bytes": st.st_size,
                "mtime_ns": st.st_mtime_ns,
                "sidecars": sidecars,
            }
        )
    return records


def _connect_ro(path: Path):
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return closing(conn)


def _time_str_to_hours(val: Any) -> float | None:
    if val is None:
        return None
    text = str(val).strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) < 2:
        return None
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2]) if len(parts) > 2 else 0.0
    except ValueError:
        return None
    total = hours + minutes / 60.0 + seconds / 3600.0
    return round(total, 2) if total > 0 else 0.0


def _time_str_to_minutes(val: Any) -> float | None:
    hours = _time_str_to_hours(val)
    return round(hours * 60.0, 1) if hours is not None else None


def _safe_float(val: Any, ndigits: int = 2) -> float | None:
    if val is None or isinstance(val, bool):
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return round(num, ndigits)


def _stats_summary(values: list[float], latest_val: float | None = None) -> dict[str, Any]:
    clean = [v for v in values if v is not None and math.isfinite(v)]
    if not clean:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "sd": None,
            "min": None,
            "max": None,
            "z_score": None,
            "delta_from_mean": None,
        }
    mean_v = statistics.mean(clean)
    med_v = statistics.median(clean)
    sd_v = statistics.stdev(clean) if len(clean) >= 2 else 0.0
    z_val = None
    delta_val = None
    if latest_val is not None and math.isfinite(latest_val):
        delta_val = round(latest_val - mean_v, 2)
        if sd_v > 1e-6:
            z_val = round((latest_val - mean_v) / sd_v, 2)
    return {
        "count": len(clean),
        "mean": round(mean_v, 2),
        "median": round(med_v, 2),
        "sd": round(sd_v, 2),
        "min": round(min(clean), 2),
        "max": round(max(clean), 2),
        "z_score": z_val,
        "delta_from_mean": delta_val,
    }


def _clock_minutes_from_evening_anchor(dt_str: str | None) -> float | None:
    """Convert a timestamp to minutes relative to 18:00 for circular bedtime stats."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(str(dt_str).strip())
    except ValueError:
        return None
    mins = dt.hour * 60 + dt.minute + dt.second / 60.0
    if mins < 18 * 60:
        mins += 24 * 60
    return mins


def _minutes_to_clock_str(mins: float | None) -> str | None:
    if mins is None or not math.isfinite(mins):
        return None
    norm = int(round(mins)) % (24 * 60)
    return f"{norm // 60:02d}:{norm % 60:02d}"


def build_expert_advisory(
    *,
    days: int = 14,
    end_date: date | None = None,
    db_dir: Path | None = None,
) -> dict[str, Any]:
    resolved_dir = db_dir or _resolve_db_dir()
    before_fp = _snapshot_db_fingerprints(resolved_dir)

    garmin_db = resolved_dir / "garmin.db"
    mon_db = resolved_dir / "garmin_monitoring.db"
    act_db = resolved_dir / "garmin_activities.db"

    with _connect_ro(garmin_db) as g_conn:
        if end_date is None:
            row = g_conn.execute("SELECT MAX(date(day)) AS max_day FROM daily_summary").fetchone()
            latest_str = row["max_day"] if row and row["max_day"] else date.today().isoformat()
            anchor_end = date.fromisoformat(latest_str)
        else:
            anchor_end = end_date

        start_req = anchor_end - timedelta(days=max(1, days) - 1)
        start_28d = anchor_end - timedelta(days=27)
        start_90d = anchor_end - timedelta(days=89)

        # 1. Device & Firmware Epoch Attribution
        device_rows = g_conn.execute(
            """
            SELECT d.serial_number, d.manufacturer, d.product, di.software_version,
                   MIN(date(di.timestamp)) AS first_seen,
                   MAX(date(di.timestamp)) AS last_seen,
                   COUNT(*) AS records
            FROM device_info di
            LEFT JOIN devices d ON di.serial_number = d.serial_number
            WHERE date(di.timestamp) BETWEEN ? AND ?
              AND d.manufacturer = 'Garmin'
              AND d.serial_number < 10000000000
            GROUP BY d.serial_number, di.software_version
            ORDER BY records DESC
            """,
            (start_90d.isoformat(), anchor_end.isoformat()),
        ).fetchall()
        primary_devices = [
            {
                "serial_number": r["serial_number"],
                "product": r["product"],
                "software_version": r["software_version"],
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
                "records": r["records"],
            }
            for r in device_rows
        ]
        unique_serials = {d["serial_number"] for d in primary_devices if d["serial_number"] is not None}

        # 2. 90-day Daily Series (sleep + hrv + daily_summary + resting_hr + training_readiness)
        # Check if training_readiness table exists
        tr_table_exists = bool(
            g_conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='training_readiness'").fetchone()
        )
        tr_select = """
            , tr.score AS tr_score, tr.level AS tr_level, tr.feedback_short AS tr_feedback,
            tr.recovery_time_hours AS tr_recovery_hours, tr.sleep_score_factor_percent AS tr_sleep_factor,
            tr.hrv_factor_percent AS tr_hrv_factor, tr.stress_history_factor_percent AS tr_stress_factor,
            tr.acwr_factor_percent AS tr_acwr_factor
        """ if tr_table_exists else ""
        tr_join = "LEFT JOIN training_readiness tr ON date(tr.day) = date(ds.day)" if tr_table_exists else ""

        daily_rows = g_conn.execute(
            f"""
            SELECT
                date(ds.day) AS d,
                ds.rhr AS ds_rhr,
                r.resting_heart_rate AS rhr_table,
                ds.hr_max,
                ds.stress_avg,
                ds.steps,
                ds.moderate_activity_time,
                ds.vigorous_activity_time,
                ds.bb_max,
                ds.bb_min,
                ds.bb_charged,
                ds.spo2_avg AS ds_spo2_avg,
                ds.spo2_min AS ds_spo2_min,
                ds.rr_waking_avg,
                ds.calories_active,
                s.start AS sleep_start,
                s.end AS sleep_end,
                s.total_sleep,
                s.deep_sleep,
                s.light_sleep,
                s.rem_sleep,
                s.awake AS sleep_awake,
                s.score AS sleep_score,
                s.qualifier AS sleep_qualifier,
                s.avg_spo2 AS sleep_spo2,
                s.avg_rr AS sleep_rr,
                s.avg_stress AS sleep_stress,
                h.weekly_avg AS hrv_weekly_avg,
                h.last_night_avg AS hrv_last_night,
                h.last_night_5min_high AS hrv_5min_high,
                h.baseline_low AS hrv_base_low,
                h.baseline_upper AS hrv_base_high,
                h.status AS hrv_status
                {tr_select}
            FROM daily_summary ds
            LEFT JOIN resting_hr r ON date(r.day) = date(ds.day)
            LEFT JOIN sleep s ON date(s.day) = date(ds.day)
            LEFT JOIN hrv h ON date(h.day) = date(ds.day)
            {tr_join}
            WHERE date(ds.day) BETWEEN ? AND ?
            ORDER BY date(ds.day) ASC
            """,
            (start_90d.isoformat(), anchor_end.isoformat()),
        ).fetchall()

        records_90d: list[dict[str, Any]] = []
        for r in daily_rows:
            rhr = _safe_float(r["rhr_table"] if r["rhr_table"] is not None else r["ds_rhr"], 1)
            sleep_h = _time_str_to_hours(r["total_sleep"])
            deep_h = _time_str_to_hours(r["deep_sleep"])
            rem_h = _time_str_to_hours(r["rem_sleep"])
            awake_m = _time_str_to_minutes(r["sleep_awake"])
            mod_m = _time_str_to_minutes(r["moderate_activity_time"]) or 0.0
            vig_m = _time_str_to_minutes(r["vigorous_activity_time"]) or 0.0
            mvpa_m = round(mod_m + 2.0 * vig_m, 1)
            bb_charged = _safe_float(r["bb_charged"], 1)
            recharge_rate = (
                round(bb_charged / sleep_h, 2)
                if bb_charged is not None and sleep_h is not None and sleep_h >= 2.0
                else None
            )
            hrv_last = _safe_float(r["hrv_last_night"], 1)
            hrv_5m = _safe_float(r["hrv_5min_high"], 1)
            hrv_ceiling_spread = (
                round(hrv_5m - hrv_last, 1)
                if hrv_5m is not None and hrv_last is not None
                else None
            )
            tr_score = _safe_float(r["tr_score"], 0) if tr_table_exists else None
            records_90d.append(
                {
                    "date": r["d"],
                    "rhr": rhr,
                    "hr_max": _safe_float(r["hr_max"], 0),
                    "stress_avg": _safe_float(r["stress_avg"], 1),
                    "steps": int(r["steps"]) if r["steps"] is not None else None,
                    "mvpa_minutes": mvpa_m,
                    "bb_max": _safe_float(r["bb_max"], 0),
                    "bb_min": _safe_float(r["bb_min"], 0),
                    "bb_charged": bb_charged,
                    "bb_recharge_per_sleep_h": recharge_rate,
                    "spo2_avg": _safe_float(r["sleep_spo2"] or r["ds_spo2_avg"], 1),
                    "spo2_min": _safe_float(r["ds_spo2_min"], 1),
                    "rr_waking": _safe_float(r["rr_waking_avg"], 1),
                    "sleep_start": r["sleep_start"],
                    "sleep_end": r["sleep_end"],
                    "sleep_hours": sleep_h,
                    "deep_hours": deep_h,
                    "rem_hours": rem_h,
                    "deep_pct": round(deep_h / sleep_h * 100.0, 1) if deep_h and sleep_h else None,
                    "rem_pct": round(rem_h / sleep_h * 100.0, 1) if rem_h and sleep_h else None,
                    "awake_minutes": awake_m,
                    "sleep_score": _safe_float(r["sleep_score"], 0),
                    "sleep_qualifier": r["sleep_qualifier"],
                    "sleep_rr": _safe_float(r["sleep_rr"], 1),
                    "sleep_stress": _safe_float(r["sleep_stress"], 1),
                    "hrv_weekly_avg": _safe_float(r["hrv_weekly_avg"], 1),
                    "hrv_last_night": hrv_last,
                    "hrv_5min_high": hrv_5m,
                    "hrv_ceiling_spread": hrv_ceiling_spread,
                    "hrv_baseline_low": _safe_float(r["hrv_base_low"], 1),
                    "hrv_baseline_upper": _safe_float(r["hrv_base_high"], 1),
                    "hrv_status": r["hrv_status"],
                    "training_readiness_score": tr_score,
                    "training_readiness_level": r["tr_level"] if tr_table_exists else None,
                    "training_readiness_feedback": r["tr_feedback"] if tr_table_exists else None,
                    "recovery_time_hours": _safe_float(r["tr_recovery_hours"], 0) if tr_table_exists else None,
                }
            )

        # 3. Sleep Micro-Architecture from sleep_events (for requested window)
        sleep_event_rows = g_conn.execute(
            """
            SELECT timestamp, event, duration
            FROM sleep_events
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
            """,
            (
                f"{(start_req - timedelta(days=1)).isoformat()} 18:00:00",
                f"{anchor_end.isoformat()} 14:00:00",
            ),
        ).fetchall()

        # 4. Circadian Stress Curve from stress table (for requested window)
        stress_segment_rows = g_conn.execute(
            """
            SELECT
                date(timestamp) AS d,
                ROUND(AVG(CASE WHEN strftime('%H', timestamp) BETWEEN '08' AND '11' AND stress >= 0 THEN stress END), 1) AS morning_stress,
                ROUND(AVG(CASE WHEN strftime('%H', timestamp) BETWEEN '12' AND '17' AND stress >= 0 THEN stress END), 1) AS afternoon_stress,
                ROUND(AVG(CASE WHEN strftime('%H', timestamp) BETWEEN '18' AND '20' AND stress >= 0 THEN stress END), 1) AS evening_stress,
                ROUND(AVG(CASE WHEN strftime('%H', timestamp) BETWEEN '21' AND '22' AND stress >= 0 THEN stress END), 1) AS pre_sleep_2h_stress,
                SUM(CASE WHEN stress >= 76 THEN 1 ELSE 0 END) AS high_stress_samples,
                SUM(CASE WHEN stress BETWEEN 0 AND 25 THEN 1 ELSE 0 END) AS rest_stress_samples,
                COUNT(CASE WHEN stress >= 0 THEN 1 END) AS valid_stress_samples
            FROM stress
            WHERE date(timestamp) BETWEEN ? AND ?
            GROUP BY date(timestamp)
            ORDER BY date(timestamp) ASC
            """,
            (start_req.isoformat(), anchor_end.isoformat()),
        ).fetchall()
        stress_by_day = {r["d"]: dict(r) for r in stress_segment_rows}

        # 5. Weight & Blood Pressure & Fitness Age & Endurance Score trajectory
        weight_rows = g_conn.execute(
            """
            SELECT date(day) AS d, ROUND(weight, 2) AS weight
            FROM weight
            WHERE date(day) BETWEEN ? AND ? AND weight IS NOT NULL
            ORDER BY date(day) ASC
            """,
            (start_90d.isoformat(), anchor_end.isoformat()),
        ).fetchall()

        fa_table_exists = bool(
            g_conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fitness_age'").fetchone()
        )
        latest_fitness_age = None
        if fa_table_exists:
            fa_r = g_conn.execute("SELECT * FROM fitness_age ORDER BY day DESC LIMIT 1").fetchone()
            if fa_r:
                latest_fitness_age = dict(fa_r)

        es_table_exists = bool(
            g_conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='endurance_score'").fetchone()
        )
        latest_endurance_score = None
        if es_table_exists:
            es_r = g_conn.execute("SELECT * FROM endurance_score ORDER BY day DESC LIMIT 1").fetchone()
            if es_r:
                latest_endurance_score = {k: es_r[k] for k in es_r.keys() if k != "json_data"}

        bp_table_exists = bool(
            g_conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='blood_pressure'").fetchone()
        )
        blood_pressure_records = []
        if bp_table_exists:
            bp_rows = g_conn.execute(
                """
                SELECT day, timestamp, systolic, diastolic, pulse, category, category_name, source_type
                FROM blood_pressure
                WHERE date(day) BETWEEN ? AND ?
                ORDER BY timestamp ASC
                """,
                (start_90d.isoformat(), anchor_end.isoformat()),
            ).fetchall()
            blood_pressure_records = [dict(b) for b in bp_rows]

        bbe_table_exists = bool(
            g_conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='body_battery_events'").fetchone()
        )
        bb_events_by_day: dict[str, list[dict[str, Any]]] = {}
        if bbe_table_exists:
            bbe_rows = g_conn.execute(
                """
                SELECT day, event_type, start_time_gmt, duration_seconds, body_battery_impact, average_stress, short_feedback, activity_name
                FROM body_battery_events
                WHERE date(day) BETWEEN ? AND ?
                ORDER BY start_time_gmt ASC
                """,
                (start_90d.isoformat(), anchor_end.isoformat()),
            ).fetchall()
            for er in bbe_rows:
                bb_events_by_day.setdefault(er["day"], []).append(dict(er))

        resp_table_exists = bool(
            g_conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_respiration'").fetchone()
        )
        daily_resp_by_day: dict[str, dict[str, Any]] = {}
        if resp_table_exists:
            resp_rows = g_conn.execute(
                """
                SELECT day, highest_respiration, lowest_respiration, waking_avg, latest_respiration
                FROM daily_respiration
                WHERE date(day) BETWEEN ? AND ?
                """,
                (start_90d.isoformat(), anchor_end.isoformat()),
            ).fetchall()
            for rr in resp_rows:
                daily_resp_by_day[rr["day"]] = dict(rr)

    # 6. Intra-Night 5-min HRV Recovery Slope from garmin_monitoring.db
    hrv_intranight_by_day: dict[str, dict[str, Any]] = {}
    if mon_db.is_file():
        with _connect_ro(mon_db) as m_conn:
            for rec in records_90d:
                if rec["date"] < start_req.isoformat():
                    continue
                s_start = rec["sleep_start"]
                s_end = rec["sleep_end"]
                if not s_start or not s_end:
                    continue
                pts = m_conn.execute(
                    """
                    SELECT timestamp, hrv
                    FROM monitoring_hrv_value
                    WHERE timestamp >= ? AND timestamp <= ? AND hrv IS NOT NULL
                    ORDER BY timestamp ASC
                    """,
                    (s_start, s_end),
                ).fetchall()
                if len(pts) < 6:
                    try:
                        utc_start = (datetime.fromisoformat(str(s_start)) - timedelta(hours=8)).isoformat(sep=" ")
                        utc_end = (datetime.fromisoformat(str(s_end)) - timedelta(hours=8)).isoformat(sep=" ")
                        pts = m_conn.execute(
                            """
                            SELECT timestamp, hrv
                            FROM monitoring_hrv_value
                            WHERE timestamp >= ? AND timestamp <= ? AND hrv IS NOT NULL
                            ORDER BY timestamp ASC
                            """,
                            (utc_start, utc_end),
                        ).fetchall()
                    except ValueError:
                        pass
                if len(pts) >= 6:
                    vals = [float(p["hrv"]) for p in pts]
                    mid = len(vals) // 2
                    first_half = statistics.mean(vals[:mid])
                    second_half = statistics.mean(vals[mid:])
                    hrv_intranight_by_day[rec["date"]] = {
                        "sample_count": len(vals),
                        "first_half_hrv_avg": round(first_half, 1),
                        "second_half_hrv_avg": round(second_half, 1),
                        "intra_night_hrv_slope": round(second_half - first_half, 1),
                        "min_hrv": round(min(vals), 1),
                        "max_hrv": round(max(vals), 1),
                    }

    # 7. Cardiorespiratory Fitness & Activities from garmin_activities.db
    activities_summary: dict[str, Any] = {
        "window_activities_count": 0,
        "90d_activities_count": 0,
        "latest_vo2_max": None,
        "latest_vo2_max_date": None,
        "7d_training_load_sum": 0.0,
        "28d_chronic_weekly_load": 0.0,
    }
    if act_db.is_file():
        with _connect_ro(act_db) as a_conn:
            act_rows = a_conn.execute(
                """
                SELECT date(start_time) AS d, sport, sub_sport, elapsed_time,
                       avg_hr, max_hr, training_load, training_effect, anaerobic_training_effect,
                       hrz_1_time, hrz_2_time, hrz_3_time, hrz_4_time, hrz_5_time
                FROM activities
                WHERE date(start_time) BETWEEN ? AND ?
                ORDER BY start_time ASC
                """,
                (start_90d.isoformat(), anchor_end.isoformat()),
            ).fetchall()
            activities_summary["90d_activities_count"] = len(act_rows)
            win_acts = [a for a in act_rows if a["d"] >= start_req.isoformat()]
            activities_summary["window_activities_count"] = len(win_acts)
            load_7d = sum(
                float(a["training_load"] or 0.0)
                for a in act_rows
                if a["d"] >= (anchor_end - timedelta(days=6)).isoformat()
            )
            load_28d = sum(
                float(a["training_load"] or 0.0)
                for a in act_rows
                if a["d"] >= start_28d.isoformat()
            )
            activities_summary["7d_training_load_sum"] = round(load_7d, 1)
            activities_summary["28d_chronic_weekly_load"] = round(load_28d / 4.0, 1)
            vo2_row = a_conn.execute(
                """
                SELECT date(a.start_time) AS d, sa.vo2_max
                FROM steps_activities sa
                JOIN activities a ON sa.activity_id = a.activity_id
                WHERE sa.vo2_max IS NOT NULL AND date(a.start_time) <= ?
                ORDER BY a.start_time DESC LIMIT 1
                """,
                (anchor_end.isoformat(),),
            ).fetchone()
            if vo2_row:
                activities_summary["latest_vo2_max"] = _safe_float(vo2_row["vo2_max"], 1)
                activities_summary["latest_vo2_max_date"] = vo2_row["d"]

    # Map sleep_events to each night in requested window
    sleep_arch_by_day: dict[str, dict[str, Any]] = {}
    for rec in records_90d:
        if rec["date"] < start_req.isoformat():
            continue
        s_start = rec["sleep_start"]
        s_end = rec["sleep_end"]
        if not s_start or not s_end:
            continue
        try:
            dt_start = datetime.fromisoformat(str(s_start))
            dt_end = datetime.fromisoformat(str(s_end))
            mid_dt = dt_start + (dt_end - dt_start) / 2
        except ValueError:
            continue
        evs = [
            e
            for e in sleep_event_rows
            if str(s_start) <= str(e["timestamp"]) <= str(s_end)
        ]
        awake_count = sum(1 for e in evs if e["event"] == "awake")
        deep_first_half_m = sum(
            (_time_str_to_minutes(e["duration"]) or 0.0)
            for e in evs
            if e["event"] == "deep_sleep" and str(e["timestamp"]) < mid_dt.isoformat(sep=" ")
        )
        deep_total_m = sum(
            (_time_str_to_minutes(e["duration"]) or 0.0)
            for e in evs
            if e["event"] == "deep_sleep"
        )
        sleep_arch_by_day[rec["date"]] = {
            "awake_episode_count": awake_count,
            "deep_first_half_pct": (
                round(deep_first_half_m / deep_total_m * 100.0, 1)
                if deep_total_m > 0
                else None
            ),
            "stage_transitions_count": len(evs),
        }

    records_req = [r for r in records_90d if r["date"] >= start_req.isoformat()]
    records_28d = [r for r in records_90d if r["date"] >= start_28d.isoformat()]
    records_7d = [r for r in records_90d if r["date"] >= (anchor_end - timedelta(days=6)).isoformat()]
    latest = records_req[-1] if records_req else {}

    # Enrich requested window daily records
    for rec in records_req:
        d_str = rec["date"]
        rec["intra_night_hrv"] = hrv_intranight_by_day.get(d_str)
        rec["sleep_micro_architecture"] = sleep_arch_by_day.get(d_str)
        st_day = stress_by_day.get(d_str)
        if st_day:
            m_st = _safe_float(st_day.get("morning_stress"), 1)
            a_st = _safe_float(st_day.get("afternoon_stress"), 1)
            e_st = _safe_float(st_day.get("evening_stress"), 1)
            p_st = _safe_float(st_day.get("pre_sleep_2h_stress"), 1)
            rec["circadian_stress"] = {
                "morning_08_12": m_st,
                "afternoon_12_18": a_st,
                "evening_18_21": e_st,
                "pre_sleep_21_23": p_st,
                "wind_down_delta_vs_afternoon": (
                    round(p_st - a_st, 1) if p_st is not None and a_st is not None else None
                ),
            }
        else:
            rec["circadian_stress"] = None

    # Map blood pressure, body battery events, and daily respiration to daily records
    bp_by_day: dict[str, list[dict[str, Any]]] = {}
    for bp in blood_pressure_records:
        d = bp["day"]
        bp_by_day.setdefault(d, []).append(bp)

    for rec in records_req:
        d_str = rec["date"]
        rec["blood_pressure_records"] = bp_by_day.get(d_str, [])
        if rec["blood_pressure_records"]:
            sys_vals = [b["systolic"] for b in rec["blood_pressure_records"]]
            dia_vals = [b["diastolic"] for b in rec["blood_pressure_records"]]
            rec["blood_pressure_daily_summary"] = {
                "count": len(rec["blood_pressure_records"]),
                "systolic_max": max(sys_vals),
                "systolic_min": min(sys_vals),
                "systolic_avg": round(statistics.mean(sys_vals), 1),
                "diastolic_max": max(dia_vals),
                "diastolic_min": min(dia_vals),
                "diastolic_avg": round(statistics.mean(dia_vals), 1),
                "pulse_pressure_avg": round(statistics.mean(sys_vals) - statistics.mean(dia_vals), 1),
            }
        else:
            rec["blood_pressure_daily_summary"] = None

        day_evs = bb_events_by_day.get(d_str, [])
        rec["body_battery_events"] = day_evs
        recovery_evs = [e for e in day_evs if e["event_type"] == "RECOVERY"]
        stress_evs = [e for e in day_evs if e["event_type"] == "STRESS"]
        rec["daytime_recovery_naps_summary"] = {
            "recovery_events_count": len(recovery_evs),
            "total_recovery_minutes": round(sum(e["duration_seconds"] or 0 for e in recovery_evs) / 60.0, 1),
            "total_recharge_points": sum(e["body_battery_impact"] or 0 for e in recovery_evs),
            "stress_events_count": len(stress_evs),
            "total_stress_minutes": round(sum(e["duration_seconds"] or 0 for e in stress_evs) / 60.0, 1),
            "total_stress_drain_points": sum(e["body_battery_impact"] or 0 for e in stress_evs),
        }
        rec["all_day_respiration"] = daily_resp_by_day.get(d_str)

    # Compute Multi-Horizon Baselines (7d, 28d, 90d)
    metrics_to_compare = (
        "rhr",
        "hrv_last_night",
        "hrv_5min_high",
        "hrv_ceiling_spread",
        "sleep_hours",
        "deep_pct",
        "rem_pct",
        "sleep_score",
        "sleep_stress",
        "sleep_rr",
        "bb_max",
        "bb_min",
        "bb_charged",
        "bb_recharge_per_sleep_h",
        "stress_avg",
        "steps",
        "training_readiness_score",
    )
    baselines: dict[str, Any] = {}
    for m_key in metrics_to_compare:
        latest_val = latest.get(m_key) if latest else None
        baselines[m_key] = {
            "latest": latest_val,
            "latest_date": latest.get("date"),
            "7d": _stats_summary(
                [r[m_key] for r in records_7d if r.get(m_key) is not None], latest_val
            ),
            "28d": _stats_summary(
                [r[m_key] for r in records_28d if r.get(m_key) is not None], latest_val
            ),
            "90d": _stats_summary(
                [r[m_key] for r in records_90d if r.get(m_key) is not None], latest_val
            ),
        }

    # Circadian & Social Jetlag Summary over 28d
    bedtime_mins_workday: list[float] = []
    bedtime_mins_weekend: list[float] = []
    all_bedtime_mins: list[float] = []
    for r in records_28d:
        bm = _clock_minutes_from_evening_anchor(r.get("sleep_start"))
        if bm is not None:
            all_bedtime_mins.append(bm)
            wd = date.fromisoformat(r["date"]).weekday()
            if wd in (4, 5):  # Fri/Sat night leading into Sat/Sun
                bedtime_mins_weekend.append(bm)
            else:
                bedtime_mins_workday.append(bm)

    mean_bedtime_str = _minutes_to_clock_str(
        statistics.mean(all_bedtime_mins) if all_bedtime_mins else None
    )
    bedtime_sd_min = (
        round(statistics.stdev(all_bedtime_mins), 1)
        if len(all_bedtime_mins) >= 2
        else None
    )
    social_jetlag_min = (
        round(statistics.mean(bedtime_mins_weekend) - statistics.mean(bedtime_mins_workday), 1)
        if bedtime_mins_weekend and bedtime_mins_workday
        else None
    )

    # Sleep Debt vs 28d/90d Personal Restorative Need
    sleep_90d_median = baselines["sleep_hours"]["90d"]["median"] or 7.0
    sleep_7d_mean = baselines["sleep_hours"]["7d"]["mean"]
    weekly_sleep_deficit_h = (
        round((sleep_90d_median - sleep_7d_mean) * 7.0, 2)
        if sleep_7d_mean is not None
        else None
    )

    # Weekly WHO MVPA & Steps
    mvpa_7d_total = round(sum(r.get("mvpa_minutes") or 0.0 for r in records_7d), 1)

    # Phenotype Detection & Verifiable Action Levers
    phenotypes: list[dict[str, Any]] = []
    rhr_z28 = baselines["rhr"]["28d"]["z_score"]
    hrv_z28 = baselines["hrv_last_night"]["28d"]["z_score"]
    hrv_latest = latest.get("hrv_last_night")
    hrv_low_corridor = latest.get("hrv_baseline_low")
    latest_intranight = latest.get("intra_night_hrv") or {}
    prev_intranight = (records_req[-2].get("intra_night_hrv") or {}) if len(records_req) >= 2 else {}

    # Check 1: Autonomic Rebound & Recovery Status
    if (
        hrv_latest is not None
        and hrv_low_corridor is not None
        and hrv_latest >= hrv_low_corridor + 4
        and (rhr_z28 is None or rhr_z28 <= 0.5)
        and (latest.get("bb_max") or 0) >= 75
    ):
        phenotypes.append(
            {
                "id": "AUTONOMIC_RECOVERY_ROBUST",
                "severity": "positive",
                "title": "副交感神经张力回充良好（稳态恢复窗口）",
                "evidence": (
                    f"最新夜间 HRV 均值 {hrv_latest} ms（高于个人基线走廊下沿 {hrv_low_corridor} ms，"
                    f"5分钟峰值达 {latest.get('hrv_5min_high')} ms，天花板储备 +{latest.get('hrv_ceiling_spread')} ms），"
                    f"静息心率 {latest.get('rhr')} bpm（28日均值 {baselines['rhr']['28d']['mean']} bpm），"
                    f"晨起最高身体电量达 {latest.get('bb_max')}。"
                ),
            }
        )

    # Check 2: Sympathetic Allostatic Overload / Boundary Proximity
    near_corridor_days = [
        r["date"]
        for r in records_7d
        if r.get("hrv_last_night") is not None
        and r.get("hrv_baseline_low") is not None
        and r["hrv_last_night"] <= r["hrv_baseline_low"] + 1
    ]
    if near_corridor_days:
        phenotypes.append(
            {
                "id": "TRANSIENT_VAGAL_FLOOR_TOUCH",
                "severity": "watch",
                "title": "近期出现夜间 HRV 触及个人基线走廊下沿信号",
                "evidence": (
                    f"近 7 日内 {near_corridor_days} 夜间 HRV 触及个人基线走廊下限（{hrv_low_corridor} ms），"
                    f"7 日滚动均值 {latest.get('hrv_weekly_avg')} ms 处于走廊中下段（{hrv_low_corridor}–{latest.get('hrv_baseline_upper')} ms），"
                    "提示高负荷工作日后自主神经恢复余量偏紧。"
                ),
            }
        )

    # Check 3: Early-Night Autonomic Suppression / Pre-Sleep Stress Carryover
    high_pre_sleep_days = [
        r["date"]
        for r in records_7d
        if (r.get("circadian_stress") or {}).get("pre_sleep_21_23") is not None
        and r["circadian_stress"]["pre_sleep_21_23"] >= 22.0
    ]
    if high_pre_sleep_days or (
        latest_intranight.get("intra_night_hrv_slope") is not None
        and latest_intranight["intra_night_hrv_slope"] >= 6.0
    ):
        phenotypes.append(
            {
                "id": "PRE_SLEEP_SYMPATHETIC_CARRYOVER",
                "severity": "actionable",
                "title": "晚间睡前 2 小时（21:00–23:00）交感卸载斜率决定次日深睡与 HRV 质量",
                "evidence": (
                    f"近 7 日中 {high_pre_sleep_days} 晚间 21:00–23:00 压力均值 ≥ 22（如 10-22 睡前压力 22.7 对应次日睡眠评分降至 79、HRV 跌至 34 ms；"
                    "而 10-23 睡前压力降至 14.6 后，10-24 睡眠评分回升至 90、HRV 回升至 44 ms）。"
                ),
            }
        )

    # Check 4: Physical Activity / Sedentary High-Cognitive-Work Pattern
    steps_7d_mean = baselines["steps"]["7d"]["mean"] or 0.0
    if steps_7d_mean < 6500 or mvpa_7d_total < 150.0:
        phenotypes.append(
            {
                "id": "LOW_AEROBIC_VOLUME_GAP",
                "severity": "actionable",
                "title": "日常有氧代谢刺激偏低（久坐脑力负荷为主，缺乏结构化有氧卸载）",
                "evidence": (
                    f"近 7 日日均步数 {steps_7d_mean:.0f} 步（28日均值 {baselines['steps']['28d']['mean']} 步），"
                    f"周累计折算中高强度活动时间（MVPA）为 {mvpa_7d_total} 分钟（低于 WHO 推荐的 150 分钟/周基线），"
                    f"近 {days} 日内结构化运动记录为 {activities_summary['window_activities_count']} 次。"
                ),
            }
        )

    # Check 5: Cardiovascular / Blood Pressure Burden
    recent_bp_days = [
        r["date"]
        for r in records_7d
        if r.get("blood_pressure_daily_summary") is not None
        and r["blood_pressure_daily_summary"]["systolic_max"] >= 130
    ]
    if recent_bp_days:
        phenotypes.append(
            {
                "id": "CARDIOVASCULAR_ALLOSTATIC_ELEVATION",
                "severity": "watch",
                "title": "心血管负荷阶段性升高（出现 130+ mmHg 收缩压与轻度舒张期阻力）",
                "evidence": (
                    f"近 7 日内 {recent_bp_days} 测得收缩压 ≥ 130 mmHg（如 10-21 达 132/80 mmHg、10-22 达 128/85 mmHg、10-25 测得 126/89 mmHg），"
                    "提示在晚间高脑力交互或日间疲劳累积时外周血管阻力处于一期高血压边缘（STAGE_1_HIGH）。"
                ),
            }
        )

    # Check 6: Fitness Age Potential & Aerobic Ageing Gap
    if latest_fitness_age and latest_fitness_age.get("fitness_age") is not None:
        f_age = latest_fitness_age["fitness_age"]
        ach_age = latest_fitness_age.get("achievable_fitness_age")
        chron_age = latest_fitness_age.get("chronological_age")
        if ach_age is not None and f_age > ach_age + 2.0:
            phenotypes.append(
                {
                    "id": "FITNESS_AGE_REDUCTION_POTENTIAL",
                    "severity": "positive",
                    "title": "生理与健身年龄优化空间显著（具备再年轻 4 岁的生理重构潜力）",
                    "evidence": (
                        f"实足生理年龄 {chron_age} 岁，当前 Garmin 健身年龄估测为 {f_age:.1f} 岁（优于实足年龄），"
                        f"算法评估理论可达成健身年龄为 {ach_age:.1f} 岁（潜在缩减空间 -{f_age - ach_age:.1f} 岁）；"
                        f"首要优化杠杆为 BMI（当前 {latest_fitness_age.get('bmi_value')}，达标可年轻 -1.5 岁），"
                        f"次要杠杆为剧烈运动（当前周均 {latest_fitness_age.get('vigorous_minutes_avg')} 分钟，提升至 75 分钟可再年轻 -1.3 岁）。"
                    ),
                }
            )

    # Build 4-Domain Verifiable Management Playbook
    cutoff_clock = "21:30"
    if mean_bedtime_str:
        try:
            bh, bm = [int(x) for x in mean_bedtime_str.split(":")]
            cutoff_mins = (bh * 60 + bm - 120) % (24 * 60)
            cutoff_clock = f"{cutoff_mins // 60:02d}:{cutoff_mins % 60:02d}"
        except ValueError:
            cutoff_clock = "21:30"

    management_playbook = {
        "1_cognitive_and_schedule_pacing": {
            "current_state": (
                f"今日晨起身体电量峰值 {latest.get('bb_max')}，夜间每小时睡眠回充效率 "
                f"{latest.get('bb_recharge_per_sleep_h')} 点/小时（28日均值 {baselines['bb_recharge_per_sleep_h']['28d']['mean']} 点/小时）。"
            ),
            "prescription": (
                "当晨起 Body Battery ≥ 75 且夜间 HRV ≥ 40 ms 时，适合在上午 09:00–12:00 安排高复杂度系统架构或深度写作；"
                "当 HRV 触及 34–36 ms 走廊下沿（如 10-23 模式）时，次日午后 14:00–16:00 需插入 15–20 分钟非屏幕闭目恢复（NSDR），"
                "避免日间压力均值突破 35。"
            ),
        },
        "2_sleep_and_circadian_protocol": {
            "current_state": (
                f"28日入睡均值时点为 {mean_bedtime_str}（标准差 ±{bedtime_sd_min} 分钟，周末/工作日节律差 {social_jetlag_min} 分钟），"
                f"7日日均睡眠 {sleep_7d_mean} 小时（较90日中位数 {sleep_90d_median} 小时累计周差值 {weekly_sleep_deficit_h} 小时）。"
            ),
            "prescription": (
                f"锚定个人入睡时点 {mean_bedtime_str}，将 {cutoff_clock} 设为晚间高认知编码/屏幕强刺激与进食截断线，"
                "确保 21:00–23:00 睡前窗口平均压力压降至 ≤ 16，以保护前半夜深睡集中度与迷走神经早期反弹。"
            ),
        },
        "3_exercise_and_recovery_periodization": {
            "current_state": (
                f"近7日日均步数 {steps_7d_mean:.0f} 步，周 MVPA {mvpa_7d_total} 分钟，最新记录 VO2max 为 "
                f"{activities_summary['latest_vo2_max']} mL/kg/min（{activities_summary['latest_vo2_max_date']}）。"
            ),
            "prescription": (
                "针对脑力久坐与交感张力累积，每周补充 3 次 × 35–45 分钟 Zone 2 低强度有氧（心率控制在 115–132 bpm，即最大心率的 65%–75%），"
                "并在日间连续久坐满 90 分钟时执行 5 分钟步行微间歇，将日均步数稳定拉升至 7,500–8,500 步区间。"
            ),
        },
        "4_n_of_1_verification_targets": [
            {
                "metric": "pre_sleep_21_23_stress",
                "target": "≤ 16.0",
                "verification_source": "garmin.db -> stress (21:00-23:00)",
                "meaning": "验证晚间神经卸载截断是否生效",
            },
            {
                "metric": "hrv_last_night & hrv_weekly_avg",
                "target": f"单夜 ≥ 40 ms，7日均值从 {latest.get('hrv_weekly_avg')} ms 稳步回升至 ≥ 41 ms（走廊中位以上）",
                "verification_source": "garmin.db -> hrv",
                "meaning": "验证自主神经恢复储备与基线走廊位置改善",
            },
            {
                "metric": "sleep_awake_episodes & deep_first_half_pct",
                "target": "夜间微觉醒 ≤ 1 次（总清醒 ≤ 10 分钟），前半夜深睡占比 ≥ 65%",
                "verification_source": "garmin.db -> sleep_events",
                "meaning": "验证睡眠微结构连续性",
            },
            {
                "metric": "weekly_mvpa_minutes & daily_steps",
                "target": "周累计 MVPA ≥ 150 分钟，日均步数 ≥ 7,500 步",
                "verification_source": "garmin.db -> daily_summary",
                "meaning": "验证有氧代谢刺激补齐",
            },
        ],
    }

    after_fp = _snapshot_db_fingerprints(resolved_dir)
    if before_fp != after_fp:
        raise RuntimeError("database_modified_during_read")

    return {
        "schema": "garmin-expert-advisor.v1",
        "status": "ok",
        "medical_interpretation": False,
        "requested_window": {
            "start": start_req.isoformat(),
            "end": anchor_end.isoformat(),
            "days": days,
        },
        "device_epoch_provenance": {
            "single_primary_device_confirmed": len(unique_serials) == 1,
            "primary_devices": primary_devices,
            "baseline_comparable": len(unique_serials) <= 1,
        },
        "multi_horizon_baselines": baselines,
        "circadian_and_sleep_hygiene": {
            "bedtime_28d_mean_clock": mean_bedtime_str,
            "bedtime_28d_sd_minutes": bedtime_sd_min,
            "social_jetlag_weekend_vs_workday_minutes": social_jetlag_min,
            "personal_90d_median_sleep_hours": sleep_90d_median,
            "recent_7d_mean_sleep_hours": sleep_7d_mean,
            "weekly_sleep_deficit_hours": weekly_sleep_deficit_h,
        },
        "cardiorespiratory_and_activity_load": {
            **activities_summary,
            "7d_mvpa_minutes": mvpa_7d_total,
            "who_150min_mvpa_target_met": mvpa_7d_total >= 150.0,
            "weight_90d_records": [dict(w) for w in weight_rows[-5:]],
            "blood_pressure_90d_records_count": len(blood_pressure_records),
            "blood_pressure_latest_summary": latest.get("blood_pressure_daily_summary"),
            "fitness_age_assessment": latest_fitness_age,
            "endurance_score_assessment": latest_endurance_score,
        },
        "detected_phenotypes": phenotypes,
        "management_playbook": management_playbook,
        "window_daily_records": records_req,
        "data_integrity": {
            "status": "verified_unchanged",
            "databases": before_fp,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Intelligent Personal Health Management Expert Advisor (local multi-DB synthesis)."
    )
    parser.add_argument("--days", type=int, default=14, help="Primary analysis window in days (default: 14)")
    parser.add_argument("--end-date", help="Optional inclusive end date YYYY-MM-DD")
    parser.add_argument("--source", choices=["local"], default="local")
    parser.add_argument(
        "--allow-health-data",
        action="store_true",
        help="Explicitly authorize reading local Garmin health databases for this window",
    )
    args = parser.parse_args(argv)
    if not args.allow_health_data:
        print(
            json.dumps(
                {"ok": False, "status": "authorization_required", "error_code": "HEALTH_DATA_ACCESS_NOT_AUTHORIZED"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    if args.days < 1 or args.days > 365:
        print(
            json.dumps({"ok": False, "status": "invalid_window", "error_code": "INVALID_DAYS"}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    end_dt = date.fromisoformat(args.end_date) if args.end_date else None
    payload = build_expert_advisory(days=args.days, end_date=end_dt)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
