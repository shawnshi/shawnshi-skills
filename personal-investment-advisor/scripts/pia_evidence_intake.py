"""Turn operator-supplied documents into a Thesis evidence package.

The disclosure channels can be down for weeks, and "channel broken" must never be
read as "no announcement".  This intake accepts files the operator already holds,
hashes them, and refuses anything it cannot tie to a declared issuer/exchange
source tier and an http locator.  It does not judge whether a document is genuine;
it only makes the binding explicit and auditable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path, PureWindowsPath

SOURCE_TIERS = {"issuer", "exchange", "regulator", "audited_filing", "official_product_data"}
REQUIRED = ("evidence_id", "local_path", "source_tier", "source_locator", "published_at", "claim")


class IntakeError(ValueError):
    pass


def _timestamp(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntakeError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntakeError(f"{label} is not ISO-8601: {value}") from exc
    if parsed.tzinfo is None:
        raise IntakeError(f"{label} must carry a timezone offset")
    return value


def build_evidence(manifest: dict, evidence_root: Path, *, retrieved_at: str) -> dict:
    root = evidence_root.resolve(strict=True)
    if not root.is_dir():
        raise IntakeError("evidence root must be a directory")
    _timestamp(retrieved_at, "retrieved_at")
    items, rejected, seen = [], [], set()
    for index, entry in enumerate(manifest.get("evidence") or []):
        missing = [field for field in REQUIRED if not entry.get(field)]
        if missing:
            rejected.append({"index": index, "reason": "missing fields: " + ", ".join(missing)})
            continue
        evidence_id = str(entry["evidence_id"])
        if evidence_id in seen:
            rejected.append({"index": index, "evidence_id": evidence_id,
                             "reason": "duplicate evidence_id"})
            continue
        if entry["source_tier"] not in SOURCE_TIERS:
            rejected.append({"index": index, "evidence_id": evidence_id,
                             "reason": f"unsupported source_tier: {entry['source_tier']}"})
            continue
        locator = str(entry["source_locator"])
        if not locator.startswith(("http://", "https://")):
            rejected.append({"index": index, "evidence_id": evidence_id,
                             "reason": "source_locator must be an http(s) URL"})
            continue
        relative = str(entry["local_path"])
        if "\\" in relative or PureWindowsPath(relative).drive:
            rejected.append({"index": index, "evidence_id": evidence_id,
                             "reason": "local_path must be a relative posix path"})
            continue
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            rejected.append({"index": index, "evidence_id": evidence_id,
                             "reason": "local_path escapes the evidence root"})
            continue
        target = root / candidate
        if not target.is_file():
            rejected.append({"index": index, "evidence_id": evidence_id,
                             "reason": f"file not found: {relative}"})
            continue
        raw = target.read_bytes()
        items.append({
            "evidence_id": evidence_id,
            "source_tier": entry["source_tier"],
            "source_locator": locator,
            "published_at": _timestamp(entry["published_at"], "published_at"),
            "retrieved_at": retrieved_at,
            "content_sha256": hashlib.sha256(raw).hexdigest(),
            "claim": str(entry["claim"]),
            "local_path": relative,
            "byte_count": len(raw),
        })
        seen.add(evidence_id)
    if not items:
        raise IntakeError("no usable evidence items were supplied")
    return {"evidence_items": items, "rejected": rejected}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bind operator-supplied Thesis evidence.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--retrieved-at", required=True)
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        bundle = build_evidence(manifest, Path(args.evidence_root), retrieved_at=args.retrieved_at)
    except (OSError, ValueError, IntakeError) as exc:
        print(json.dumps({"status": "failed", "detail_status": "evidence_intake_invalid",
                          "errors": [f"{type(exc).__name__}: {exc}"]}, ensure_ascii=False, indent=2))
        return 2
    payload = {
        "schema_version": "pia_operator_evidence_v1",
        "authority_status": "operator_supplied",
        "channel_status": "operator_feed",
        "note": ("Documents were supplied by the operator because the disclosure channels were "
                 "unavailable. Hash binding proves byte identity only; it is not publisher "
                 "authentication and not a statement that the claim is true."),
        "evidence_items": bundle["evidence_items"],
        "rejected": bundle["rejected"],
        "evidence_file": args.out,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "complete" if not bundle["rejected"] else "partial",
                      "evidence_count": len(bundle["evidence_items"]),
                      "rejected_count": len(bundle["rejected"]),
                      "out": args.out}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
