#!/usr/bin/env python3
"""Share-count change (dilution / accretion) assessment for A-share holdings.

Why this exists: per-share metrics and thesis checks silently assume a constant share
count.  A convertible-bond conversion, an option exercise or a buyback moves the
denominator, and nothing in the pipeline noticed.  This tool reads the issuer's
share-change ledger and reports the signed change with its reason, point-in-time.

Point-in-time discipline: an event is selected by its **announcement** date (when it
became knowable) and reported with its **effective** date, so a replay for an earlier
as-of date cannot see a later announcement.

Boundaries: A-share issuers only.  Open-ended funds (ETF/LOF) have creation/redemption
instead of dilution and are declared `not_applicable` rather than reported as zero.
A symbol with no rows is `insufficient_data`, never a zero change.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

DECISION_SCOPE = "research_only"
SCHEMA_VERSION = "pia_share_change_v1"
CHANNEL = "cninfo 股本变动 (akshare stock_share_change_cninfo)"
SHARE_UNIT_MULTIPLIER = 10_000  # the channel reports thousands of shares (万股)
CN_SUFFIXES = (".SS", ".SZ", ".BJ")
CN_CODE = re.compile(r"^\d{6}$")
# Shanghai/Shenzhen listed fund code ranges: open-ended funds (ETF/LOF) have
# creation/redemption, not an issuer share count.
FUND_CODE_PREFIXES = ("15", "16", "50", "51", "52", "56", "58")


class ShareChangeError(RuntimeError):
    pass


def cninfo_code(symbol: str) -> str | None:
    """Map 601899.SS to 601899; none when the symbol is not an A-share code."""
    upper = symbol.strip().upper()
    for suffix in CN_SUFFIXES:
        if upper.endswith(suffix):
            stem = upper[: -len(suffix)]
            return stem if CN_CODE.match(stem) else None
    return None


def classify(symbol: str, overrides: dict[str, str] | None = None) -> tuple[str, str | None]:
    """Return (class, not_applicable_reason) for a symbol."""
    override = (overrides or {}).get(symbol.strip().upper())
    if override == "fund":
        return "fund", "open_ended_fund_shares_are_creation_redemption_not_dilution"
    if override == "stock":
        return "stock", None
    code = cninfo_code(symbol)
    if code is None:
        return "not_applicable", "not_an_a_share_issuer"
    if code.startswith(FUND_CODE_PREFIXES):
        return "fund", "open_ended_fund_shares_are_creation_redemption_not_dilution"
    return "stock", None


def _finite_float(value: Any) -> float | None:
    """pandas turns a missing number into NaN; NaN is not a JSON number."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_text(value: Any) -> str | None:
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "nat"):
        return None
    return text


SPLIT_KEYWORDS = ("转增", "送股", "拆股", "拆细")
ISSUANCE_KEYWORDS = ("增发", "新股上市", "配股", "ipo", "h股上市", "a股上市")
BUYBACK_KEYWORDS = ("回购", "注销", "缩股")
CONVERSION_KEYWORDS = ("可转债转股", "转股", "期权行权", "行权", "股权激励")
# Natures that move the share count without changing per-share economics: a bonus
# issue (转增) or a stock dividend (送股) multiplies shares and divides the price.
MECHANICAL_NATURES = ("share_split_equivalent",)
ECONOMIC_NATURES = ("capital_issuance", "conversion_or_exercise", "buyback_or_cancellation",
                    "other_share_count_change")


def classify_event(reason: str | None, delta_shares: float | None) -> str:
    """Name what kind of share-count event this row is.

    Priority is by economics, not by keyword order in the reason text: a row that is
    both a conversion and a buyback is a buyback (it reduces shares), and a row that
    matches a split keyword but reduces the count is not a split.
    """

    text = (reason or "").strip().lower()
    if delta_shares is None or delta_shares == 0:
        return "restatement_no_change"
    if delta_shares > 0 and any(keyword in text for keyword in SPLIT_KEYWORDS):
        return "share_split_equivalent"
    if any(keyword in text for keyword in ISSUANCE_KEYWORDS):
        return "capital_issuance"
    if any(keyword in text for keyword in BUYBACK_KEYWORDS):
        return "buyback_or_cancellation"
    if any(keyword in text for keyword in CONVERSION_KEYWORDS):
        return "conversion_or_exercise"
    return "other_share_count_change"


def normalise_rows(frame: Any) -> list[dict[str, Any]]:
    """Normalise a share-change frame into dated rows in shares (not 万股).

    Zero-change rows (e.g. periodic-report restatements) are kept: they are evidence
    that the ledger was read to that date, and they carry delta 0.
    """

    if frame is None or not hasattr(frame, "columns"):
        raise ShareChangeError("share-change payload is not a table")
    required = {"变动日期", "总股本"}
    missing = required - set(frame.columns)
    if missing:
        raise ShareChangeError(f"share-change payload lacks columns: {sorted(missing)}")
    rows: list[dict[str, Any]] = []
    for record in frame.to_dict("records"):
        effective = _clean_text(record.get("变动日期") or "") or ""
        effective = effective[:10]
        if not effective:
            continue
        total_shares = _finite_float(record.get("总股本"))
        if total_shares is None:
            continue
        total_shares *= SHARE_UNIT_MULTIPLIER
        listed_shares = _finite_float(record.get("已流通股份"))
        if listed_shares is not None:
            listed_shares *= SHARE_UNIT_MULTIPLIER
        announced = _clean_text(record.get("公告日期")) or None
        rows.append({
            "effective_date": effective,
            "announcement_date": announced[:10] if announced else None,
            "total_shares": total_shares,
            "listed_shares": listed_shares,
            "reason": _clean_text(record.get("变动原因")),
        })
    rows.sort(key=lambda row: (row["effective_date"], row["announcement_date"] or ""))
    return rows


def assess(symbol: str, rows: list[dict[str, Any]], *, as_of_date: str, lookback_days: int,
           threshold: float) -> dict[str, Any]:
    """Signed share-count change over the window ending at as_of_date."""

    as_of = datetime.date.fromisoformat(as_of_date)
    window_start = as_of - datetime.timedelta(days=lookback_days)
    visible = [row for row in rows
               if (row["announcement_date"] or row["effective_date"]) <= as_of.isoformat()
               and row["effective_date"] >= window_start.isoformat()]
    if not visible:
        return {"symbol": symbol, "status": "insufficient_data",
                "detail_status": "no_share_change_rows_in_window",
                "window": {"start": window_start.isoformat(), "end": as_of.isoformat(),
                           "as_of_basis": "announcement_date"},
                "errors": [f"no share-change rows announced on or before {as_of_date} "
                           f"within {lookback_days} days"]}

    events: list[dict[str, Any]] = []
    previous: float | None = None
    for row in visible:
        total = row["total_shares"]
        delta_shares = None if previous is None else total - previous
        delta_ratio = None if not previous else delta_shares / previous
        nature = classify_event(row["reason"], delta_shares)
        economic_delta = delta_shares if nature in ECONOMIC_NATURES else 0.0
        events.append({
            "effective_date": row["effective_date"],
            "announcement_date": row["announcement_date"],
            "total_shares": round(total, 2),
            "listed_shares": (round(row["listed_shares"], 2)
                              if row["listed_shares"] is not None else None),
            "delta_shares": None if delta_shares is None else round(delta_shares, 2),
            "delta_ratio": None if delta_ratio is None else round(delta_ratio, 6),
            "nature": nature,
            "mechanical": nature in MECHANICAL_NATURES,
            "reason": row["reason"],
        })
        events[-1]["_economic_delta"] = economic_delta
        previous = total

    first, last = events[0], events[-1]
    net_delta_shares = last["total_shares"] - first["total_shares"]
    net_change_ratio = (net_delta_shares / first["total_shares"]) if first["total_shares"] else None
    economic_delta_shares = sum(event["_economic_delta"] for event in events
                                if event["delta_shares"] is not None)
    economic_change_ratio = (economic_delta_shares / first["total_shares"]
                             if first["total_shares"] else None)
    # Materiality is judged on the economic change: a bonus issue moves the share count
    # without moving per-share economics, while an issuance genuinely dilutes.
    material = [event for event in events
                if event["delta_ratio"] is not None and not event["mechanical"]
                and abs(event["delta_ratio"]) >= threshold]
    largest = max((event for event in events if event["delta_ratio"] is not None),
                  key=lambda event: abs(event["delta_ratio"]), default=None)
    largest_economic = max(material, key=lambda event: abs(event["delta_ratio"]), default=None)
    for event in events:
        del event["_economic_delta"]

    def direction_of(ratio: float | None) -> str:
        if not ratio:
            return "unchanged"
        return "dilution" if ratio > 0 else "accretion"

    return {
        "symbol": symbol,
        "status": "complete",
        "detail_status": "share_change_assessed",
        "direction": direction_of(net_change_ratio),
        "economic_direction": direction_of(economic_change_ratio),
        "net_change_ratio": None if net_change_ratio is None else round(net_change_ratio, 6),
        "economic_change_ratio": (None if economic_change_ratio is None
                                  else round(economic_change_ratio, 6)),
        "net_delta_shares": round(net_delta_shares, 2),
        "economic_delta_shares": round(economic_delta_shares, 2),
        "material_change": bool(material),
        "threshold": threshold,
        "material_events": material,
        "largest_event": largest,
        "largest_economic_event": largest_economic,
        "events": events,
        "observation_window": {"first_effective_date": first["effective_date"],
                               "last_effective_date": last["effective_date"],
                               "first_total_shares": first["total_shares"],
                               "last_total_shares": last["total_shares"],
                               "window": {"start": window_start.isoformat(),
                                          "end": as_of.isoformat(),
                                          "as_of_basis": "announcement_date"}},
        "row_count": len(events),
        "notes": ("share_split_equivalent events (转增/送股) move the share count without "
                  "changing per-share economics and are excluded from "
                  "economic_change_ratio and from materiality"),
    }


def fetch_share_changes(code: str, *, start_date: str, end_date: str) -> Any:
    """Fetch the share-change ledger. Imported lazily so tests need no akshare."""

    import akshare as ak  # noqa: PLC0415

    return ak.stock_share_change_cninfo(symbol=code, start_date=start_date.replace("-", ""),
                                        end_date=end_date.replace("-", ""))


def parse_class_overrides(items: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in items:
        symbol, _, raw = item.partition("=")
        value = raw.strip().lower()
        if not symbol.strip() or value not in ("stock", "fund"):
            raise ShareChangeError(f"--class expects SYMBOL=stock|fund, got {item!r}")
        overrides[symbol.strip().upper()] = value
    return overrides


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Signed share-count change (dilution/accretion) for A-share holdings.")
    parser.add_argument("--symbol", action="append", default=[], help="repeatable")
    parser.add_argument("--class", action="append", default=[], dest="class_overrides",
                        help="SYMBOL=stock|fund override, repeatable")
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--lookback-days", type=int, default=400)
    parser.add_argument("--threshold", type=float, default=0.01,
                        help="absolute delta ratio treated as material (default 1%%)")
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    errors: list[str] = []
    try:
        if not args.symbol:
            raise ShareChangeError("at least one --symbol is required")
        if args.lookback_days <= 0:
            raise ShareChangeError("--lookback-days must be positive")
        if args.threshold < 0:
            raise ShareChangeError("--threshold must not be negative")
        datetime.date.fromisoformat(args.as_of_date)
        overrides = parse_class_overrides(args.class_overrides)
    except (ShareChangeError, ValueError) as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "failed",
                          "detail_status": "share_change_input_invalid",
                          "decision_scope": DECISION_SCOPE, "errors": [str(exc)]},
                         ensure_ascii=False, indent=2))
        return 3

    start_date = (datetime.date.fromisoformat(args.as_of_date)
                  - datetime.timedelta(days=args.lookback_days)).isoformat()
    results: list[dict[str, Any]] = []
    for symbol in args.symbol:
        symbol = symbol.strip().upper()
        kind, reason = classify(symbol, overrides)
        if kind != "stock":
            results.append({"symbol": symbol, "status": "not_applicable",
                            "detail_status": reason, "decision_scope": DECISION_SCOPE})
            continue
        code = cninfo_code(symbol)
        try:
            frame = fetch_share_changes(code, start_date=start_date, end_date=args.as_of_date)
            rows = normalise_rows(frame)
        except Exception as exc:  # noqa: BLE001 - the channel's failure mode is reported
            results.append({"symbol": symbol, "status": "insufficient_data",
                            "detail_status": "share_change_channel_failed",
                            "errors": [f"{type(exc).__name__}: {exc}"]})
            continue
        result = assess(symbol, rows, as_of_date=args.as_of_date,
                        lookback_days=args.lookback_days, threshold=args.threshold)
        result["cninfo_code"] = code
        results.append(result)

    failed = [row["symbol"] for row in results if row["status"] in ("failed", "insufficient_data")]
    complete = [row["symbol"] for row in results if row["status"] == "complete"]
    if not complete:
        # Nothing was assessed (all funds/foreign, or all channels failed): that is not
        # a complete run even when no symbol carries an explicit failure.
        status, detail = "insufficient_data", "no_symbol_assessed"
    elif failed:
        status, detail = "incomplete", "share_change_partially_assessed"
    else:
        status, detail = "complete", "share_change_assessed"
    if failed:
        errors.extend(f"{symbol}: share-change assessment unavailable" for symbol in failed)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "detail_status": detail,
        "decision_scope": DECISION_SCOPE,
        "as_of_date": args.as_of_date,
        "lookback_days": args.lookback_days,
        "threshold": args.threshold,
        "data_basis": {
            "channel": CHANNEL,
            "unit": "shares",
            "channel_unit": "万股 (multiplied by 10000)",
            "as_of_basis": "announcement_date",
            "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "query_window": {"start": start_date, "end": args.as_of_date},
        },
        "symbols": results,
        "errors": errors,
        "non_executable": True,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        target = Path(args.out).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    print(text)
    return 0 if status == "complete" else 2


if __name__ == "__main__":
    sys.exit(main())
