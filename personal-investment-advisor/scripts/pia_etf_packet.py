#!/usr/bin/env python3
"""Assemble and verify an ETF history-integrity packet from operator evidence.

Why this exists: ``history_integrity_gate.evaluate_history_integrity`` verifies a
packet, but nothing could *produce* one, so ETF history (and therefore ETF
volatility, tracking and risk contributions) was unreachable without hand-writing
JSON and mis-transcribing hashes.

Boundaries: this tool never invents an official corporate action and never derives
one from the price series.  The caller supplies the official events and the
provider's own event list, each with an evidence file or locator; the assembler
hashes the evidence, checks the packet's own consistency, runs the real gate
in-process, and refuses to publish a packet the gate did not verify.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from history_integrity_gate import evaluate_history_integrity  # noqa: E402

SCHEMA_VERSION = "pia_etf_packet_build_receipt_v1"
DECISION_SCOPE = "research_only"
REQUIRED_EVENT_FIELDS = ("event_type", "effective_date", "factor")


class PacketError(RuntimeError):
    pass


def iso_date(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise PacketError(f"{label} must be an ISO date, got {value!r}")
    try:
        datetime.date.fromisoformat(text)
    except ValueError as exc:
        raise PacketError(f"{label} is not a real date: {text}") from exc
    return text


def aware_datetime(value: Any, label: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PacketError(f"{label} must be a timezone-aware ISO datetime") from exc
    if parsed.utcoffset() is None:
        raise PacketError(f"{label} must be timezone-aware")
    return text


def hash_evidence(path: Path) -> str:
    if not path.is_file():
        raise PacketError(f"evidence artifact not found: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_events(
    events: Any,
    label: str,
    as_of_date: str,
    task_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (packet_events, evidence_bindings) for one event list."""

    if not isinstance(events, list):
        raise PacketError(f"{label} must be a list")
    packet_events: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        prefix = f"{label}[{index}]"
        if not isinstance(event, dict):
            raise PacketError(f"{prefix} must be an object")
        for field in REQUIRED_EVENT_FIELDS:
            if not isinstance(event.get(field), str) or not event[field].strip():
                raise PacketError(f"{prefix}.{field} must be a non-empty string")
        effective = iso_date(event["effective_date"], f"{prefix}.effective_date")
        if effective > as_of_date:
            raise PacketError(f"{prefix}.effective_date is after as_of_date")
        artifact = event.get("evidence_file")
        locator = event.get("evidence_locator")
        if not artifact and not locator:
            raise PacketError(
                f"{prefix} needs evidence_file or evidence_locator: an official event "
                "without a source is not evidence")
        binding = {"event_index": index, "event_type": event["event_type"].strip(),
                   "effective_date": effective}
        if artifact:
            evidence_path = (task_dir / artifact).resolve() if not Path(artifact).is_absolute() \
                else Path(artifact)
            binding["evidence_file"] = artifact
            binding["content_sha256"] = hash_evidence(evidence_path)
        else:
            if not str(locator).startswith(("http://", "https://", "sec://", "dataset://")):
                raise PacketError(
                    f"{prefix}.evidence_locator must be a public URL, sec:// or dataset:// locator")
            binding["evidence_locator"] = str(locator)
        packet_events.append({
            "event_type": event["event_type"].strip(),
            "effective_date": effective,
            "factor": event["factor"].strip(),
        })
        bindings.append(binding)
    return packet_events, bindings


def _build_tolerance(args: argparse.Namespace) -> dict[str, Any] | None:
    """Return the optional factor-tolerance block, or refuse an incomplete one.

    Tolerance is off unless the caller supplies a magnitude, a basis, a justification
    and a source locator; an unexplained tolerance would silently widen every
    comparison in the packet.
    """

    supplied = [getattr(args, "factor_tolerance", None), getattr(args, "tolerance_basis", None),
                getattr(args, "tolerance_justification", None),
                getattr(args, "tolerance_source", None)]
    if not any(value is not None for value in supplied):
        return None
    value = args.factor_tolerance
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise PacketError("--factor-tolerance must be a positive finite number")
    basis = str(args.tolerance_basis or "").strip().lower()
    if basis not in {"relative", "absolute"}:
        raise PacketError("--tolerance-basis must be relative or absolute")
    justification = str(args.tolerance_justification or "").strip()
    if not justification:
        raise PacketError("--tolerance-justification is required when a tolerance is used")
    source = str(args.tolerance_source or "").strip()
    if not source:
        raise PacketError("--tolerance-source is required when a tolerance is used")
    return {"basis": basis, "value": float(value), "justification": justification,
            "source_locator": source}


def build_packet(args: argparse.Namespace) -> int:
    task_dir = Path(args.task_dir).expanduser().resolve()
    evidence_path = Path(args.evidence_file).expanduser().resolve()
    if not evidence_path.is_file():
        raise PacketError(f"evidence file not found: {evidence_path}")
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise PacketError(f"evidence file is not valid JSON: {exc}") from exc
    if not isinstance(evidence, dict):
        raise PacketError("evidence file must be a JSON object")

    symbol = str(args.symbol or evidence.get("symbol") or "").strip().upper()
    if not symbol:
        raise PacketError("symbol is required")
    as_of_date = iso_date(args.as_of_date or evidence.get("as_of_date"), "as_of_date")
    coverage = evidence.get("official_coverage")
    if not isinstance(coverage, dict):
        raise PacketError("evidence file needs an official_coverage object")
    locator = str(coverage.get("source_locator") or "").strip()
    if not locator:
        raise PacketError("official_coverage.source_locator is required")
    retrieved_at = aware_datetime(coverage.get("retrieved_at"), "official_coverage.retrieved_at")
    control_count = coverage.get("control_query_count")
    if not isinstance(control_count, int) or isinstance(control_count, bool) or control_count < 0:
        raise PacketError("official_coverage.control_query_count must be a non-negative integer")
    control_query = coverage.get("control_query")
    if control_count > 0:
        if not isinstance(control_query, dict) or not str(control_query.get("symbol") or "").strip():
            raise PacketError(
                "official_coverage.control_query must name the control symbol that proved the "
                "channel responds (a control count alone is not auditable)")
        control_symbol = str(control_query["symbol"]).strip().upper()
        if control_symbol == symbol:
            raise PacketError("official_coverage.control_query.symbol must differ from the target symbol")
        if not str(control_query.get("channel_scope") or "").strip():
            raise PacketError(
                "official_coverage.control_query.channel_scope must state what the channel covers: "
                "a zero result only means 'no event' when the channel actually covers this instrument")

    official_events, official_bindings = normalize_events(
        evidence.get("official_events", []), "official_events", as_of_date, task_dir)
    provider_events, provider_bindings = normalize_events(
        evidence.get("provider_events", []), "provider_events", as_of_date, task_dir)

    packet = {
        "symbol": symbol,
        "asset_type": "etf",
        "as_of_date": as_of_date,
        "provider_source": str(args.provider_source or evidence.get("provider_source") or "").strip(),
        "provider_source_locator": str(args.provider_source_locator
                                       or evidence.get("provider_source_locator") or "").strip(),
        "provider_adjustment": str(args.provider_adjustment
                                   or evidence.get("provider_adjustment") or "").strip(),
        "official_coverage": {
            "source_locator": locator,
            "retrieved_at": retrieved_at,
            "coverage_status": "complete",
            "result_count": len(official_events),
            "control_query_count": control_count,
        },
        "official_events": official_events,
        "provider_events": provider_events,
    }
    tolerance = _build_tolerance(args)
    if tolerance is not None:
        packet["factor_tolerance"] = tolerance

    gate = evaluate_history_integrity(packet)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "decision_scope": DECISION_SCOPE,
        "symbol": symbol,
        "as_of_date": as_of_date,
        "evidence_source": str(evidence_path),
        "evidence_source_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        "official_event_count": len(official_events),
        "provider_event_count": len(provider_events),
        "official_event_evidence": official_bindings,
        "provider_event_evidence": provider_bindings,
        "control_query": control_query,
        "gate_status": gate.get("status"),
        "gate_detail_status": gate.get("detail_status"),
        "packet_verified": bool(gate.get("packet_verified")),
        "gate_errors": gate.get("errors") or [],
        "event_mismatches": gate.get("event_mismatches") or {},
        "factor_tolerance": tolerance,
        "tolerance_used": bool(gate.get("tolerance_used")),
        "note": ("packet_verified authorizes the packet only; yf.py still binds provider, "
                 "locator, adjustment and series end before technical metrics are emitted"),
    }

    if gate.get("packet_verified") or args.allow_unverified:
        packet_path = task_dir / "inputs" / f"history_integrity_{symbol.replace('.', '_')}.json"
        packet_path.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(packet, ensure_ascii=False, indent=2).encode("utf-8")
        with packet_path.open("wb" if args.force else "xb") as stream:
            stream.write(rendered)
        receipt["packet_file"] = str(packet_path)
        receipt["packet_sha256"] = hashlib.sha256(rendered).hexdigest()
        receipt["status"] = "complete" if gate.get("packet_verified") else "insufficient_data"
    else:
        receipt["status"] = "insufficient_data"
        receipt["packet_file"] = None
        receipt["note"] += ("; packet not written because the gate did not verify it "
                            "(use --allow-unverified to keep a diagnostic artifact)")

    receipt_path = task_dir / "out" / f"packet_receipt_{symbol.replace('.', '_')}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(json.dumps(receipt, ensure_ascii=False, indent=2).encode("utf-8"))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "complete" else 2


def derive_provider_events(args: argparse.Namespace) -> int:
    """Derive ``provider_events`` from the provider's own action series.

    The provider (yfinance) publishes dividends and splits on the adjusted series; those
    are the provider's *claims*, so they can be derived rather than hand-written — but
    they are rounded to the provider's precision, so the factor is quantised to the same
    number of decimals and the raw capture is stored next to the derivation.
    """

    import yfinance as yf  # imported lazily: only this subcommand needs the network

    task_dir = Path(args.task_dir).expanduser().resolve()
    as_of = iso_date(args.as_of_date, "--as-of-date")
    window_start = (datetime.date.fromisoformat(as_of)
                    - datetime.timedelta(days=max(1, args.window_days))).isoformat()
    try:
        actions = yf.Ticker(args.symbol).actions
    except Exception as exc:  # noqa: BLE001 - recorded as a channel failure
        raise PacketError(f"provider action feed unavailable: {type(exc).__name__}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    if actions is not None and not getattr(actions, "empty", True):
        for index, row in actions.iterrows():
            day = str(index)[:10]
            if not (window_start <= day <= as_of):
                continue
            dividend = _finite(row.get("Dividends"))
            split = _finite(row.get("Stock Splits"))
            if dividend is not None and dividend > 0:
                rows.append({"event_type": "dividend", "effective_date": day,
                             "factor": _quantize(dividend, args.amount_decimals),
                             "source_amount": dividend})
            if split is not None and split > 0 and split != 1.0:
                rows.append({"event_type": "split", "effective_date": day,
                             "factor": f"{_quantize(split, 6)}:1" if split > 1 else f"1:{_quantize(1.0 / split, 6)}",
                             "source_amount": split})
    events = [{key: value for key, value in row.items() if key != "source_amount"}
              for row in rows]
    # Deterministic ordering: the provider feed order is not part of the contract.
    events.sort(key=lambda event: (event["effective_date"], event["event_type"]))
    capture = {
        "schema_version": "pia_provider_actions_capture_v1",
        "symbol": args.symbol.strip().upper(),
        "as_of_date": as_of,
        "window_start": window_start,
        "amount_decimals": args.amount_decimals,
        "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "raw_action_count": int(len(actions)) if actions is not None else 0,
        "derived": rows,
    }
    target = (Path(args.out).expanduser().resolve() if args.out else
              task_dir / "raw" / f"provider_actions_{args.symbol.strip().upper()}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(capture, ensure_ascii=False, indent=2).encode("utf-8")
    target.write_bytes(rendered)
    receipt = {
        "schema_version": "pia_provider_event_derivation_v1",
        "status": "complete",
        "detail_status": "provider_events_derived",
        "decision_scope": DECISION_SCOPE,
        "symbol": capture["symbol"],
        "as_of_date": as_of,
        "window_start": window_start,
        "event_count": len(events),
        "events": events,
        "capture_file": str(target),
        "capture_sha256": hashlib.sha256(rendered).hexdigest(),
        "precision_note": (f"factors are quantised to {args.amount_decimals} decimals because the "
                           "provider publishes distributions at that precision; the raw amount is "
                           "kept in the capture"),
        "independence_note": ("both the provider feed and an exchange-derived feed may originate "
                              "from the same market-data family; a match proves provider "
                              "consistency, not that the distributions themselves are correct"),
    }
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


def derive_official_events(args: argparse.Namespace) -> int:
    """Derive ``official_events`` from a captured exchange/market-data dividend feed."""

    feed_path = Path(args.feed_file).expanduser().resolve()
    if not feed_path.is_file():
        raise PacketError(f"feed not found: {feed_path}")
    feed_bytes = feed_path.read_bytes()
    try:
        payload = json.loads(feed_bytes.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise PacketError(f"feed is not valid JSON: {exc}") from exc
    rows = ((payload or {}).get("data") or {}).get("dividends")
    rows = rows.get("rows") if isinstance(rows, dict) else rows
    if not isinstance(rows, list):
        raise PacketError("feed does not contain data.dividends.rows")
    as_of = iso_date(args.as_of_date, "--as-of-date")
    window_start = (datetime.date.fromisoformat(as_of)
                    - datetime.timedelta(days=max(1, args.window_days))).isoformat()
    events: list[dict[str, Any]] = []
    skipped: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_date = str(row.get("exOrEffDate") or "").strip()
        try:
            day = datetime.datetime.strptime(raw_date, "%m/%d/%Y").date().isoformat()
        except ValueError:
            skipped.append(f"unparsable date: {raw_date!r}")
            continue
        if not (window_start <= day <= as_of):
            continue
        amount = _parse_amount(row.get("amount"))
        if amount is None:
            skipped.append(f"unparsable amount on {day}: {row.get('amount')!r}")
            continue
        kind = str(row.get("type") or "cash").strip().lower()
        events.append({"event_type": "dividend" if kind == "cash" else kind,
                       "effective_date": day,
                       "factor": _quantize(amount, args.amount_decimals)})
    events.sort(key=lambda event: (event["effective_date"], event["event_type"]))
    task_dir = Path(args.task_dir).expanduser().resolve()
    target = (Path(args.out).expanduser().resolve() if args.out else
              task_dir / "raw" / f"official_events_{args.symbol.strip().upper()}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_version": "pia_official_event_derivation_v1",
        "status": "complete" if events else "insufficient_data",
        "detail_status": "official_events_derived" if events else "no_official_events_in_window",
        "decision_scope": DECISION_SCOPE,
        "symbol": args.symbol.strip().upper(),
        "as_of_date": as_of,
        "window_start": window_start,
        "event_count": len(events),
        "events": events,
        "skipped_rows": skipped,
        "feed_file": str(feed_path),
        "feed_sha256": hashlib.sha256(feed_bytes).hexdigest(),
        "precision_note": (f"amounts quantised to {args.amount_decimals} decimals to match the "
                           "provider's published precision"),
    }
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if events else 2


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _quantize(value: float, decimals: int) -> str:
    return f"{round(float(value), max(0, int(decimals))):.{max(0, int(decimals))}f}"


def _parse_amount(raw: Any) -> float | None:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    text = str(raw or "").replace("$", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


CHANNEL_ADAPTERS: dict[str, dict[str, Any]] = {
    "cninfo": {
        "purpose": "A-share issuer disclosure (cninfo hisAnnouncement API)",
        "instrument_classes": {"stock"},
        "locator": "http://www.cninfo.com.cn/new/hisAnnouncement/query",
    },
    "nasdaq": {
        "purpose": "Exchange dividend feed for US listed funds and equities",
        "instrument_classes": {"etf", "stock"},
        "locator": "https://api.nasdaq.com/api/quote/{symbol}/dividends?assetclass=etf",
    },
}
CNINFO_ORGANIZATION_IDS = {
    "510300": "jjjl0000035",
    "159934": "jjjl0000041",
    "159072": "jjjl0000063",
    "601899": "9900004143",
    "603259": "9900035584",
    "603986": "9900026561",
    "688002": "9900038939",
    "300253": "9900012530",
    "300502": "9900026455",
}


def channel_probe_verdict(target_count: int | None, control_count: int | None, *,
                          same_class_control: bool, channel_available: bool) -> tuple[str, str]:
    """Return (verdict, coverage_basis) for a zero/non-zero result.

    A zero result only means "no events" when a control of the *same instrument
    class* proved the channel answers for that class.  Anything else is an unproven
    coverage claim and must block rather than pass.
    """

    if not channel_available or target_count is None or control_count is None:
        return "channel_unavailable", "none"
    basis = "same_instrument_class_control" if same_class_control else "cross_class_control_weak"
    if target_count > 0:
        return "covered_with_events", basis
    if control_count > 0 and same_class_control:
        return "covered_zero_events", basis
    return "coverage_unproven", basis


def _fetch_cninfo(code: str, task_dir: Path, window: str, *,
                  attempts: int = 2) -> tuple[bytes, int, dict[str, Any]]:
    """Query cninfo, retrying once when the request is answered by an empty shell.

    A 165-byte body with ``totalRecordNum = 0`` and ``announcements = null`` is returned
    for throttled or unsatisfiable requests.  It looks exactly like a legitimate zero,
    so it must never be counted as one: the adapter retries once and, if the shell
    persists, marks the capture inconclusive.
    """

    import urllib.parse
    import urllib.request

    organization = CNINFO_ORGANIZATION_IDS.get(code, "")
    column = "sse" if code.startswith(("5", "6", "9")) else "szse"
    payload = {
        "pageNum": 1, "pageSize": 50, "column": column, "tabName": "fulltext", "plate": "",
        "stock": f"{code},{organization}" if organization else code,
        "searchkey": "", "secid": "", "category": "", "trade": "", "seDate": window,
        "sortName": "", "sortType": "", "isHLtitle": "true",
    }
    details: dict[str, Any] = {
        "organization_id": organization or None,
        "query_scope": "code_and_organization" if organization else "code_only",
    }
    raw = b""
    for attempt in range(1, max(1, attempts) + 1):
        request = urllib.request.Request(
            CHANNEL_ADAPTERS["cninfo"]["locator"],
            data=urllib.parse.urlencode(payload).encode(),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                     "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
                     "X-Requested-With": "XMLHttpRequest"},
            method="POST",
        )
        raw = urllib.request.urlopen(request, timeout=45).read()
        parsed = json.loads(raw.decode("utf-8", "replace"))
        total = parsed.get("totalRecordNum")
        announcements = parsed.get("announcements")
        empty_shell = (total == 0 and announcements is None and len(raw) < 300)
        details["attempts"] = attempt
        details["empty_shell"] = empty_shell
        if not empty_shell:
            count = int(total) if isinstance(total, int) else len(announcements or [])
            details["rows_parsed"] = isinstance(total, int) or isinstance(announcements, list)
            return raw, count, details
    details["rows_parsed"] = True
    return raw, 0, details


def _fetch_nasdaq(symbol: str, task_dir: Path, window: str) -> tuple[bytes, int, dict[str, Any]]:
    import urllib.request

    url = CHANNEL_ADAPTERS["nasdaq"]["locator"].format(symbol=symbol)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 dhls-scout/1.0",
                                                   "Accept": "application/json"})
    raw = urllib.request.urlopen(request, timeout=60).read()
    parsed = json.loads(raw.decode("utf-8", "replace"))
    rows = ((parsed or {}).get("data") or {}).get("dividends")
    rows = rows.get("rows") if isinstance(rows, dict) else rows
    # A malformed or absent row list is a parse failure, not an empty history.
    rows_parsed = isinstance(rows, list)
    return raw, len(rows) if rows_parsed else 0, {"rows_parsed": rows_parsed}


def coverage_probe(args: argparse.Namespace) -> int:
    """Prove (or refuse to claim) that a channel covers an instrument class.

    Zero events are only acceptable when a *same-class* control proved the channel
    answers for that class.  This turns "the provider reported no actions" into a
    definite pass-or-block result instead of an open question.
    """

    channel = str(args.channel or "").strip().lower()
    if channel not in CHANNEL_ADAPTERS:
        raise PacketError(f"unknown channel {channel!r}; known: {', '.join(sorted(CHANNEL_ADAPTERS))}")
    task_dir = Path(args.task_dir).expanduser().resolve()
    as_of = iso_date(args.as_of_date, "--as-of-date")
    window_start = (datetime.date.fromisoformat(as_of)
                    - datetime.timedelta(days=max(1, args.window_days))).isoformat()
    cninfo_window = window_start.replace("-", "~") + "~" + as_of.replace("-", "~")
    fetcher = _fetch_cninfo if channel == "cninfo" else _fetch_nasdaq

    captures: list[dict[str, Any]] = []
    availability = True
    counts: dict[str, int | None] = {}
    quality_notes: list[str] = []
    for role, symbol in (("target", args.target), ("control", args.control)):
        code = str(symbol).split(".")[0]
        try:
            raw, count, details = fetcher(code, task_dir, cninfo_window)
        except Exception as exc:  # noqa: BLE001 - recorded as a channel failure
            availability = False
            counts[role] = None
            captures.append({"role": role, "symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if details.get("rows_parsed") is False:
            availability = False
            counts[role] = None
            captures.append({"role": role, "symbol": symbol, "count": 0,
                             "error": "response rows were not parseable; treated as a channel failure",
                             "details": details})
            continue
        name = f"coverage_{channel}_{role}_{code}.json"
        path = task_dir / "raw" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        counts[role] = count
        if channel == "cninfo" and details.get("query_scope") == "code_only" and count == 0:
            quality_notes.append(
                f"{role} {symbol}: queried by code only (organization id unknown), so a zero "
                "result cannot be read as 'no events'")
        if details.get("empty_shell"):
            # Retried once and still answered by the empty shell: inconclusive.
            quality_notes.append(
                f"{role} {symbol}: cninfo answered with the empty shell after "
                f"{details.get('attempts')} attempts; the zero is inconclusive, not evidence")
            counts[role] = None
            availability = False
        captures.append({"role": role, "symbol": symbol, "count": count,
                         "file": f"raw/{name}",
                         "sha256": hashlib.sha256(raw).hexdigest(),
                         "details": details})

    declared_classes = CHANNEL_ADAPTERS[channel]["instrument_classes"]
    same_class = (str(getattr(args, "target_class", "") or "").strip().lower()
                  in declared_classes and
                  str(getattr(args, "control_class", "") or "").strip().lower()
                  in declared_classes and
                  str(getattr(args, "target_class", "")).strip().lower()
                  == str(getattr(args, "control_class", "")).strip().lower())
    verdict, basis = channel_probe_verdict(counts.get("target"), counts.get("control"),
                                          same_class_control=same_class,
                                          channel_available=availability)
    if quality_notes and verdict.startswith("covered"):
        # An under-scoped query cannot support a 'no events' conclusion.
        verdict, basis = "coverage_unproven", basis
    official_coverage = None
    if verdict in {"covered_zero_events", "covered_with_events"}:
        official_coverage = {
            "source_locator": CHANNEL_ADAPTERS[channel]["locator"],
            "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "control_query_count": counts.get("control") or 0,
            "control_query": {"symbol": str(args.control), "channel_scope": args.channel_scope},
        }
    receipt = {
        "schema_version": "pia_channel_coverage_probe_v1",
        "status": "complete" if verdict.startswith("covered") else "insufficient_data",
        "detail_status": verdict,
        "decision_scope": DECISION_SCOPE,
        "channel": channel,
        "target": str(args.target),
        "control": str(args.control),
        "window": [window_start, as_of],
        "target_count": counts.get("target"),
        "control_count": counts.get("control"),
        "coverage_basis": basis,
        "channel_scope": args.channel_scope,
        "captures": captures,
        "query_quality_notes": quality_notes,
        "official_coverage": official_coverage,
        "note": ("a zero result is only accepted as 'no events' when a same-class control "
                 "proved the channel answers for that class; otherwise the verdict is "
                 "coverage_unproven and the packet must not be assembled"),
    }
    target = (Path(args.out).expanduser().resolve() if args.out else
              task_dir / "out" / f"coverage_probe_{channel}_{str(args.target).split('.')[0]}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(json.dumps(receipt, ensure_ascii=False, indent=2).encode("utf-8"))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "complete" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble, verify or derive an ETF history-integrity packet."
    )
    subparsers = parser.add_subparsers(dest="subcommand")
    assemble = subparsers.add_parser(
        "assemble", help="Assemble and verify a packet from operator evidence.")
    assemble.add_argument("--evidence-file", required=True)
    assemble.add_argument("--task-dir", required=True)
    assemble.add_argument("--symbol")
    assemble.add_argument("--as-of-date")
    assemble.add_argument("--provider-source")
    assemble.add_argument("--provider-source-locator")
    assemble.add_argument("--provider-adjustment")
    assemble.add_argument("--allow-unverified", action="store_true")
    assemble.add_argument("--force", action="store_true")
    assemble.add_argument(
        "--factor-tolerance", type=float,
        help="Optional positive factor tolerance; requires --tolerance-basis, "
             "--tolerance-justification and --tolerance-source. Default is exact equality.",
    )
    assemble.add_argument("--tolerance-basis", choices=("relative", "absolute"))
    assemble.add_argument("--tolerance-justification")
    assemble.add_argument("--tolerance-source")
    provider = subparsers.add_parser(
        "derive-provider-events",
        help="Derive provider_events from the provider's own dividend/split series.",
    )
    provider.add_argument("--symbol", required=True)
    provider.add_argument("--as-of-date", required=True)
    provider.add_argument("--task-dir", required=True)
    provider.add_argument("--window-days", type=int, default=400)
    provider.add_argument("--amount-decimals", type=int, default=3)
    provider.add_argument("--out")
    official = subparsers.add_parser(
        "derive-official-events",
        help="Derive official_events from a captured exchange dividend feed.",
    )
    official.add_argument("--symbol", required=True)
    official.add_argument("--feed-file", required=True)
    official.add_argument("--as-of-date", required=True)
    official.add_argument("--task-dir", required=True)
    official.add_argument("--window-days", type=int, default=400)
    official.add_argument("--amount-decimals", type=int, default=3)
    official.add_argument("--out")
    probe = subparsers.add_parser(
        "coverage-probe",
        help="Prove whether a channel covers an instrument class (zero-result control).",
    )
    probe.add_argument("--channel", required=True,
                       help="Channel adapter id (e.g. cninfo, nasdaq).")
    probe.add_argument("--target", required=True, help="Symbol whose zero/records are in question.")
    probe.add_argument("--control", required=True,
                       help="Different symbol used as the control query.")
    probe.add_argument("--target-class", help="Instrument class of the target (stock/etf).")
    probe.add_argument("--control-class", help="Instrument class of the control (stock/etf).")
    probe.add_argument("--channel-scope", required=True,
                       help="Plain-language statement of what the channel covers.")
    probe.add_argument("--as-of-date", required=True)
    probe.add_argument("--task-dir", required=True)
    probe.add_argument("--window-days", type=int, default=400)
    probe.add_argument("--out")
    return parser


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(argv if argv is not None else sys.argv[1:])
    if effective_argv in (["-h"], ["--help"]):
        build_parser().print_help()
        return 0
    if not effective_argv or effective_argv[0].startswith("-"):
        # Keep the original flag-only invocation working as the default action.
        effective_argv = ["assemble", *effective_argv]
    args = build_parser().parse_args(effective_argv)
    try:
        if args.subcommand == "derive-provider-events":
            return derive_provider_events(args)
        if args.subcommand == "derive-official-events":
            return derive_official_events(args)
        if args.subcommand == "coverage-probe":
            return coverage_probe(args)
        return build_packet(args)
    except PacketError as exc:
        print(json.dumps({"status": "failed", "detail_status": "packet_input_invalid",
                          "decision_scope": DECISION_SCOPE, "errors": [str(exc)]},
                         ensure_ascii=False, indent=2))
        return 3


def main_unused_legacy(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble and verify an ETF history-integrity packet."
    )


def assemble_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble and verify an ETF history-integrity packet."
    )
    parser.add_argument("--evidence-file", required=True)
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--symbol")
    parser.add_argument("--as-of-date")
    parser.add_argument("--provider-source")
    parser.add_argument("--provider-source-locator")
    parser.add_argument("--provider-adjustment")
    parser.add_argument("--allow-unverified", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def _legacy_main(argv: list[str] | None = None) -> int:
    args = assemble_parser().parse_args(argv)
    try:
        return build_packet(args)
    except PacketError as exc:
        print(json.dumps({"status": "failed", "detail_status": "packet_input_invalid",
                          "decision_scope": DECISION_SCOPE, "errors": [str(exc)]},
                         ensure_ascii=False, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
