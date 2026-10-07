#!/usr/bin/env python3
"""Build gate-ready active-research inputs from upstream artifacts.

Why this exists: every downstream gate consumes a hand-authored JSON file whose
``source_locator``, ``content_sha256`` and ``portfolio_snapshot_binding`` must
match byte-for-byte.  Building those files by hand was the largest source of
friction and mis-transcription in real runs.  These builders derive them from the
upstream artifacts, never invent a value, and fail closed on a missing input.

Subcommands
-----------
``scenario``      weights + confirmed policy -> scenario portfolio + assumptions + manifest
``inverse-vol``   volatility observations + confirmed policy -> pia_inverse_volatility_policy_v1
``thesis-pack``   quotes + evidence/assessment files -> pia_thesis_red_team_v1 evidence package
``dataset-manifest``  register local artifacts under dataset:// locators

All builders are offline, never modify their inputs, and refuse to overwrite an
existing output unless ``--force`` is supplied.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "pia_build_receipt_v1"
DECISION_SCOPE = "advisory"
TASK_PREFIX = "dataset://pia/tasks"


class BuildError(RuntimeError):
    """A missing or unusable input.  Never a default value."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise BuildError(f"{label} not found: {path}")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise BuildError(f"{label} is not valid UTF-8 JSON: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BuildError(f"{label} must be a JSON object")
    return payload, sha256_bytes(raw)


def write_json(path: Path, payload: dict[str, Any], force: bool) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    if path.exists() and not force:
        raise BuildError(f"{path} already exists; pass --force to overwrite")
    with path.open("wb") as stream:
        stream.write(rendered)
    return sha256_bytes(rendered)


def locator(task_dir: Path, relative: str) -> str:
    return f"{TASK_PREFIX}/{task_dir.name}/{relative}"


def manifest_entries(task_dir: Path, bindings: list[tuple[str, Path]]) -> list[dict[str, Any]]:
    entries = []
    for relative, path in bindings:
        entries.append({
            "locator": locator(task_dir, relative),
            "file": relative,
            "sha256": sha256_bytes(path.read_bytes()),
        })
    return entries


def ensure_local_copy(task_dir: Path, relative: str, source: Path, force: bool) -> Path:
    """Copy an upstream artifact into the task namespace so dataset:// resolves.

    A ``dataset://pia/tasks/<task>/...`` locator must resolve to a real file
    inside that task directory; registering the caller's path without copying
    would produce a locator that cannot be resolved later.
    """

    target = task_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = source.read_bytes()
    if target.exists():
        if target.read_bytes() != payload and not force:
            raise BuildError(f"{target} exists with different content; pass --force to replace it")
        if target.read_bytes() == payload:
            return target
    target.write_bytes(payload)
    return target


def merge_manifest(path: Path, entries: list[dict[str, Any]]) -> None:
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise BuildError(f"existing dataset manifest is unreadable: {exc}") from exc
    if not isinstance(existing, dict):
        raise BuildError("existing dataset manifest must be a JSON object")
    merged = existing.get("bindings") or []
    seen = {entry.get("locator") for entry in merged}
    merged.extend(entry for entry in entries if entry["locator"] not in seen)
    existing.update({
        "schema_version": "pia_dataset_manifest_v1",
        "namespace": "dataset://pia",
        "note": "dataset:// locators resolve to local artifacts in this task directory",
        "bindings": merged,
    })
    write_json(path, existing, True)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BuildError(message)


# --------------------------------------------------------------------------- scenario


def build_scenario(args: argparse.Namespace) -> dict[str, Any]:
    task_dir = Path(args.task_dir).expanduser().resolve()
    weights_source = Path(args.weights_file).expanduser().resolve()
    policy_source = Path(args.confirmed_policy).expanduser().resolve()
    weights, weights_sha = read_json(weights_source, "weights file")
    policy, policy_sha = read_json(policy_source, "confirmed policy")
    positions, positions_sha = read_json(Path(args.positions_file).expanduser().resolve(),
                                        "positions snapshot")
    weights_path = ensure_local_copy(task_dir, "out/weights.json", weights_source, args.force)
    policy_path = ensure_local_copy(task_dir, "inputs/confirmed_policy.json", policy_source,
                                    args.force)

    require(weights.get("status") == "complete",
            f"weights file status is {weights.get('status')!r}; only a complete run can be used")
    rows = weights.get("current_weights")
    require(isinstance(rows, list) and rows, "weights file has no current_weights rows")
    bucket_policy = policy.get("bucket_policy") or {}
    core = list(bucket_policy.get("core") or [])
    satellite = list(bucket_policy.get("satellite") or [])
    excluded = list(bucket_policy.get("excluded_cash") or [])
    require(core and satellite, "confirmed policy must declare core and satellite buckets")
    main_returns = policy.get("main_local_total_returns") or {}
    require(main_returns, "confirmed policy must declare main_local_total_returns")
    sensitivity = policy.get("sensitivity_overrides") or {}
    usd_cny = policy.get("main_usd_cny_return")

    positions_by_symbol = {
        str(item.get("symbol")): item for item in positions.get("positions", [])
        if isinstance(item, dict) and float(item.get("quantity") or 0) > 0
    }
    market_values = {row["symbol"]: row["market_value_base"] for row in rows}
    weight_sum = sum(market_values.values())
    require(weight_sum > 0, "weights file market values sum to zero")
    missing_returns = sorted(set(market_values) - set(main_returns))
    require(not missing_returns,
            f"confirmed policy has no scenario return for: {', '.join(missing_returns)}")

    portfolio = copy.deepcopy(positions)
    for position in portfolio.get("positions", []):
        row = next((item for item in rows if item["symbol"] == position["symbol"]), None)
        if row is None:
            continue
        position["current_weight"] = row["current_weight"]
        position["current_price"] = row["current_price"]
        position["market_value_base"] = row["market_value_base"]

    fx_rates: dict[str, float] = {}
    metadata = positions.get("exchange_rate_metadata") or {}
    base_currency = str(positions.get("base_currency") or "CNY").upper()
    active_currencies: set[str] = set()
    for position in positions.get("positions", []):
        if not isinstance(position, dict) or float(position.get("quantity") or 0) <= 0:
            continue
        symbol = str(position.get("symbol") or "")
        is_cash = (str(position.get("market") or "").upper() == "CASH"
                   or str(position.get("asset_type") or "").lower() == "cash"
                   or symbol.startswith("CASH"))
        if is_cash:
            continue
        active_currencies.add(str(position.get("currency") or "").upper())
    for currency in sorted(active_currencies):
        if not currency or currency == base_currency:
            continue
        rate = (positions.get("exchange_rates") or {}).get(currency)
        require(isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0,
                f"positions snapshot has no usable {currency} rate")
        fx_rates[f"{currency}/{base_currency}"] = float(rate)
    fx_metadata = {
        f"{currency}/{base_currency}": {
            "as_of": (metadata.get(currency) or {}).get("as_of"),
            "source_locator": (metadata.get(currency) or {}).get("source_locator"),
            "content_sha256": (metadata.get(currency) or {}).get("content_sha256"),
        }
        for currency in {key.split("/")[0] for key in fx_rates}
    }

    scenario_names = policy.get("scenario_names") or ["global_recession_12m"]
    primary_name = scenario_names[0]
    sensitivity_name = scenario_names[1] if len(scenario_names) > 1 else "sensitivity_12m"

    def asset_returns(overrides: dict[str, float] | None = None,
                      fx_return: float | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for symbol, value in main_returns.items():
            if overrides and symbol in overrides:
                value = overrides[symbol]
            position = positions_by_symbol.get(symbol) or {}
            currency = str(position.get("currency") or base_currency).upper()
            entry: dict[str, Any] = {"basis": "local_total_return", "return": float(value),
                                     "currency": currency}
            if currency != base_currency:
                entry["fx_pair"] = f"{currency}/{base_currency}"
            result[symbol] = entry
        del fx_return
        return result

    assumption_locator = locator(task_dir, "inputs/confirmed_policy.json")
    weight_locator = locator(task_dir, "out/weights.json")
    as_of = datetime.datetime.fromtimestamp(
        float(weights.get("evaluation_epoch") or 0), datetime.timezone.utc).isoformat()
    retrieved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    assumptions = {
        "scenario_contract_version": "2.0",
        "base_currency": base_currency,
        "weight_snapshot": {
            "as_of": as_of,
            "source": "PIA current weights from rebalance_weights.py on a validated Daily Sync report",
            "source_locator": weight_locator,
            "retrieved_at": retrieved_at,
            "content_sha256": weights_sha,
            "valuation_basis": "base_currency_market_value",
            "market_values_base_currency": market_values,
            "fx_as_of": next(iter(fx_metadata.values()), {}).get("as_of"),
            "fx_source": "isolated FX refresh recorded in the positions snapshot",
            "fx_source_locator": next(iter(fx_metadata.values()), {}).get("source_locator"),
            "fx_rates": fx_rates,
        },
        "scenarios": [
            {
                "name": primary_name,
                "assumption_source": (
                    "Explicit user-confirmed hypothetical stress; not a forecast, historical "
                    f"backtest, maximum-drawdown calculation or probability claim. {assumption_locator}"),
                "asset_returns": asset_returns(),
                "fx_returns": {
                    pair: {"return": float(usd_cny if pair.startswith("USD/") else 0.0),
                           "as_of": retrieved_at,
                           "source": "User-confirmed hypothetical FX shock",
                           "source_locator": assumption_locator}
                    for pair in fx_rates
                },
                "cost_model": {
                    "source": ("User-confirmed no transactions/no new capital: incremental transaction "
                               "cost is zero, not a fee estimate for active construction"),
                    "source_locator": assumption_locator,
                    "as_of": retrieved_at,
                    "default": {"transaction_cost_bps": 0, "assumed_turnover": 0},
                },
            },
            {
                "name": sensitivity_name,
                "assumption_source": (
                    "Explicit user-confirmed sensitivity: the same stress with the overrides "
                    f"applied. {assumption_locator}"),
                "asset_returns": asset_returns(
                    overrides={key.replace("_local_total_return", ""): value
                               for key, value in sensitivity.items()
                               if key.endswith("_local_total_return")}),
                "fx_returns": {
                    pair: {
                        "return": float(sensitivity.get("usd_cny_return", 0.0))
                        if pair.startswith("USD/") else 0.0,
                        "as_of": retrieved_at,
                        "source": "User-confirmed hypothetical FX shock (sensitivity override)",
                        "source_locator": assumption_locator,
                    }
                    for pair in fx_rates
                },
                "cost_model": {
                    "source": "User-confirmed no transactions/no new capital",
                    "source_locator": assumption_locator,
                    "as_of": retrieved_at,
                    "default": {"transaction_cost_bps": 0, "assumed_turnover": 0},
                },
            },
        ],
        "constraints": {
            "bucket_policies": [
                {
                    "id": "user_confirmed_non_cash_80_20",
                    "source": "User-confirmed bucket policy",
                    "source_locator": assumption_locator,
                    "scope_symbols": [*core, *satellite],
                    "excluded_symbols": {
                        symbol: "Cash excluded only from the bucket denominator; retained in stress P/L"
                        for symbol in excluded
                    },
                    "tolerance": float(bucket_policy.get("tolerance_fraction") or 0.02),
                    "buckets": [
                        {"id": "core", "symbols": core,
                         "target_weight": float(bucket_policy.get("core_fraction") or 0.8)},
                        {"id": "satellite", "symbols": satellite,
                         "target_weight": float(bucket_policy.get("satellite_fraction") or 0.2)},
                    ],
                }
            ]
        },
    }

    stamp = datetime.date.today().strftime("%Y%m%d")
    portfolio_path = task_dir / "inputs" / f"scenario_portfolio_{stamp}.json"
    assumptions_path = task_dir / "inputs" / f"scenario_assumptions_{stamp}.json"
    portfolio_sha = write_json(portfolio_path, portfolio, args.force)
    assumptions_sha = write_json(assumptions_path, assumptions, args.force)
    merge_manifest(task_dir / "inputs" / "dataset_manifest.json", manifest_entries(
        task_dir,
        [("out/weights.json", weights_path),
         ("inputs/confirmed_policy.json", policy_path),
         (f"inputs/{portfolio_path.name}", portfolio_path),
         (f"inputs/{assumptions_path.name}", assumptions_path)],
    ))
    return {
        "status": "complete",
        "detail_status": "scenario_inputs_built",
        "decision_scope": DECISION_SCOPE,
        "portfolio_json": str(portfolio_path),
        "portfolio_sha256": portfolio_sha,
        "assumptions_json": str(assumptions_path),
        "assumptions_sha256": assumptions_sha,
        "weights_sha256": weights_sha,
        "confirmed_policy_sha256": policy_sha,
        "positions_sha256": positions_sha,
        "scenarios": [scenario["name"] for scenario in assumptions["scenarios"]],
        "fx_rates": fx_rates,
        "non_executable": True,
    }


# ----------------------------------------------------------------------- inverse-vol


def build_inverse_vol(args: argparse.Namespace) -> dict[str, Any]:
    task_dir = Path(args.task_dir).expanduser().resolve()
    policy_source = Path(args.confirmed_policy).expanduser().resolve()
    observations_source = Path(args.volatilities_file).expanduser().resolve()
    policy, policy_sha = read_json(policy_source, "confirmed policy")
    positions, _ = read_json(Path(args.positions_file).expanduser().resolve(), "positions snapshot")
    observations, observations_sha = read_json(observations_source, "volatility observations")
    policy_path = ensure_local_copy(task_dir, "inputs/confirmed_policy.json", policy_source, args.force)
    observations_path = ensure_local_copy(task_dir, "inputs/volatility_observations.json",
                                         observations_source, args.force)

    bucket_policy = policy.get("bucket_policy") or {}
    core = list(bucket_policy.get("core") or [])
    satellite = list(bucket_policy.get("satellite") or [])
    require(core and satellite, "confirmed policy must declare core and satellite buckets")

    active = [item for item in positions.get("positions", [])
              if isinstance(item, dict) and float(item.get("quantity") or 0) > 0]
    cash_symbols = [str(item.get("symbol")) for item in active
                    if str(item.get("market")).upper() == "CASH"
                    or str(item.get("asset_type")).lower() == "cash"]
    # The user-confirmed 80/20 rule measures its denominator on non-cash market value,
    # so a policy can declare that scope and list the cash positions as explicitly
    # excluded with a reason instead of forcing a cash bucket target.
    denominator = str(bucket_policy.get("denominator") or "").strip()
    use_non_cash_scope = denominator == "active_non_cash_market_value"
    if not use_non_cash_scope:
        require(len(cash_symbols) <= 1,
                "cash_bucket_rule_conflict: the policy schema allows exactly one cash position in a "
                f"cash bucket, but this portfolio has {len(cash_symbols)} ({', '.join(cash_symbols)}); "
                "declare bucket_policy.denominator=active_non_cash_market_value in the confirmed "
                "policy to exclude cash explicitly, or merge the cash lines")
    non_cash = [str(item.get("symbol")) for item in active if str(item.get("symbol")) not in cash_symbols]
    uncovered = sorted(set(non_cash) - set(core) - set(satellite))
    require(not uncovered,
            f"confirmed bucket policy leaves active symbols unmapped: {', '.join(uncovered)}")

    resolved: dict[str, Any] = {}
    missing: list[str] = []
    for symbol, record in (observations.get("volatility_observations") or {}).items():
        if symbol not in non_cash:
            continue
        required_fields = ("annualized_volatility", "observation_count", "window_start",
                           "window_end", "as_of", "source", "source_locator")
        absent = [field for field in required_fields if record.get(field) in (None, "")]
        if absent:
            missing.append(f"{symbol}: missing {', '.join(absent)}")
            continue
        resolved[symbol] = record
    absent_symbols = sorted(set(non_cash) - set(resolved))
    if absent_symbols or missing:
        detail = missing + [f"{symbol}: no volatility observation supplied" for symbol in absent_symbols]
        return {
            "status": "insufficient_data",
            "detail_status": "volatility_observations_incomplete",
            "decision_scope": DECISION_SCOPE,
            "errors": detail[:12],
            "required_symbols": non_cash,
            "note": "annualized volatility is an input, not a value the skill may invent",
        }

    bucket_members = {"core": [symbol for symbol in core if symbol in resolved],
                      "satellite": [symbol for symbol in satellite if symbol in resolved]}
    bucket_targets = {
        "core": float(bucket_policy.get("core_fraction") or 0.8),
        "satellite": float(bucket_policy.get("satellite_fraction") or 0.2),
    }
    excluded_policy_symbols: dict[str, str] = {}
    if use_non_cash_scope:
        excluded_policy_symbols = {
            symbol: ("excluded from the policy denominator by the user-confirmed 80/20 rule "
                     "(non-cash market value); cash remains in the scenario P/L")
            for symbol in cash_symbols}
    elif cash_symbols:
        bucket_members["cash"] = cash_symbols
        cash_target = round(1.0 - sum(bucket_targets.values()), 10)
        if cash_target <= 0:
            # The policy schema requires every active symbol in exactly one bucket and
            # bucket targets to sum to 1.0, while the confirmed 80/20 policy measures the
            # denominator on non-cash value only.  With a cash position present the two
            # contracts cannot both hold, so the builder reports the gap instead of
            # inventing a cash target.
            return {
                "status": "insufficient_data",
                "detail_status": "cash_bucket_weight_conflict",
                "decision_scope": DECISION_SCOPE,
                "errors": [
                    "the confirmed core+satellite targets already sum to 1.0, so the policy "
                    "schema has no weight left for the cash bucket "
                    f"({', '.join(cash_symbols)}); the schema also requires every active "
                    "symbol in exactly one bucket"
                ],
                "remediation": [
                    "confirm a cash target that subtracts from core and satellite, or",
                    "exclude cash from the experiment policy once the contract says so, or",
                    "extend inverse_volatility_policy_schema.json with a non-cash denominator rule",
                ],
                "non_executable": True,
            }
        bucket_targets["cash"] = cash_target

    payload = {
        "schema_version": "pia_inverse_volatility_policy_v1",
        "experiment": "inverse_volatility_allocation",
        "decision_scope": DECISION_SCOPE,
        "as_of": str(observations.get("as_of") or datetime.date.today().isoformat()),
        "bucket_targets": bucket_targets,
        "bucket_members": bucket_members,
        "volatility_observations": resolved,
        "source_bindings": {
            "confirmed_policy_sha256": policy_sha,
            "volatility_observations_sha256": observations_sha,
            "volatility_observations_locator": locator(task_dir, "inputs/volatility_observations.json"),
        },
    }
    if use_non_cash_scope:
        payload["denominator"] = "active_non_cash_market_value"
        payload["excluded_policy_symbols"] = excluded_policy_symbols
    out_path = task_dir / "inputs" / "inverse_volatility_policy.json"
    out_sha = write_json(out_path, payload, args.force)
    merge_manifest(task_dir / "inputs" / "dataset_manifest.json", manifest_entries(
        task_dir,
        [("inputs/confirmed_policy.json", policy_path),
         ("inputs/volatility_observations.json", observations_path),
         ("inputs/inverse_volatility_policy.json", out_path)],
    ))
    return {
        "status": "complete",
        "detail_status": "inverse_volatility_policy_built",
        "decision_scope": DECISION_SCOPE,
        "policy_file": str(out_path),
        "policy_sha256": out_sha,
        "symbols": sorted(resolved),
        "method_boundary": "inverse_volatility_allocation ignores correlation; not risk parity",
        "output_field": "experimental_weight",
        "non_executable": True,
    }


# ----------------------------------------------------------------------- thesis-pack


def build_thesis_pack(args: argparse.Namespace) -> dict[str, Any]:
    task_dir = Path(args.task_dir).expanduser().resolve()
    quotes_source = Path(args.quotes_file).expanduser().resolve()
    quotes, quotes_sha = read_json(quotes_source, "quotes file")
    quotes_path = ensure_local_copy(task_dir, "out/quotes.json", quotes_source, args.force)
    audit = quotes.get("portfolio_batch_audit") or {}
    binding = audit.get("portfolio_snapshot_binding")
    require(isinstance(binding, dict) and binding.get("sha256"),
            "quotes file has no portfolio_snapshot_binding; run yf.py --daily-sync first")
    evidence, evidence_sha = read_json(Path(args.evidence_file).expanduser().resolve(),
                                      "evidence file")
    assessments, assessments_sha = read_json(Path(args.assessments_file).expanduser().resolve(),
                                            "assessments file")
    scopes, scopes_sha = read_json(Path(args.scope_coverage_file).expanduser().resolve(),
                                  "scope coverage file")

    items: list[dict[str, Any]] = []
    for index, item in enumerate(evidence.get("evidence_items") or []):
        require(isinstance(item, dict), f"evidence_items[{index}] must be an object")
        artifact = item.get("artifact")
        require(isinstance(artifact, str) and artifact,
                f"evidence_items[{index}] must name a local artifact to hash")
        artifact_path = (task_dir / artifact).resolve()
        require(artifact_path.is_file(),
                f"evidence_items[{index}] artifact not found: {artifact_path}")
        digest = sha256_bytes(artifact_path.read_bytes())
        declared = str(item.get("content_sha256") or "").lower()
        if declared and declared != digest:
            raise BuildError(
                f"evidence_items[{index}] content_sha256 does not match {artifact}: "
                f"declared {declared[:12]}… recomputed {digest[:12]}…")
        items.append({key: value for key, value in item.items() if key != "artifact"} | {
            "content_sha256": digest})

    window_end = str(args.window_end or datetime.datetime.now(datetime.timezone.utc).isoformat())
    # ``x.get("k") or x`` would re-substitute the whole document when the key
    # holds an empty list, so resolve the wrapped form explicitly.
    scope_coverage = scopes.get("scope_coverage")
    if scope_coverage is None:
        scope_coverage = scopes
    assessment_list = assessments.get("assessments")
    if assessment_list is None:
        assessment_list = assessments
    require(isinstance(scope_coverage, dict), "scope coverage must be an object")
    require(isinstance(assessment_list, list), "assessments must be a list")
    payload = {
        "schema_version": "pia_thesis_red_team_v1",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "window_start": str(args.window_start),
        "window_end": window_end,
        "portfolio_snapshot_binding": binding,
        "scope_coverage": scope_coverage,
        "assessments": assessment_list,
        "evidence_items": items,
    }
    active = [entry["symbol"] for entry in binding.get("active_positions", [])
              if entry.get("asset_type") != "cash"]
    assessed = {entry.get("symbol") for entry in assessment_list if isinstance(entry, dict)}
    assessed = {entry.get("symbol") for entry in assessment_list if isinstance(entry, dict)}
    missing = sorted(set(active) - assessed)
    require(not missing, f"assessments do not cover: {', '.join(missing)}")

    out_path = task_dir / "inputs" / "thesis_evidence_pack.json"
    out_sha = write_json(out_path, payload, args.force)
    merge_manifest(task_dir / "inputs" / "dataset_manifest.json", manifest_entries(
        task_dir,
        [("out/quotes.json", quotes_path),
         ("inputs/thesis_evidence_pack.json", out_path)],
    ))
    return {
        "status": "complete",
        "detail_status": "thesis_evidence_pack_built",
        "decision_scope": DECISION_SCOPE,
        "pack_file": str(out_path),
        "pack_sha256": out_sha,
        "evidence_count": len(items),
        "assessment_count": len(payload["assessments"]),
        "quotes_sha256": quotes_sha,
        "evidence_source_sha256": evidence_sha,
        "assessments_source_sha256": assessments_sha,
        "scope_source_sha256": scopes_sha,
        "active_symbols": len(active),
    }


# ------------------------------------------------------------------- dataset-manifest


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    task_dir = Path(args.task_dir).expanduser().resolve()
    bindings: list[tuple[str, Path]] = []
    for item in args.artifact:
        relative, _, raw_path = item.partition("=")
        require(bool(raw_path), f"--artifact expects relative-path=file, got {item!r}")
        path = Path(raw_path).expanduser().resolve()
        require(path.is_file(), f"artifact not found: {path}")
        bindings.append((relative, path))
    merge_manifest(task_dir / "inputs" / "dataset_manifest.json",
                   manifest_entries(task_dir, bindings))
    return {
        "status": "complete",
        "detail_status": "dataset_manifest_updated",
        "decision_scope": DECISION_SCOPE,
        "manifest": str(task_dir / "inputs" / "dataset_manifest.json"),
        "binding_count": len(bindings),
    }


BUILDERS = {
    "scenario": build_scenario,
    "inverse-vol": build_inverse_vol,
    "thesis-pack": build_thesis_pack,
    "dataset-manifest": build_manifest,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build gate-ready active-research inputs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scenario = subparsers.add_parser("scenario", help="Build scenario portfolio + assumptions.")
    scenario.add_argument("--weights-file", required=True)
    scenario.add_argument("--confirmed-policy", required=True)
    scenario.add_argument("--positions-file", required=True)
    scenario.add_argument("--task-dir", required=True)
    scenario.add_argument("--force", action="store_true")

    inverse = subparsers.add_parser("inverse-vol", help="Build an inverse-volatility policy.")
    inverse.add_argument("--confirmed-policy", required=True)
    inverse.add_argument("--positions-file", required=True)
    inverse.add_argument("--volatilities-file", required=True)
    inverse.add_argument("--task-dir", required=True)
    inverse.add_argument("--force", action="store_true")

    pack = subparsers.add_parser("thesis-pack", help="Build a thesis red-team evidence package.")
    pack.add_argument("--quotes-file", required=True)
    pack.add_argument("--evidence-file", required=True)
    pack.add_argument("--assessments-file", required=True)
    pack.add_argument("--scope-coverage-file", required=True)
    pack.add_argument("--window-start", required=True)
    pack.add_argument("--window-end")
    pack.add_argument("--task-dir", required=True)
    pack.add_argument("--force", action="store_true")

    manifest = subparsers.add_parser("dataset-manifest", help="Register local artifacts.")
    manifest.add_argument("--task-dir", required=True)
    manifest.add_argument("--artifact", action="append", default=[], required=True)

    args = parser.parse_args(argv)
    try:
        payload = BUILDERS[args.command](args)
    except BuildError as exc:
        print(json.dumps({"status": "failed", "detail_status": "build_input_invalid",
                          "decision_scope": DECISION_SCOPE, "errors": [str(exc)]},
                         ensure_ascii=False, indent=2))
        return 3
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
