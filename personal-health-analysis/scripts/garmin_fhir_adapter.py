#!/usr/bin/env python3
"""Offline, research-only FHIR R4 packaging for explicit local JSON input.

The adapter deliberately avoids LOINC mappings because Garmin's vendor-derived
fields do not establish the measurement method required for a safe terminology
mapping. It performs no authentication, Garmin access, network access, clinical
interpretation, or server upload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


FHIR_VERSION = "4.0.1"
FHIR_EXPORT_RESEARCH_ONLY = "FHIR_EXPORT_RESEARCH_ONLY"
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AUTHORIZATION = 3
EXIT_OUTPUT_EXISTS = 4
EXIT_CONTRACT = 5

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CLASSIFICATION_SYSTEM = "urn:personal-health-analysis:classification"
_SOURCE_HASH_SYSTEM = "urn:personal-health-analysis:declared-upstream-source-sha256"
_INPUT_HASH_SYSTEM = "urn:personal-health-analysis:input-json-sha256"
_RESEARCH_TAG = {
    "system": _CLASSIFICATION_SYSTEM,
    "code": "consumer-wearable-research-only",
    "display": "Consumer wearable research-only data",
}


def _external_gate_status() -> dict[str, str]:
    return {
        "r4_structure": "not_performed",
        "profile_ig": "not_performed",
        "terminology": "not_performed",
        "receiver": "not_performed",
    }

SUPPORTED_METRICS = {
    "hrv_ms": {
        "text": "Garmin nightly average heart rate variability (vendor-derived)",
        "unit": "ms",
        "ucum": "ms",
    },
    "resting_heart_rate_bpm": {
        "text": "Garmin resting heart rate (consumer wearable)",
        "unit": "beats/minute",
        "ucum": "/min",
    },
    "sleep_duration_seconds": {
        "text": "Garmin estimated sleep duration (vendor-derived)",
        "unit": "s",
        "ucum": "s",
    },
}


class FHIRContractError(ValueError):
    """Raised before emitting a resource that violates the research contract."""


def _require_sha256(value: str, field_name: str = "source_sha256") -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise FHIRContractError(f"{field_name}_must_be_64_lowercase_hex")
    return value


def _normalize_effective(value: str) -> str:
    candidate = str(value).strip()
    if _DATE_RE.fullmatch(candidate):
        try:
            datetime.strptime(candidate, "%Y-%m-%d")
        except ValueError as exc:
            raise FHIRContractError("invalid_effective_date") from exc
        return candidate
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FHIRContractError("invalid_effective_datetime") from exc
    if parsed.tzinfo is None:
        raise FHIRContractError("effective_datetime_requires_timezone")
    return parsed.isoformat()


def _normalize_recorded(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    candidate = str(value).strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FHIRContractError("invalid_recorded_at") from exc
    if parsed.tzinfo is None:
        raise FHIRContractError("recorded_at_requires_timezone")
    return parsed.isoformat()


def _stable_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, canonical))


def get_export_status() -> dict[str, Any]:
    """Describe the bounded export surface without accessing health data."""
    return {
        "status": FHIR_EXPORT_RESEARCH_ONLY,
        "enabled": True,
        "clinical_interoperability": False,
        "fhir_version": FHIR_VERSION,
        "terminology_mapping": "text_only_no_loinc",
        "validation_scope": "local_research_contract_only",
        "external_gates": _external_gate_status(),
        "data_accessed": False,
        "network_accessed": False,
        "supported_metrics": sorted(SUPPORTED_METRICS),
    }


def create_observation(
    value: float,
    date_str: str,
    metric_type: str,
    *,
    source_sha256: str,
    firmware_version: str | None = None,
    device_serial_hash: str | None = None,
) -> dict[str, Any]:
    """Create one text-coded, non-clinical Observation from explicit input."""
    if metric_type not in SUPPORTED_METRICS:
        raise FHIRContractError("unsupported_metric")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FHIRContractError("value_must_be_numeric")
    if not math.isfinite(float(value)):
        raise FHIRContractError("value_must_be_finite")
    source_digest = _require_sha256(source_sha256)
    effective = _normalize_effective(date_str)
    metric = SUPPORTED_METRICS[metric_type]
    normalized_device_hash: str | None = None
    if device_serial_hash is not None:
        normalized_device_hash = _require_sha256(
            device_serial_hash, "device_serial_hash"
        )
    identity = {
        "metric": metric_type,
        "effective": effective,
        "value": float(value),
        "source_sha256": source_digest,
        "firmware_version": firmware_version,
        "device_serial_hash": normalized_device_hash,
    }
    notes = [
        "Consumer wearable observation for research or personal data portability only; "
        "not clinical-grade and no diagnosis or interpretation is asserted."
    ]
    if firmware_version:
        notes.append(f"Recorded firmware version: {firmware_version}")
    if normalized_device_hash:
        notes.append(f"Pseudonymous device serial hash: {normalized_device_hash}")
    return {
        "resourceType": "Observation",
        "id": _stable_id(identity),
        "meta": {"tag": [_RESEARCH_TAG.copy()]},
        "status": "unknown",
        "code": {"text": metric["text"]},
        "effectiveDateTime": effective,
        "valueQuantity": {
            "value": float(value),
            "unit": metric["unit"],
            "system": "http://unitsofmeasure.org",
            "code": metric["ucum"],
        },
        "method": {
            "text": "Garmin consumer wearable or vendor algorithm; method version not clinically verified"
        },
        "note": [{"text": note} for note in notes],
    }


def create_fhir_bundle(
    observations: Sequence[dict[str, Any]],
    *,
    source_sha256: str,
    input_sha256: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Package observations and explicit source provenance in a collection Bundle."""
    source_digest = _require_sha256(source_sha256)
    input_digest = (
        _require_sha256(input_sha256, "input_sha256")
        if input_sha256 is not None
        else None
    )
    recorded = _normalize_recorded(recorded_at)
    entries: list[dict[str, Any]] = []
    targets: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for observation in observations:
        if not isinstance(observation, dict) or observation.get("resourceType") != "Observation":
            raise FHIRContractError("bundle_accepts_observations_only")
        resource_id = str(observation.get("id", ""))
        if not resource_id or resource_id in seen_ids:
            raise FHIRContractError("observation_ids_must_be_unique")
        seen_ids.add(resource_id)
        full_url = f"urn:uuid:{resource_id}"
        entries.append({"fullUrl": full_url, "resource": observation})
        targets.append({"reference": full_url})
    if not entries:
        raise FHIRContractError("at_least_one_observation_required")

    provenance_seed = {
        "source_sha256": source_digest,
        "input_sha256": input_digest,
        "recorded": recorded,
        "targets": [target["reference"] for target in targets],
    }
    provenance_id = _stable_id(provenance_seed)
    provenance = {
        "resourceType": "Provenance",
        "id": provenance_id,
        "meta": {"tag": [_RESEARCH_TAG.copy()]},
        "target": targets,
        "recorded": recorded,
        "activity": {"text": "Offline conversion of explicit local consumer wearable data"},
        "agent": [
            {
                "type": {"text": "assembler"},
                "who": {"display": "personal-health-analysis local converter"},
            }
        ],
        "entity": [
            {
                "role": "source",
                "what": {
                    "identifier": {
                        "system": _SOURCE_HASH_SYSTEM,
                        "value": source_digest,
                    }
                },
            },
            *(
                [
                    {
                        "role": "source",
                        "what": {
                            "identifier": {
                                "system": _INPUT_HASH_SYSTEM,
                                "value": input_digest,
                            }
                        },
                    }
                ]
                if input_digest is not None
                else []
            ),
        ],
    }
    entries.append({"fullUrl": f"urn:uuid:{provenance_id}", "resource": provenance})
    bundle = {
        "resourceType": "Bundle",
        "id": _stable_id(provenance_seed | {"kind": "bundle"}),
        "meta": {"tag": [_RESEARCH_TAG.copy()]},
        "type": "collection",
        "timestamp": recorded,
        "entry": entries,
    }
    validate_research_bundle(bundle)
    return bundle


def validate_research_bundle(bundle: dict[str, Any]) -> None:
    """Enforce the local FHIR R4 research subset before any write."""
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise FHIRContractError("bundle_resource_required")
    if bundle.get("type") != "collection":
        raise FHIRContractError("collection_bundle_required")
    entries = bundle.get("entry")
    if not isinstance(entries, list) or not entries:
        raise FHIRContractError("bundle_entries_required")
    full_urls = [entry.get("fullUrl") for entry in entries if isinstance(entry, dict)]
    if len(full_urls) != len(entries) or len(full_urls) != len(set(full_urls)):
        raise FHIRContractError("bundle_full_urls_must_be_unique")
    if any(not isinstance(value, str) or not value.startswith("urn:uuid:") for value in full_urls):
        raise FHIRContractError("bundle_full_urls_must_be_uuid_urns")

    observations: list[tuple[str, dict[str, Any]]] = []
    provenances: list[dict[str, Any]] = []
    for entry in entries:
        resource = entry.get("resource")
        if not isinstance(resource, dict):
            raise FHIRContractError("bundle_entry_resource_required")
        resource_type = resource.get("resourceType")
        if resource_type == "Observation":
            observations.append((entry["fullUrl"], resource))
            if resource.get("status") != "unknown":
                raise FHIRContractError("observation_status_must_be_unknown")
            code = resource.get("code")
            if not isinstance(code, dict) or not code.get("text") or "coding" in code:
                raise FHIRContractError("observation_code_must_be_text_only")
            if "interpretation" in resource or "referenceRange" in resource:
                raise FHIRContractError("clinical_interpretation_is_forbidden")
            quantity = resource.get("valueQuantity")
            if not isinstance(quantity, dict) or quantity.get("system") != "http://unitsofmeasure.org":
                raise FHIRContractError("ucum_quantity_required")
        elif resource_type == "Provenance":
            provenances.append(resource)
        else:
            raise FHIRContractError("unsupported_bundle_resource")
    if not observations or len(provenances) != 1:
        raise FHIRContractError("observations_and_one_provenance_required")
    provenance = provenances[0]
    target_refs = {
        target.get("reference")
        for target in provenance.get("target", [])
        if isinstance(target, dict)
    }
    if target_refs != {full_url for full_url, _ in observations}:
        raise FHIRContractError("provenance_targets_must_match_observations")
    _normalize_recorded(provenance.get("recorded"))
    if not provenance.get("agent") or not provenance.get("entity"):
        raise FHIRContractError("provenance_agent_and_entity_required")
    serialized = json.dumps(bundle, ensure_ascii=False).lower()
    if "loinc" in serialized:
        raise FHIRContractError("loinc_mapping_is_not_permitted")


def _atomic_write_json(bundle: dict[str, Any], output: Path, *, overwrite: bool) -> None:
    output = output.expanduser().resolve()
    if output.exists() and not overwrite:
        raise FileExistsError(str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(bundle, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary, output)
        else:
            # Publishing a hard link is an atomic create-if-absent operation on
            # the same filesystem.  It cannot replace a target created by a
            # concurrent process between the early check and publication.
            os.link(temporary, output)
            temporary.unlink()
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline research-only FHIR R4 packaging for explicit JSON input."
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Describe the bounded export contract")
    export = subparsers.add_parser("export", help="Package explicit local JSON input")
    export.add_argument("--input", required=True, help="Explicit local JSON input file")
    export.add_argument("--output", required=True, help="Explicit FHIR Bundle output file")
    export.add_argument(
        "--acknowledge-research-only",
        action="store_true",
        help="Acknowledge that the output is non-clinical and has text-only semantics",
    )
    export.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        _emit({"ok": False, "status": "usage_error", "error": "command_required"})
        return EXIT_USAGE
    if args.command == "status":
        _emit(get_export_status())
        return EXIT_OK
    if not args.acknowledge_research_only:
        _emit({"ok": False, "status": "research_only_acknowledgement_required"})
        return EXIT_AUTHORIZATION

    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    if input_path == output_path:
        _emit({"ok": False, "status": "input_output_conflict"})
        return EXIT_USAGE
    try:
        input_bytes = input_path.read_bytes()
        input_sha256 = hashlib.sha256(input_bytes).hexdigest()
        payload = json.loads(input_bytes.decode("utf-8"))
        source_sha256 = _require_sha256(payload.get("source_sha256", ""))
        raw_observations = payload.get("observations")
        if not isinstance(raw_observations, list):
            raise FHIRContractError("observations_must_be_a_list")
        observations = [
            create_observation(
                item.get("value"),
                item.get("date"),
                item.get("metric"),
                source_sha256=source_sha256,
                firmware_version=item.get("firmware_version"),
                device_serial_hash=item.get("device_serial_hash"),
            )
            for item in raw_observations
            if isinstance(item, dict)
        ]
        if len(observations) != len(raw_observations):
            raise FHIRContractError("each_observation_must_be_an_object")
        bundle = create_fhir_bundle(
            observations,
            source_sha256=source_sha256,
            input_sha256=input_sha256,
            recorded_at=payload.get("recorded_at"),
        )
        _atomic_write_json(bundle, output_path, overwrite=args.overwrite)
    except FileExistsError:
        _emit({"ok": False, "status": "output_exists"})
        return EXIT_OUTPUT_EXISTS
    except (OSError, json.JSONDecodeError, FHIRContractError) as exc:
        _emit(
            {
                "ok": False,
                "status": "fhir_contract_failed",
                "error_type": type(exc).__name__,
            }
        )
        return EXIT_CONTRACT
    _emit(
        {
            "ok": True,
            "status": FHIR_EXPORT_RESEARCH_ONLY,
            "resources_emitted": len(bundle["entry"]),
            "clinical_interoperability": False,
            "validation_scope": "local_research_contract_only",
            "external_gates": _external_gate_status(),
            "network_accessed": False,
        }
    )
    return EXIT_OK


def convert_hrv(*_args, **_kwargs):
    raise FHIRContractError("live_conversion_disabled_use_explicit_local_input")


def convert_rhr(*_args, **_kwargs):
    raise FHIRContractError("live_conversion_disabled_use_explicit_local_input")


def convert_sleep(*_args, **_kwargs):
    raise FHIRContractError("live_conversion_disabled_use_explicit_local_input")


def convert_stress(*_args, **_kwargs):
    raise FHIRContractError("unsupported_metric")


if __name__ == "__main__":
    raise SystemExit(main())
