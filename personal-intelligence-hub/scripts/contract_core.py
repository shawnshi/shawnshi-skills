"""Shared contract primitives for the personal-intelligence-hub run contract.

Extracted from run_contract.py so that identity/hash helpers can be imported by
sibling modules (lane selection, brokers, adapters) without importing the whole
run-contract module.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from history_manager import normalize_url


class RunContractError(ValueError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def candidate_ref(url: str) -> str:
    normalized = normalize_url(str(url))
    if not normalized:
        raise RunContractError("candidate URL is required")
    return "cand-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def candidate_object_hash(candidate: dict[str, Any]) -> str:
    bound = deepcopy(candidate)
    bound.pop("candidate_object_sha256", None)
    return hashlib.sha256(canonical_json_bytes(bound)).hexdigest()
