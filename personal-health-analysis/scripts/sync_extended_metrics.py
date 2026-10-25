#!/usr/bin/env python3
"""Sync extended Garmin metrics (Blood Pressure & Training Readiness) into local SQLite."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import garmin_auth
from garmin_capabilities import consume_capability, issue_capability, require_capability

SYNC_EXTENDED_OPERATION = "garmin_extended_sync"
EXTENDED_METRICS = (
    "blood_pressure",
    "training_readiness",
    "fitness_age",
    "endurance_score",
    "body_battery_events",
    "daily_respiration",
)


def _resolve_garmin_db_path() -> Path:
    candidates = (
        Path.home() / ".GarminDb" / "HealthData" / "DBs" / "garmin.db",
        Path.home() / ".GarminDb" / "garmin.db",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("garmin.db not found in standard GarminDB directories")


def _init_extended_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS blood_pressure (
            day TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            timestamp_gmt TEXT,
            systolic INTEGER NOT NULL,
            diastolic INTEGER NOT NULL,
            pulse INTEGER,
            category TEXT,
            category_name TEXT,
            source_type TEXT,
            version INTEGER,
            PRIMARY KEY (day, timestamp)
        );
        CREATE INDEX IF NOT EXISTS idx_blood_pressure_day ON blood_pressure (day);

        CREATE TABLE IF NOT EXISTS training_readiness (
            day TEXT PRIMARY KEY,
            timestamp TEXT,
            timestamp_gmt TEXT,
            score INTEGER,
            level TEXT,
            feedback_short TEXT,
            feedback_long TEXT,
            recovery_time_hours INTEGER,
            recovery_time_factor_percent INTEGER,
            recovery_time_feedback TEXT,
            sleep_score INTEGER,
            sleep_score_factor_percent INTEGER,
            sleep_score_feedback TEXT,
            acwr_factor_percent INTEGER,
            acwr_feedback TEXT,
            acute_load INTEGER,
            hrv_factor_percent INTEGER,
            hrv_feedback TEXT,
            hrv_weekly_avg INTEGER,
            stress_history_factor_percent INTEGER,
            stress_history_feedback TEXT,
            sleep_history_factor_percent INTEGER,
            sleep_history_feedback TEXT,
            valid_sleep INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_training_readiness_day ON training_readiness (day);

        CREATE TABLE IF NOT EXISTS fitness_age (
            day TEXT PRIMARY KEY,
            chronological_age INTEGER,
            fitness_age REAL,
            achievable_fitness_age REAL,
            previous_fitness_age REAL,
            bmi_value REAL,
            bmi_target REAL,
            bmi_potential_age REAL,
            vigorous_minutes_avg REAL,
            vigorous_minutes_target REAL,
            vigorous_days_avg REAL,
            vigorous_days_target REAL,
            rhr_value INTEGER,
            last_updated TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_fitness_age_day ON fitness_age (day);

        CREATE TABLE IF NOT EXISTS endurance_score (
            day TEXT PRIMARY KEY,
            overall_score INTEGER,
            classification INTEGER,
            feedback_phrase TEXT,
            top_contributor_type_id INTEGER,
            top_contributor_pct REAL,
            json_data TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_endurance_score_day ON endurance_score (day);

        CREATE TABLE IF NOT EXISTS body_battery_events (
            event_id TEXT PRIMARY KEY,
            day TEXT NOT NULL,
            event_type TEXT NOT NULL,
            start_time_gmt TEXT,
            duration_seconds INTEGER,
            body_battery_impact INTEGER,
            average_stress REAL,
            short_feedback TEXT,
            activity_name TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_bb_events_day ON body_battery_events (day);

        CREATE TABLE IF NOT EXISTS daily_respiration (
            day TEXT PRIMARY KEY,
            highest_respiration REAL,
            lowest_respiration REAL,
            waking_avg REAL,
            latest_respiration REAL
        );
        CREATE INDEX IF NOT EXISTS idx_daily_respiration_day ON daily_respiration (day);
        """
    )
    conn.commit()


def sync_blood_pressure_range(
    client: Any,
    start_str: str,
    end_str: str,
    conn: sqlite3.Connection,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    raw = client.get_blood_pressure(start_str, end_str)
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        dump_file = cache_dir / f"bp_{start_str}_{end_str}.json"
        dump_file.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    summaries = raw.get("measurementSummaries", []) if isinstance(raw, dict) else []
    inserted = 0
    cur = conn.cursor()
    for s in summaries:
        s_date = str(s.get("startDate") or "")
        measurements = s.get("measurements", [])
        for m in measurements:
            ts_loc = m.get("measurementTimestampLocal") or f"{s_date} 00:00:00"
            ts_gmt = m.get("measurementTimestampGMT")
            sys_val = m.get("systolic")
            dia_val = m.get("diastolic")
            if sys_val is None or dia_val is None:
                continue
            cur.execute(
                """
                INSERT OR REPLACE INTO blood_pressure (
                    day, timestamp, timestamp_gmt, systolic, diastolic, pulse,
                    category, category_name, source_type, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    s_date,
                    str(ts_loc),
                    str(ts_gmt) if ts_gmt else None,
                    int(sys_val),
                    int(dia_val),
                    int(m["pulse"]) if m.get("pulse") is not None else None,
                    m.get("category"),
                    m.get("categoryName"),
                    m.get("sourceType"),
                    int(m["version"]) if m.get("version") is not None else None,
                ),
            )
            inserted += 1
    conn.commit()
    return {"days": len(summaries), "records_inserted": inserted}


def sync_training_readiness_range(
    client: Any,
    start_date: date,
    end_date: date,
    conn: sqlite3.Connection,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    cur_dt = start_date
    days_synced = 0
    records_inserted = 0
    cur = conn.cursor()

    while cur_dt <= end_date:
        d_str = cur_dt.isoformat()
        res = None
        try:
            res = client.get_morning_training_readiness(d_str)
        except Exception:
            try:
                raw_tr = client.get_training_readiness(d_str)
                if isinstance(raw_tr, list) and raw_tr:
                    res = raw_tr[0]
            except Exception:
                res = None

        if isinstance(res, dict) and res.get("score") is not None:
            if cache_dir:
                dump_file = cache_dir / f"readiness_{d_str}.json"
                dump_file.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")

            ts_loc = res.get("timestampLocal") or f"{d_str} 07:00:00"
            ts_gmt = res.get("timestamp")
            cur.execute(
                """
                INSERT OR REPLACE INTO training_readiness (
                    day, timestamp, timestamp_gmt, score, level, feedback_short, feedback_long,
                    recovery_time_hours, recovery_time_factor_percent, recovery_time_feedback,
                    sleep_score, sleep_score_factor_percent, sleep_score_feedback,
                    acwr_factor_percent, acwr_feedback, acute_load,
                    hrv_factor_percent, hrv_feedback, hrv_weekly_avg,
                    stress_history_factor_percent, stress_history_feedback,
                    sleep_history_factor_percent, sleep_history_feedback,
                    valid_sleep
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    d_str,
                    str(ts_loc),
                    str(ts_gmt) if ts_gmt else None,
                    int(res["score"]),
                    res.get("level"),
                    res.get("feedbackShort"),
                    res.get("feedbackLong"),
                    int(res["recoveryTime"]) if res.get("recoveryTime") is not None else None,
                    int(res["recoveryTimeFactorPercent"]) if res.get("recoveryTimeFactorPercent") is not None else None,
                    res.get("recoveryTimeFactorFeedback"),
                    int(res["sleepScore"]) if res.get("sleepScore") is not None else None,
                    int(res["sleepScoreFactorPercent"]) if res.get("sleepScoreFactorPercent") is not None else None,
                    res.get("sleepScoreFactorFeedback"),
                    int(res["acwrFactorPercent"]) if res.get("acwrFactorPercent") is not None else None,
                    res.get("acwrFactorFeedback"),
                    int(res["acuteLoad"]) if res.get("acuteLoad") is not None else None,
                    int(res["hrvFactorPercent"]) if res.get("hrvFactorPercent") is not None else None,
                    res.get("hrvFactorFeedback"),
                    int(res["hrvWeeklyAverage"]) if res.get("hrvWeeklyAverage") is not None else None,
                    int(res["stressHistoryFactorPercent"]) if res.get("stressHistoryFactorPercent") is not None else None,
                    res.get("stressHistoryFactorFeedback"),
                    int(res["sleepHistoryFactorPercent"]) if res.get("sleepHistoryFactorPercent") is not None else None,
                    res.get("sleepHistoryFactorFeedback"),
                    1 if res.get("validSleep") else 0,
                ),
            )
            records_inserted += 1
            days_synced += 1
        cur_dt += timedelta(days=1)

    conn.commit()
    return {"days_probed": (end_date - start_date).days + 1, "records_inserted": records_inserted}


def sync_fitness_age_range(
    client: Any,
    target_date: date,
    conn: sqlite3.Connection,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
    d_str = target_date.isoformat()
    try:
        raw = client.get_fitnessage_data(d_str)
    except Exception:
        return {"records_inserted": 0, "status": "no_data_or_error"}
    if not isinstance(raw, dict) or raw.get("fitnessAge") is None:
        return {"records_inserted": 0, "status": "no_data"}

    if cache_dir:
        dump_file = cache_dir / f"fitness_age_{d_str}.json"
        dump_file.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    comps = raw.get("components", {})
    bmi = comps.get("bmi", {})
    vig_m = comps.get("vigorousMinutesAvg", {})
    vig_d = comps.get("vigorousDaysAvg", {})
    rhr = comps.get("rhr", {})

    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO fitness_age (
            day, chronological_age, fitness_age, achievable_fitness_age, previous_fitness_age,
            bmi_value, bmi_target, bmi_potential_age,
            vigorous_minutes_avg, vigorous_minutes_target,
            vigorous_days_avg, vigorous_days_target,
            rhr_value, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            d_str,
            int(raw["chronologicalAge"]) if raw.get("chronologicalAge") is not None else None,
            float(raw["fitnessAge"]) if raw.get("fitnessAge") is not None else None,
            float(raw["achievableFitnessAge"]) if raw.get("achievableFitnessAge") is not None else None,
            float(raw["previousFitnessAge"]) if raw.get("previousFitnessAge") is not None else None,
            float(bmi["value"]) if bmi.get("value") is not None else None,
            float(bmi["targetValue"]) if bmi.get("targetValue") is not None else None,
            float(bmi["potentialAge"]) if bmi.get("potentialAge") is not None else None,
            float(vig_m["value"]) if vig_m.get("value") is not None else None,
            float(vig_m["targetValue"]) if vig_m.get("targetValue") is not None else None,
            float(vig_d["value"]) if vig_d.get("value") is not None else None,
            float(vig_d["targetValue"]) if vig_d.get("targetValue") is not None else None,
            int(rhr["value"]) if rhr.get("value") is not None else None,
            raw.get("lastUpdated"),
        ),
    )
    conn.commit()
    return {"records_inserted": 1, "fitness_age": raw.get("fitnessAge")}


def sync_endurance_score_range(
    client: Any,
    start_str: str,
    end_str: str,
    conn: sqlite3.Connection,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        raw = client.get_endurance_score(start_str, end_str)
    except Exception:
        return {"records_inserted": 0, "status": "no_data_or_error"}
    if not isinstance(raw, dict):
        return {"records_inserted": 0, "status": "no_data"}

    if cache_dir:
        dump_file = cache_dir / f"endurance_{start_str}_{end_str}.json"
        dump_file.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    dto = raw.get("enduranceScoreDTO", {})
    cal_date = dto.get("calendarDate") or end_str
    score = dto.get("overallScore")
    if score is None:
        return {"records_inserted": 0, "status": "no_score"}

    contributors = dto.get("contributors", [])
    top_c_type = None
    top_c_pct = None
    if contributors:
        sorted_c = sorted(contributors, key=lambda x: x.get("contribution", 0), reverse=True)
        top_c_type = sorted_c[0].get("activityTypeId")
        top_c_pct = sorted_c[0].get("contribution")

    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO endurance_score (
            day, overall_score, classification, feedback_phrase,
            top_contributor_type_id, top_contributor_pct, json_data
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cal_date,
            int(score),
            dto.get("classification"),
            str(dto.get("feedbackPhrase")) if dto.get("feedbackPhrase") is not None else None,
            int(top_c_type) if top_c_type is not None else None,
            float(top_c_pct) if top_c_pct is not None else None,
            json.dumps(dto, ensure_ascii=False),
        ),
    )
    conn.commit()
    return {"records_inserted": 1, "overall_score": score, "date": cal_date}


def sync_body_battery_events_range(
    client: Any,
    start_date: date,
    end_date: date,
    conn: sqlite3.Connection,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    cur_dt = start_date
    days_synced = 0
    records_inserted = 0
    cur = conn.cursor()

    while cur_dt <= end_date:
        d_str = cur_dt.isoformat()
        try:
            events = client.get_body_battery_events(d_str)
        except Exception:
            events = None

        if isinstance(events, list) and events:
            if cache_dir:
                dump_file = cache_dir / f"bb_events_{d_str}.json"
                dump_file.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")

            for ev in events:
                inner = ev.get("event") or ev
                e_type = inner.get("eventType")
                s_gmt = inner.get("eventStartTimeGmt")
                if not e_type or not s_gmt:
                    continue
                ev_id = f"{d_str}_{e_type}_{s_gmt}"
                dur_ms = inner.get("durationInMilliseconds")
                dur_s = int(dur_ms / 1000) if dur_ms is not None else None
                cur.execute(
                    """
                    INSERT OR REPLACE INTO body_battery_events (
                        event_id, day, event_type, start_time_gmt, duration_seconds,
                        body_battery_impact, average_stress, short_feedback, activity_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ev_id,
                        d_str,
                        str(e_type),
                        str(s_gmt),
                        dur_s,
                        int(inner["bodyBatteryImpact"]) if inner.get("bodyBatteryImpact") is not None else None,
                        float(ev["averageStress"]) if ev.get("averageStress") is not None else None,
                        inner.get("shortFeedback") or inner.get("feedbackType"),
                        ev.get("activityName"),
                    ),
                )
                records_inserted += 1
            days_synced += 1
        cur_dt += timedelta(days=1)

    conn.commit()
    return {"days_probed": (end_date - start_date).days + 1, "records_inserted": records_inserted}


def sync_daily_respiration_range(
    client: Any,
    start_date: date,
    end_date: date,
    conn: sqlite3.Connection,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    cur_dt = start_date
    days_synced = 0
    records_inserted = 0
    cur = conn.cursor()

    while cur_dt <= end_date:
        d_str = cur_dt.isoformat()
        try:
            resp = client.get_respiration_data(d_str)
        except Exception:
            resp = None

        if isinstance(resp, dict) and (resp.get("highestRespirationValue") is not None or resp.get("wakingAvg") is not None):
            if cache_dir:
                dump_file = cache_dir / f"resp_{d_str}.json"
                dump_file.write_text(json.dumps(resp, indent=2, ensure_ascii=False), encoding="utf-8")

            cur.execute(
                """
                INSERT OR REPLACE INTO daily_respiration (
                    day, highest_respiration, lowest_respiration, waking_avg, latest_respiration
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    d_str,
                    float(resp["highestRespirationValue"]) if resp.get("highestRespirationValue") is not None else None,
                    float(resp["lowestRespirationValue"]) if resp.get("lowestRespirationValue") is not None else None,
                    float(resp["wakingAvg"]) if resp.get("wakingAvg") is not None else None,
                    float(resp["latestRespirationValue"]) if resp.get("latestRespirationValue") is not None else None,
                ),
            )
            records_inserted += 1
            days_synced += 1
        cur_dt += timedelta(days=1)

    conn.commit()
    return {"days_probed": (end_date - start_date).days + 1, "records_inserted": records_inserted}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync extended metrics (Blood Pressure, Training Readiness) from Garmin Connect."
    )
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=30, help="Default lookback days if start/end omitted (default: 30)")
    parser.add_argument(
        "--metrics",
        nargs="+",
        choices=EXTENDED_METRICS,
        default=list(EXTENDED_METRICS),
        help="Metrics to sync (default: blood_pressure training_readiness)",
    )
    parser.add_argument("--allow-network", action="store_true", help="Authorize network access")
    parser.add_argument("--allow-sync", action="store_true", help="Authorize database write")
    parser.add_argument("--dry-run", action="store_true", help="Probe intent only without network or DB writes")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    today = date.today()
    if args.end:
        end_d = date.fromisoformat(args.end)
    else:
        end_d = today

    if args.start:
        start_d = date.fromisoformat(args.start)
    else:
        start_d = end_d - timedelta(days=max(1, args.days) - 1)

    if start_d > end_d or end_d > today:
        print(json.dumps({"ok": False, "status": "invalid_date_window"}, ensure_ascii=False))
        return 2

    if args.dry_run:
        print(
            json.dumps(
                {
                    "ok": True,
                    "status": "dry_run",
                    "window": {"start": start_d.isoformat(), "end": end_d.isoformat()},
                    "metrics": args.metrics,
                    "network_accessed": False,
                    "database_written": False,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if not args.allow_network:
        print(json.dumps({"ok": False, "status": "network_authorization_required"}, ensure_ascii=False))
        return 3

    if not args.allow_sync:
        print(json.dumps({"ok": False, "status": "sync_authorization_required"}, ensure_ascii=False))
        return 3

    req = {"command": "sync_extended_metrics", "window": {"start": start_d.isoformat(), "end": end_d.isoformat()}}
    net_cap = issue_capability(scope="network", operation=garmin_auth.AUTH_OPERATION, request=req)

    import garminconnect

    garmin_auth._force_direct_garmin_egress(os.environ)
    with garmin_auth._tun_fake_ip_bypass_scope(garminconnect.Garmin):
        client = garmin_auth.get_client(network_capability=net_cap, request=req, in_memory=True)
        if not client:
            print(json.dumps({"ok": False, "status": "authentication_required"}, ensure_ascii=False))
            return 5

        db_path = _resolve_garmin_db_path()
        base_data_dir = db_path.parent.parent

        results: dict[str, Any] = {}
        with sqlite3.connect(db_path) as conn:
            _init_extended_tables(conn)
            if "blood_pressure" in args.metrics:
                bp_cache = base_data_dir / "BloodPressure"
                bp_res = sync_blood_pressure_range(
                    client, start_d.isoformat(), end_d.isoformat(), conn, cache_dir=bp_cache
                )
                results["blood_pressure"] = bp_res

            if "training_readiness" in args.metrics:
                tr_cache = base_data_dir / "TrainingReadiness"
                tr_res = sync_training_readiness_range(
                    client, start_d, end_d, conn, cache_dir=tr_cache
                )
                results["training_readiness"] = tr_res

            if "fitness_age" in args.metrics:
                fa_cache = base_data_dir / "FitnessAge"
                fa_res = sync_fitness_age_range(
                    client, end_d, conn, cache_dir=fa_cache
                )
                results["fitness_age"] = fa_res

            if "endurance_score" in args.metrics:
                es_cache = base_data_dir / "EnduranceScore"
                es_res = sync_endurance_score_range(
                    client, start_d.isoformat(), end_d.isoformat(), conn, cache_dir=es_cache
                )
                results["endurance_score"] = es_res

            if "body_battery_events" in args.metrics:
                bbe_cache = base_data_dir / "BodyBatteryEvents"
                bbe_res = sync_body_battery_events_range(
                    client, start_d, end_d, conn, cache_dir=bbe_cache
                )
                results["body_battery_events"] = bbe_res

            if "daily_respiration" in args.metrics:
                dr_cache = base_data_dir / "Respiration"
                dr_res = sync_daily_respiration_range(
                    client, start_d, end_d, conn, cache_dir=dr_cache
                )
                results["daily_respiration"] = dr_res

    print(
        json.dumps(
            {
                "ok": True,
                "status": "sync_completed",
                "window": {"start": start_d.isoformat(), "end": end_d.isoformat()},
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
