#!/usr/bin/env python3
"""Write an isolated FX-refreshed portfolio snapshot for downstream gates.

Why this exists: current-weight calculation fails closed when the portfolio's
exchange-rate snapshot is older than 72 hours, and no command could produce a
refreshed *derived* snapshot -- the original holdings file must never be edited.
This script fetches a dated FX observation (or consumes one captured earlier by
``yf.py``), writes ``<task-dir>/inputs/positions_fx_snapshot.json``, and records a
receipt binding the original file hash, the derived file hash, the FX
observation hash and a ``dataset://`` manifest so builders and gates can consume
the snapshot offline.

Boundaries: never modifies the input; never invents a rate; a currency whose
observation is missing or older than ``--max-fx-age-hours`` fails the run instead
of falling back to a default rate.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from portfolio_loader import validate_portfolio_payload  # noqa: E402

SCHEMA_VERSION = "pia_refresh_receipt_v1"
DERIVED_FILENAME = "positions_fx_snapshot.json"
DEFAULT_MAX_FX_AGE_HOURS = 72.0
FX_PROBE_TIMEOUT_SECONDS = 240
DECISION_SCOPE = "research_only"


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def yahoo_fx_symbol(currency: str, base_currency: str) -> str:
    """Map a quote currency to the Yahoo pair used by the existing snapshots.

    The portfolio file already carries USD/CNY as ``CNY=X`` and HKD/CNY as
    ``HKDCNY=X``; the USD case is the provider's inverted-pair convention and is
    reproduced here rather than guessed per currency.
    """

    currency = currency.upper()
    base_currency = base_currency.upper()
    if currency == base_currency:
        return ""
    if currency == "USD":
        return f"{base_currency}=X"
    return f"{currency}{base_currency}=X"


def active_non_cash_currencies(payload: dict[str, Any]) -> list[str]:
    base = str(payload.get("base_currency") or "").strip().upper()
    currencies = {
        str(position.get("currency") or "").strip().upper()
        for position in payload.get("positions", [])
        if isinstance(position, dict)
        and not _is_cash(position)
        and float(position.get("quantity") or 0) > 0
    }
    currencies.discard("")
    currencies.discard(base)
    return sorted(currencies)


def _is_cash(position: dict[str, Any]) -> bool:
    symbol = str(position.get("symbol") or "").strip().upper()
    marker = str(position.get("market") or "").strip().upper()
    asset_type = str(position.get("asset_type") or "").strip().lower()
    return asset_type == "cash" or marker == "CASH" or symbol.startswith("CASH")


def parse_fx_capture(raw: bytes, symbol: str) -> dict[str, Any]:
    """Extract the last valid dated observation from a ``yf.py`` FX capture."""

    payload = json.loads(raw.decode("utf-8"))
    records = payload if isinstance(payload, list) else [payload]
    record = next(
        (item for item in records if isinstance(item, dict)
         and str(item.get("symbol") or "").upper() == symbol.upper()),
        None,
    )
    if record is None:
        raise ValueError(f"capture does not contain symbol {symbol}")
    history = record.get("history") or []
    usable = [
        row for row in history
        if isinstance(row, dict) and isinstance(row.get("Close"), (int, float))
        and float(row["Close"]) > 0 and row.get("Date")
    ]
    if not usable:
        raise ValueError(f"capture contains no usable Close observation for {symbol}")
    last = usable[-1]
    info = record.get("info") or {}
    return {
        "rate": float(last["Close"]),
        "observation_date": str(last["Date"])[:10],
        "market_state": info.get("marketState"),
        "regular_market_time": info.get("regularMarketTime"),
    }


def _failure_reason(stdout: bytes, stderr: bytes, exit_code: int) -> tuple[str, bool]:
    """Return (reason, is_transient) for a failed FX probe.

    The child writes its structured error to stdout (empty stderr is normal), so a
    bare "exit 2" previously discarded the only machine-readable cause.  A reason
    that names invalid input or a contract problem is never retried; a missing or
    connection-class reason is treated as transient so the caller may retry once.
    """

    detail = ""
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        parts = [str(payload.get("detail_status") or payload.get("status") or "")]
        errors = payload.get("errors")
        if isinstance(errors, list):
            parts.extend(str(item) for item in errors[:3])
        detail = "; ".join(part for part in parts if part)
    if not detail:
        detail = stderr.decode("utf-8", "replace").strip()[:200]
    lowered = detail.lower()
    non_transient = ("invalid_input", "contract", "not found", "signature", "schema", "unsupported")
    is_transient = not any(token in lowered for token in non_transient)
    if not detail:
        detail = f"no structured reason (exit {exit_code})"
    return detail, is_transient


def fetch_fx_capture(symbol: str, cache_dir: Path | None, *, attempts: int = 2) -> tuple[bytes, str]:
    """Run the documented FX probe, bounded-retrying transient failures once.

    A deterministic contract failure is not retried; the reported reason always
    includes the child's structured error so a failure is diagnosable without a
    second manual run.
    """

    command = [
        sys.executable, "-B", str(SCRIPT_DIR / "yf.py"), symbol,
        "--price-only", "--period", "5d", "--lean", "--json",
    ]
    if cache_dir is not None:
        command.extend(["--cache-dir", str(cache_dir)])
    last_reason = ""
    for attempt in range(1, max(1, attempts) + 1):
        completed = subprocess.run(
            command, capture_output=True, timeout=FX_PROBE_TIMEOUT_SECONDS, check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            return completed.stdout, " ".join(command) + (f" [attempts={attempt}]" if attempt > 1 else "")
        reason, is_transient = _failure_reason(completed.stdout, completed.stderr, completed.returncode)
        last_reason = reason
        if not is_transient or attempt == max(1, attempts):
            break
    raise RuntimeError(f"FX probe failed for {symbol}: {last_reason}")


def build_snapshot(
    original: dict[str, Any],
    base_currency: str,
    resolved: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    derived = copy.deepcopy(original)
    derived.setdefault("exchange_rates", {})
    derived.setdefault("exchange_rate_metadata", {})
    derived["exchange_rates"][base_currency] = 1.0
    for currency, record in resolved.items():
        derived["exchange_rates"][currency] = record["rate"]
        derived["exchange_rate_metadata"][currency] = {
            "pair": record["pair"],
            "as_of": record["as_of"],
            "source": "Yahoo Finance via yfinance (isolated FX refresh, this task)",
            "source_locator": record["source_locator"],
            "retrieved_at": record["retrieved_at"],
            "content_sha256": record["content_sha256"],
            "price_convention": f"{base_currency}_per_{currency}",
            "observation_field": "history[-1].Close",
            "market_state": record.get("market_state"),
        }
    return derived


def write_new_file(path: Path, payload: dict[str, Any], force: bool) -> str:
    """Write the snapshot and return the SHA-256 of the exact bytes on disk.

    Bytes are written in binary mode: text mode applies newline translation on
    Windows, which would make the recorded hash disagree with the file.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    mode = "wb" if force else "xb"
    with path.open(mode) as stream:
        stream.write(rendered)
    return sha256_bytes(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write an isolated FX-refreshed portfolio snapshot."
    )
    parser.add_argument("--positions-file", required=True)
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--cache-dir")
    parser.add_argument("--fx-observation-file")
    parser.add_argument(
        "--fx-pair", action="append", default=[],
        help="Explicit currency=yahoo-symbol override, repeatable (e.g. USD=CNY=X).",
    )
    parser.add_argument("--max-fx-age-hours", type=float, default=DEFAULT_MAX_FX_AGE_HOURS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    positions_path = Path(args.positions_file).expanduser().resolve()
    task_dir = Path(args.task_dir).expanduser().resolve()
    derived_path = task_dir / "inputs" / DERIVED_FILENAME
    receipt_path = task_dir / "out" / "refresh_receipt.json"

    errors: list[str] = []
    if not positions_path.is_file():
        errors.append(f"positions file not found: {positions_path}")
    if derived_path == positions_path:
        errors.append("derived snapshot would overwrite the positions input")
    if errors:
        print(json.dumps({"status": "failed", "detail_status": "invalid_input",
                          "errors": errors, "decision_scope": DECISION_SCOPE},
                         ensure_ascii=False, indent=2))
        return 3

    original_bytes = positions_path.read_bytes()
    original_sha = sha256_bytes(original_bytes)
    try:
        original = json.loads(original_bytes.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "detail_status": "unreadable_positions",
                          "errors": [f"{type(exc).__name__}: {exc}"],
                          "decision_scope": DECISION_SCOPE}, ensure_ascii=False, indent=2))
        return 3

    contract_errors = validate_portfolio_payload(original)
    required = active_non_cash_currencies(original)
    # An incomplete or stale FX block is exactly what this command repairs, so
    # errors that concern only the currencies about to be replaced are recorded
    # and healed instead of blocking the refresh.  Every other contract error
    # still fails closed.
    repairable_markers = tuple(
        f"exchange_rates.{currency}" for currency in required
    ) + tuple(
        f"exchange_rate_metadata.{currency}" for currency in required
    )
    healed_errors: list[str] = []
    blocking_errors: list[str] = []
    for error in contract_errors:
        (healed_errors if any(marker in error for marker in repairable_markers)
         else blocking_errors).append(error)
    if blocking_errors:
        print(json.dumps({"status": "failed", "detail_status": "positions_contract_failed",
                          "errors": blocking_errors[:10],
                          "decision_scope": DECISION_SCOPE}, ensure_ascii=False, indent=2))
        return 3

    base_currency = str(original.get("base_currency") or "").strip().upper()
    overrides = {}
    for item in args.fx_pair:
        if "=" not in item:
            errors.append(f"--fx-pair expects currency=yahoo-symbol, got {item!r}")
            continue
        currency, symbol = item.split("=", 1)
        overrides[currency.strip().upper()] = symbol.strip()
    if errors:
        print(json.dumps({"status": "failed", "detail_status": "invalid_arguments",
                          "errors": errors, "decision_scope": DECISION_SCOPE},
                         ensure_ascii=False, indent=2))
        return 3

    capture_bytes = None
    capture_source = None
    if args.fx_observation_file:
        capture_path = Path(args.fx_observation_file).expanduser().resolve()
        if not capture_path.is_file():
            print(json.dumps({"status": "insufficient_data",
                              "detail_status": "fx_capture_missing",
                              "errors": [f"fx observation file not found: {capture_path}"],
                              "decision_scope": DECISION_SCOPE},
                             ensure_ascii=False, indent=2))
            return 2
        capture_bytes = capture_path.read_bytes()
        capture_source = str(capture_path)

    cache_dir = Path(args.cache_dir).expanduser().resolve() if args.cache_dir else None
    if cache_dir is not None:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(json.dumps({"status": "failed", "detail_status": "cache_dir_unusable",
                              "errors": [f"{type(exc).__name__}: {exc}"],
                              "decision_scope": DECISION_SCOPE},
                             ensure_ascii=False, indent=2))
            return 3

    resolved: dict[str, dict[str, Any]] = {}
    captures: dict[str, bytes] = {}
    unresolved: list[str] = []
    max_age_seconds = float(args.max_fx_age_hours) * 3600.0
    now = datetime.datetime.now(datetime.timezone.utc)
    for currency in required:
        symbol = overrides.get(currency) or yahoo_fx_symbol(currency, base_currency)
        if not symbol:
            unresolved.append(f"{currency}: no FX pair can be derived")
            continue
        try:
            raw = capture_bytes if capture_bytes is not None else fetch_fx_capture(symbol, cache_dir)[0]
            observation = parse_fx_capture(raw, symbol)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            unresolved.append(f"{currency}: {type(exc).__name__}: {exc}")
            continue
        observed_at = datetime.datetime.fromisoformat(f"{observation['observation_date']}T00:00:00+00:00")
        age_seconds = (now - observed_at).total_seconds()
        if age_seconds > max_age_seconds:
            unresolved.append(
                f"{currency}: observation {observation['observation_date']} is "
                f"{age_seconds / 3600.0:.1f}h old, over the {args.max_fx_age_hours}h limit"
            )
            continue
        resolved[currency] = {
            "pair": f"{currency}/{base_currency}",
            "rate": observation["rate"],
            "as_of": observation["observation_date"],
            "age_seconds": round(age_seconds, 3),
            "max_age_seconds": max_age_seconds,
            "market_state": observation.get("market_state"),
            "content_sha256": sha256_bytes(raw),
            "source_locator": f"dataset://pia/tasks/{task_dir.name}/raw/fx_{currency}_{base_currency}.json",
            "retrieved_at": now.isoformat(),
        }
        captures[currency] = raw

    if unresolved:
        print(json.dumps({
            "status": "insufficient_data",
            "detail_status": "fx_observation_unavailable",
            "errors": unresolved,
            "required_currencies": required,
            "resolved_currencies": sorted(resolved),
            "decision_scope": DECISION_SCOPE,
        }, ensure_ascii=False, indent=2))
        return 2

    derived = build_snapshot(original, base_currency, resolved)
    if derived_path.exists() and not args.force:
        print(json.dumps({
            "status": "failed",
            "detail_status": "derived_snapshot_exists",
            "errors": [f"{derived_path} already exists; pass --force to overwrite"],
            "decision_scope": DECISION_SCOPE,
        }, ensure_ascii=False, indent=2))
        return 3

    for currency in resolved:
        raw_dir = task_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"fx_{currency}_{base_currency}.json").write_bytes(captures[currency])

    derived_sha = write_new_file(derived_path, derived, args.force)

    original_after = sha256_bytes(positions_path.read_bytes())
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision_scope": DECISION_SCOPE,
        "status": "complete",
        "positions_file": str(positions_path),
        "positions_sha256_before": original_sha,
        "positions_sha256_after": original_after,
        "original_unchanged": original_after == original_sha,
        "derived_snapshot": str(derived_path),
        "derived_sha256": derived_sha,
        "base_currency": base_currency,
        "max_fx_age_hours": args.max_fx_age_hours,
        "fx_capture_source": capture_source or "yf.py subprocess per currency",
        "healed_contract_errors": healed_errors,
        "resolved": resolved,
        "dataset_manifest": [
            {"locator": record["source_locator"],
             "file": f"raw/fx_{currency}_{base_currency}.json",
             "sha256": record["content_sha256"]}
            for currency, record in resolved.items()
        ],
    }
    if not receipt["original_unchanged"]:
        receipt["status"] = "failed"
        receipt["errors"] = ["positions file changed during the refresh"]
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(json.dumps(receipt, ensure_ascii=False, indent=2).encode("utf-8"))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
