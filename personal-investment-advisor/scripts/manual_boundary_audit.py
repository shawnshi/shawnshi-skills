#!/usr/bin/env python3
"""手工观察边界覆盖审计（只读）。

按用户 2026-10-01 裁定，`user_confirmed` 手工档保留告警权威，与政策派生档并列。
本脚本回答两件事，并把缺口显式化：

1. 权威 Dashboard 代是否携带其历史确认的手工档？（缺失即 ``manual_boundary_coverage_gap``）
2. 按本次行情，各手工档是越界 / 接近 / 未越界 / 未评估？

只读：不修改任何 Dashboard、组合或运行制品。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SCHEMA_VERSION = "pia_manual_boundary_audit_v1"
CONFIRMED = "user_confirmed"


class AuditError(RuntimeError):
    """输入缺失或结构非法时失败关闭。"""


def _read_json(path: Path, label: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuditError(f"{label} unreadable: {type(exc).__name__}") from exc


def pinned_generations(stocks_root: Path) -> dict[str, str]:
    index = _read_json(stocks_root / "dashboard_index.json", "dashboard index")
    dashboards = index.get("dashboards")
    if not isinstance(dashboards, dict):
        raise AuditError("dashboard index has no dashboards map")
    return {str(s): str(e.get("generation_id") or "") for s, e in dashboards.items() if isinstance(e, dict)}


def collect_manual_boundaries(stocks_root: Path, symbols: set[str]) -> dict[tuple[str, str], dict]:
    """按 (symbol, boundary_id) 归并全部代的 user_confirmed 手工档。"""
    collected: dict[tuple[str, str], dict] = {}
    for generation in sorted(stocks_root.glob("*/generations/*/dashboard.json")):
        symbol = generation.parts[-4]
        if symbol not in symbols:
            continue
        payload = _read_json(generation, f"dashboard {generation}")
        block = payload.get("monitoring_boundaries")
        if not isinstance(block, dict):
            continue
        for boundary in block.get("boundaries") or []:
            if not isinstance(boundary, dict) or boundary.get("authority_status") != CONFIRMED:
                continue
            key = (symbol, str(boundary.get("boundary_id") or ""))
            record = collected.setdefault(
                key,
                {
                    "symbol": symbol,
                    "boundary_id": key[1],
                    "role": boundary.get("role"),
                    "operator": boundary.get("operator"),
                    "boundary_value": boundary.get("value"),
                    "authority_status": boundary.get("authority_status"),
                    "source_locator": boundary.get("source_locator"),
                    "generations": [],
                    "pinned_in_run": False,
                },
            )
            record["generations"].append(generation.parent.name)
    return collected


def run_prices(run_dir: Path) -> dict[str, dict]:
    """从运行目录取本轮报价快照（只读 out/daily_sync.json）。"""
    payload = _read_json(run_dir / "out" / "daily_sync.json", "daily sync report")
    snapshot = payload.get("quote_snapshot")
    if not isinstance(snapshot, list):
        raise AuditError("daily sync report has no quote_snapshot list")
    prices = {}
    for record in snapshot:
        if isinstance(record, dict) and isinstance(record.get("symbol"), str):
            prices[record["symbol"]] = record
    return prices


def run_evaluated_ids(run_dir: Path) -> set[str]:
    evaluated: set[str] = set()
    for path in (run_dir / "out").glob("watchlist_*.json"):
        if path.name == "watchlist_results.json":
            continue
        payload = _read_json(path, f"watchlist report {path.name}")
        for item in payload.get("evaluations") or []:
            if isinstance(item, dict) and item.get("boundary_id"):
                evaluated.add(str(item["boundary_id"]))
    return evaluated


def run_proximity_value(run_dir: Path) -> float | None:
    path = run_dir / "out" / "position_limits.json"
    if not path.is_file():
        return None
    policy = (_read_json(path, "position limits") or {}).get("proximity_policy")
    if isinstance(policy, dict) and isinstance(policy.get("value"), (int, float)):
        return float(policy["value"])
    return None


def pinned_boundary_ids(stocks_root: Path, symbols: set[str]) -> set[tuple[str, str]]:
    """权威代（本次被钉住的那一代）实际携带的手工档集合。"""
    pinned = pinned_generations(stocks_root)
    found: set[tuple[str, str]] = set()
    for symbol in symbols:
        generation_id = pinned.get(symbol)
        if not generation_id:
            continue
        path = stocks_root / symbol / "generations" / generation_id / "dashboard.json"
        if not path.is_file():
            continue
        payload = _read_json(path, "pinned dashboard")
        block = payload.get("monitoring_boundaries")
        if not isinstance(block, dict):
            continue
        for boundary in block.get("boundaries") or []:
            if isinstance(boundary, dict) and boundary.get("authority_status") == CONFIRMED:
                found.add((symbol, str(boundary.get("boundary_id") or "")))
    return found


def audit(stocks_root: Path, run_dir: Path) -> dict:
    prices = run_prices(run_dir)
    symbols = set(prices)
    manual = collect_manual_boundaries(stocks_root, symbols)
    pinned_ids = pinned_boundary_ids(stocks_root, symbols)
    evaluated = run_evaluated_ids(run_dir)
    proximity = run_proximity_value(run_dir)

    crossed, near, not_crossed, unevaluable = [], [], [], []
    for key, record in manual.items():
        quote = prices.get(record["symbol"]) or {}
        price = quote.get("current_price")
        value = record["boundary_value"]
        operator = record["operator"]
        record["current_price"] = price
        record["price_as_of"] = quote.get("as_of")
        record["price_source"] = quote.get("source")
        record["evaluated_by_run"] = record["boundary_id"] in evaluated
        record["pinned_in_run"] = key in pinned_ids
        usable = (
            isinstance(price, (int, float))
            and isinstance(value, (int, float))
            and value > 0
            and operator in {"lte", "gte"}
        )
        if not usable:
            record["reason"] = "operator_price_or_value_unusable"
            unevaluable.append(record)
            continue
        relative_gap = abs(float(price) / float(value) - 1)
        record["relative_gap"] = round(relative_gap, 6)
        if (float(price) <= value) if operator == "lte" else (float(price) >= value):
            record["status"] = "crossed"
            crossed.append(record)
        elif proximity is not None and relative_gap <= proximity:
            record["status"] = "near"
            near.append(record)
        else:
            record["status"] = "not_crossed"
            not_crossed.append(record)

    missing_from_pinned = sorted(
        {f"{symbol}:{bid}" for (symbol, bid) in manual if (symbol, bid) not in pinned_ids}
    )
    gaps = []
    if missing_from_pinned:
        gaps.append(
            {
                "code": "manual_boundary_coverage_gap",
                "detail": "历史代存在 user_confirmed 手工档，但本次钉住的权威代未携带；按裁定只能报告缺口，不得从归档代补齐。",
                "boundaries": missing_from_pinned,
            }
        )
    if proximity is None:
        gaps.append({"code": "near_rule_undefined", "detail": "无显式接近规则（Dashboard 与用户政策均未提供）。"})

    def brief(rows):
        return [
            {
                "symbol": r["symbol"],
                "boundary_id": r["boundary_id"],
                "operator": r["operator"],
                "boundary_value": r["boundary_value"],
                "current_price": r["current_price"],
                "relative_gap": r.get("relative_gap"),
                "status": r.get("status"),
                "pinned_in_run": r["pinned_in_run"],
                "evaluated_by_run": r["evaluated_by_run"],
            }
            for r in sorted(rows, key=lambda x: (x["symbol"], x["boundary_id"]))
        ]

    return {
        "schema_version": SCHEMA_VERSION,
        "stocks_root": str(stocks_root),
        "run_dir": str(run_dir),
        "proximity_value": proximity,
        "manual_boundary_count": len(manual),
        "crossed": brief(crossed),
        "near": brief(near),
        "not_crossed": brief(not_crossed),
        "unevaluable": brief(unevaluable),
        "missed_by_run": sorted(
            {r["boundary_id"] for r in list(manual.values()) if r["boundary_id"] not in evaluated}
        ),
        "gaps": gaps,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stocks-root", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = audit(args.stocks_root.expanduser().resolve(), args.run_dir.expanduser().resolve())
    except AuditError as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False))
        return 3
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"status": "complete", "out": str(args.out),
                          "sha256": hashlib.sha256((text + "\n").encode("utf-8")).hexdigest(),
                          "crossed": len(payload["crossed"]), "near": len(payload["near"]),
                          "gaps": [g["code"] for g in payload["gaps"]]}, ensure_ascii=False))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
