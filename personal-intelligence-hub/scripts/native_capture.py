"""Bind a native receipt to the exact saved tool return, never a prose reconstruction.

A local hash detects alteration after capture; it does not authenticate the provider
or make a model-authored file a trusted runtime attestation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def capture_fields(path: Path, requested_url: str) -> dict:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("urls"), list):
        raise ValueError("capture must be the unmodified fetch_content return object")
    matches = [item for item in value["urls"] if isinstance(item, dict) and item.get("url") == requested_url]
    if len(matches) != 1:
        raise ValueError("capture must contain exactly one matching requested URL")
    item = matches[0]
    text = item.get("content")
    error = item.get("error")
    status = item.get("status")
    if error or (isinstance(status, int) and status >= 400):
        outcome, text = "error", "" if text is None else text
        error = str(error or f"HTTP {status}")
    else:
        if not isinstance(text, str):
            raise ValueError("capture has no returned content; use stored-result retrieval, not a summary")
        outcome, error = "success", None
    truncated = item.get("truncated", False)
    if type(truncated) is not bool or item.get("hasMore") is True:
        raise ValueError("capture is incomplete; retrieve the complete stored tool output")
    return {"text": text, "outcome": outcome, "error": error, "truncated": truncated,
            "native_capture": {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}}


def validate_capture(receipt: dict, request: dict, request_path: Path) -> None:
    version = request.get("native_capture_version")
    if version is None:
        return
    if type(version) is not int or version != 1:
        raise ValueError("unsupported native capture policy")
    capture = receipt.get("native_capture")
    if not isinstance(capture, dict) or set(capture) != {"path", "sha256"}:
        raise ValueError("exact native tool capture is required; reconstructed receipts are prohibited")
    path = Path(capture["path"]).resolve()
    if not path.is_relative_to(request_path.resolve().parent):
        raise ValueError("native capture must be inside the run directory")
    fields = capture_fields(path, receipt["arguments"]["url"])
    if capture != fields["native_capture"]:
        raise ValueError("native capture bytes changed after receipt assembly")
    if any(receipt.get(key) != fields[key] for key in ("text", "outcome", "error", "truncated")):
        raise ValueError("receipt differs from the exact native tool capture")
