"""Public-source timing 1.0: availability is not first publication.

Receipt validation is structural. Only explicit verify_source_capture calls read
raw bytes; neither a digest nor a supplied observation timestamp authenticates a
publisher or proves historical availability. No implicit artifact dereferencing.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from datetime import date, datetime, timezone
from pathlib import Path

MAX_CAPTURE_BYTES = 32 * 1024 * 1024
PRIMARY_TIERS = {"company_primary", "regulator", "exchange", "annual_audited_filing", "quarterly_filing", "current_report"}
TIMING_FIELDS = ("timing_contract_version", "publication_precision", "published_at", "publication_date", "publication_utc_offset", "availability_observed_at", "source_capture_receipt")


def aware(value):
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value):
        raise ValueError("seconds-level timezone-aware ISO timestamp required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timezone-aware ISO timestamp required")
    return result.astimezone(timezone.utc)


def iso_day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("ISO date required")
    return date.fromisoformat(value)


def validate_timing_policy(policy):
    errors = []
    if not isinstance(policy, dict):
        return ["timing source_policy must be an object"]
    if policy.get("timing_contract_version") != "1.0":
        errors.append("source_policy.timing_contract_version must be 1.0")
    try:
        cutoff = aware(policy.get("cutoff_at"))
        if cutoff.date() != iso_day(policy.get("cutoff_date")):
            errors.append("source_policy.cutoff_at UTC date must equal cutoff_date")
        if cutoff > datetime.now(timezone.utc):
            errors.append("source_policy.cutoff_at cannot be in the future")
    except (ValueError, TypeError):
        errors.append("source_policy.cutoff_at requires a timezone-aware timestamp")
    return errors


def verify_source_capture(raw_path, *, source_locator, availability_observed_at, retrieved_at, expected_sha256=None, expected_receipt=None):
    """Recompute an explicitly authorized regular file; never infer observation time.

    Caller must verify source identity and the actual capture log independently.
    Passing expected_receipt rechecks the artifact and its supplied source/time
    bindings. verified_at is now, not a retroactive publication/observation time.
    """
    path = Path(raw_path)
    if not stat.S_ISREG(path.stat().st_mode) or path.is_symlink():
        raise ValueError("capture must be a regular, non-symlink file")
    if path.stat().st_size > MAX_CAPTURE_BYTES:
        raise ValueError("capture size limit exceeded")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_CAPTURE_BYTES:
            raise ValueError("opened capture must be a bounded regular file")
        raw = stream.read(MAX_CAPTURE_BYTES + 1)
    if len(raw) > MAX_CAPTURE_BYTES or not raw:
        raise ValueError("capture must be non-empty and within size limit")
    observed, retrieved = aware(availability_observed_at), aware(retrieved_at)
    now = datetime.now(timezone.utc)
    if not observed <= retrieved <= now:
        raise ValueError("capture requires observed <= retrieved <= verification time")
    if not isinstance(source_locator, str) or not source_locator.startswith(("https://", "http://")):
        raise ValueError("capture requires explicit public source URL")
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("capture content_sha256 mismatch")
    receipt = {"contract_version": "1.0", "verification_method": "sha256_raw_bytes_v1", "raw_artifact": str(path.resolve()), "source_locator": source_locator, "content_sha256": digest, "byte_count": len(raw), "availability_observed_at": availability_observed_at, "retrieved_at": retrieved_at, "verified_at": now.isoformat()}
    if expected_receipt is not None:
        if not isinstance(expected_receipt, dict):
            raise ValueError("capture receipt must be an object")
        for field in receipt:
            if field != "verified_at" and expected_receipt.get(field) != receipt[field]:
                raise ValueError(f"capture receipt {field} mismatch")
        if not retrieved <= aware(expected_receipt.get("verified_at")) <= now:
            raise ValueError("capture receipt verification time invalid")
    return receipt


def validate_source_timing(item, policy, prefix="evidence"):
    """Check a supplied receipt chain, without asserting external authenticity."""
    errors = []
    if item.get("timing_contract_version") != "1.0":
        errors.append(f"{prefix}.timing_contract_version must be 1.0")
    if item.get("source_tier") not in PRIMARY_TIERS or item.get("source_type") in ("quote", "market_data", "news", "user_authorized"):
        errors.append(f"{prefix} precision-aware timing requires primary non-quote evidence")
    if not isinstance(item.get("source_locator"), str) or not item["source_locator"].startswith(("https://", "http://")):
        errors.append(f"{prefix} timing requires a public primary URL")
    try:
        observed = aware(item.get("availability_observed_at"))
        retrieved = aware(item.get("retrieved_at"))
        cutoff = aware(policy.get("cutoff_at"))
        valuation = iso_day(item.get("valuation_date"))
        if not valuation <= observed.date() or not observed <= retrieved <= cutoff <= datetime.now(timezone.utc):
            errors.append(f"{prefix} requires valuation_date <= observed availability <= retrieved <= cutoff, no future values")
        precision = item.get("publication_precision")
        if precision == "exact":
            published = aware(item.get("published_at"))
            if published > observed:
                errors.append(f"{prefix} publication cannot follow observed availability")
            if valuation > published.date():
                errors.append(f"{prefix} valuation_date cannot follow exact publication")
            if any(item.get(k) is not None for k in ("publication_date", "publication_utc_offset")):
                errors.append(f"{prefix} exact publication cannot also claim day-only publication")
        elif precision in ("day", "unknown"):
            if "published_at" not in item or item["published_at"] is not None:
                errors.append(f"{prefix}.published_at must be explicitly null for {precision}")
            if precision == "day":
                day = iso_day(item.get("publication_date"))
                if valuation > day:
                    errors.append(f"{prefix} valuation_date cannot follow reported publication day")
                offset = item.get("publication_utc_offset")
                if not isinstance(offset, str) or not re.fullmatch(r"[+-](?:0\d|1[0-4]):[0-5]\d", offset) or (offset[1:3] == "14" and offset[-2:] != "00"):
                    raise ValueError("publication day offset required")
                # This is only a lower bound, never an exact midnight publication.
                lower_bound = aware(day.isoformat() + "T00:00:00" + offset)
                if lower_bound > observed:
                    errors.append(f"{prefix} reported publication day cannot follow availability")
            elif any(item.get(k) is not None for k in ("publication_date", "publication_utc_offset")):
                errors.append(f"{prefix} unknown publication cannot claim a publication day")
        else:
            errors.append(f"{prefix}.publication_precision must be exact, day, or unknown")
    except (ValueError, TypeError, AttributeError, OverflowError):
        errors.append(f"{prefix} malformed timing/date/availability/cutoff")
    receipt = item.get("source_capture_receipt")
    if not isinstance(receipt, dict):
        return errors + [f"{prefix}.source_capture_receipt is required"]
    if receipt.get("contract_version") != "1.0" or receipt.get("verification_method") != "sha256_raw_bytes_v1":
        errors.append(f"{prefix} unknown capture receipt contract")
    for field in ("source_locator", "content_sha256", "availability_observed_at", "retrieved_at"):
        if receipt.get(field) != item.get(field) or item.get(field) is None:
            errors.append(f"{prefix} capture receipt {field} binding mismatch")
    if not isinstance(receipt.get("raw_artifact"), str) or not receipt["raw_artifact"].strip():
        errors.append(f"{prefix} capture receipt requires raw_artifact locator (not auto-opened)")
    if type(receipt.get("byte_count")) is not int or not 0 < receipt["byte_count"] <= MAX_CAPTURE_BYTES:
        errors.append(f"{prefix} capture byte_count invalid")
    if not isinstance(item.get("content_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["content_sha256"]):
        errors.append(f"{prefix}.content_sha256 must hash the full raw artifact")
    try:
        if not aware(item.get("retrieved_at")) <= aware(receipt.get("verified_at")) <= datetime.now(timezone.utc):
            errors.append(f"{prefix} capture verification time invalid")
    except (ValueError, TypeError):
        errors.append(f"{prefix} capture verified_at malformed")
    return errors


def availability_day(item):
    return aware(item.get("availability_observed_at") if item.get("timing_contract_version") == "1.0" else item.get("published_at")).date()
