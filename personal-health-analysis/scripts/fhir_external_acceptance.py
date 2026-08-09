#!/usr/bin/env python3
"""Inventory hash-bound external FHIR assertions without sending health data.

This tool does not run a validator, contact a receiver, or verify an independent
signature.  It can show that caller-supplied artifacts still match caller-
supplied hashes, but it can never establish that an external gate passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from garmin_fhir_adapter import FHIRContractError, validate_research_bundle


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_FAILED = 5
EVIDENCE_VERSION = 1
GATE_NAMES = ("r4_structure", "profile_ig", "terminology", "receiver")
ALLOWED_STATES = {"passed", "failed", "not_requested", "unavailable", "indeterminate"}


class AcceptanceError(ValueError):
    """Stable failure raised for malformed or unbound external evidence."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise AcceptanceError("artifact_read_failed") from exc
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _resolve_artifact(item: object, base: Path, role: str) -> dict[str, str]:
    if not isinstance(item, dict):
        raise AcceptanceError(f"{role}_artifact_required")
    supplied = item.get("path")
    expected = item.get("sha256")
    if not isinstance(supplied, str) or not supplied.strip() or not _is_sha256(expected):
        raise AcceptanceError(f"{role}_artifact_binding_invalid")
    path = Path(supplied).expanduser()
    path = path if path.is_absolute() else base / path
    path = Path(os.path.abspath(os.fspath(path)))
    if path.is_symlink() or not path.is_file():
        raise AcceptanceError(f"{role}_artifact_invalid")
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    if attributes & 0x400:
        raise AcceptanceError(f"{role}_artifact_reparse_forbidden")
    actual = _sha256_file(path)
    if actual != expected:
        raise AcceptanceError(f"{role}_artifact_hash_mismatch")
    return {"role": role, "sha256": actual}


def _zero_error_result(value: object, gate: str) -> None:
    if not isinstance(value, dict):
        raise AcceptanceError(f"{gate}_result_required")
    for field in ("exit_code", "error_count", "fatal_count"):
        if value.get(field) != 0:
            raise AcceptanceError(f"{gate}_validator_not_clean")


def _validate_r4_gate(gate: dict[str, Any], base: Path) -> list[dict[str, str]]:
    validator = gate.get("validator")
    package = gate.get("r4_package")
    if not isinstance(validator, dict) or not str(validator.get("version", "")).strip():
        raise AcceptanceError("r4_validator_version_required")
    if (
        not isinstance(package, dict)
        or package.get("id") != "hl7.fhir.r4.core"
        or package.get("version") != "4.0.1"
    ):
        raise AcceptanceError("r4_package_4_0_1_required")
    _zero_error_result(gate.get("result"), "r4_structure")
    return [
        _resolve_artifact(validator, base, "validator"),
        _resolve_artifact(package, base, "r4_package"),
    ]


def _validate_profile_gate(gate: dict[str, Any], base: Path) -> list[dict[str, str]]:
    profiles = gate.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise AcceptanceError("profile_list_required")
    required_types = {"Bundle", "Observation", "Provenance"}
    observed_types: set[str] = set()
    artifacts: list[dict[str, str]] = []
    for index, profile in enumerate(profiles):
        if not isinstance(profile, dict):
            raise AcceptanceError("profile_entry_invalid")
        resource_type = profile.get("resource_type")
        canonical = profile.get("canonical")
        version = profile.get("version")
        if (
            resource_type not in required_types
            or not isinstance(canonical, str)
            or not canonical.startswith(("http://", "https://", "urn:"))
            or not isinstance(version, str)
            or not version.strip()
        ):
            raise AcceptanceError("profile_identity_invalid")
        if profile.get("required_coding") is True:
            raise AcceptanceError("text_only_export_conflicts_with_required_coding")
        observed_types.add(resource_type)
        artifacts.append(_resolve_artifact(profile.get("package"), base, f"profile_{index}"))
    if observed_types != required_types:
        raise AcceptanceError("bundle_observation_provenance_profiles_required")
    _zero_error_result(gate.get("result"), "profile_ig")
    return artifacts


def _validate_terminology_gate(gate: dict[str, Any], _base: Path) -> list[dict[str, str]]:
    # The exported codes are intentionally text-only. UCUM structure may be
    # checked by the validator, but semantic code-system equivalence cannot pass.
    raise AcceptanceError("text_only_export_has_no_clinical_terminology_equivalence")


def _validate_receiver_gate(gate: dict[str, Any], base: Path) -> list[dict[str, str]]:
    result = gate.get("result")
    if not isinstance(result, dict):
        raise AcceptanceError("receiver_result_required")
    if result.get("real_health_data") is True:
        raise AcceptanceError("real_health_data_receiver_evidence_not_accepted")
    status = result.get("transport_status")
    if (
        result.get("actual_delivery") is not True
        or result.get("synthetic_data") is not True
        or not isinstance(status, int)
        or not 200 <= status < 300
        or result.get("operation_outcome_error_count") != 0
    ):
        raise AcceptanceError("receiver_transport_evidence_incomplete")
    return [
        _resolve_artifact(gate.get("capability_statement"), base, "capability_statement"),
        _resolve_artifact(gate.get("operation_outcome"), base, "operation_outcome"),
        _resolve_artifact(gate.get("receiver_attestation"), base, "receiver_attestation"),
    ]


_VALIDATORS = {
    "r4_structure": _validate_r4_gate,
    "profile_ig": _validate_profile_gate,
    "terminology": _validate_terminology_gate,
    "receiver": _validate_receiver_gate,
}


def evaluate_acceptance(bundle_path: Path, evidence_path: Path) -> dict[str, Any]:
    bundle_path = Path(bundle_path).expanduser().resolve()
    evidence_path = Path(evidence_path).expanduser().resolve()
    try:
        bundle_bytes = bundle_path.read_bytes()
        bundle = json.loads(bundle_bytes.decode("utf-8"))
        evidence_bytes = evidence_path.read_bytes()
        evidence = json.loads(evidence_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError("input_read_or_json_failed") from exc
    try:
        validate_research_bundle(bundle)
    except FHIRContractError as exc:
        raise AcceptanceError("bundle_local_contract_failed") from exc
    if not isinstance(evidence, dict) or evidence.get("version") != EVIDENCE_VERSION:
        raise AcceptanceError("evidence_version_invalid")
    expected_bundle_hash = evidence.get("bundle_sha256")
    actual_bundle_hash = hashlib.sha256(bundle_bytes).hexdigest()
    if expected_bundle_hash != actual_bundle_hash:
        raise AcceptanceError("bundle_hash_mismatch")
    gates = evidence.get("gates")
    if not isinstance(gates, dict) or set(gates) != set(GATE_NAMES):
        raise AcceptanceError("four_external_gates_required")

    statuses: dict[str, dict[str, Any]] = {}
    hash_checked_artifacts: list[dict[str, str]] = []
    required_count = 0
    for name in GATE_NAMES:
        gate = gates[name]
        if not isinstance(gate, dict) or not isinstance(gate.get("required"), bool):
            raise AcceptanceError(f"{name}_gate_invalid")
        supplied_status = gate.get("status")
        if supplied_status not in ALLOWED_STATES:
            raise AcceptanceError(f"{name}_status_invalid")
        final_status = supplied_status
        reason = None
        if supplied_status == "passed":
            try:
                hash_checked_artifacts.extend(
                    _VALIDATORS[name](gate, evidence_path.parent)
                )
                final_status = "indeterminate"
                reason = "unsigned_caller_evidence_cannot_establish_pass"
            except AcceptanceError as exc:
                final_status = "failed"
                reason = str(exc)
        if gate["required"]:
            required_count += 1
        statuses[name] = {
            "required": gate["required"],
            "asserted_status": supplied_status,
            "status": final_status,
            **({"reason": reason} if reason else {}),
        }

    return {
        "ok": False,
        "status": "external_acceptance_not_established",
        "evidence_contract_ok": True,
        "external_acceptance_established": False,
        "required_gate_count": required_count,
        "validation_scope": "caller_evidence_integrity_review_only",
        "evidence_trust": "caller_supplied_hash_bound_not_signed",
        "bundle_sha256": actual_bundle_hash,
        "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "external_gates": statuses,
        "hash_checked_artifacts": hash_checked_artifacts,
        "clinical_interoperability": False,
        "network_accessed": False,
    }


def _atomic_write_json(payload: dict[str, Any], output: Path) -> None:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output)
        temporary.unlink()
        temporary = None
    except FileExistsError as exc:
        raise AcceptanceError("output_exists") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed review of external FHIR acceptance evidence")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        result = evaluate_acceptance(Path(args.bundle), Path(args.evidence))
        if args.output:
            _atomic_write_json(result, Path(args.output))
    except AcceptanceError as exc:
        print(json.dumps({"ok": False, "status": "acceptance_contract_failed", "error": str(exc)}))
        return EXIT_USAGE
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return EXIT_OK if result["ok"] else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
