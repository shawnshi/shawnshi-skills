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
EXTENDED_METRICS = ("blood_pressure", "training_readiness")


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
