"""Literal query evidence. Checks consistency, not authenticity of a tool return.

The parent must capture actual public tool output; a self-consistent fabricated source
cannot be detected here. No host paths, network access, or ledger writes are needed.
"""
from __future__ import annotations

import hashlib
import json

PROOF_KEYS = {"text", "raw_response", "raw_sha256", "coverage"}


def build_query_proof(raw: str) -> dict:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("literal query response must be non-empty text")
    proof = {
        "text": raw[:2048],
        "raw_response": raw,
        "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "coverage": "full" if len(raw) <= 2048 else "prefix",
    }
    validate_query_proof(proof)
    return proof


def validate_query_proof(proof: dict) -> None:
    if not isinstance(proof, dict) or set(proof) != PROOF_KEYS:
        raise ValueError("literal query proof requires text/raw_response/raw_sha256/coverage")
    raw, excerpt = proof["raw_response"], proof["text"]
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("literal query response must be non-empty text")
    if not isinstance(excerpt, str) or not excerpt or not raw.startswith(excerpt):
        raise ValueError("query proof text must be an exact response prefix, not a paraphrase")
    if proof["raw_sha256"] != hashlib.sha256(raw.encode("utf-8")).hexdigest():
        raise ValueError("literal query response hash mismatch")
    expected = "full" if excerpt == raw else "prefix"
    if proof["coverage"] != expected:
        raise ValueError("literal query coverage mismatch")
    if len(json.dumps(proof, ensure_ascii=False).encode("utf-8")) > 60000:
        raise ValueError("literal query proof exceeds bounded receipt size")
