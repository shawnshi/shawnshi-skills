"""Parent-only compact sealed evidence handoff; no acquisition or ledger writes."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

import article_broker as broker
import run_contract as rc
from supplement_agent import build_agent_context


def publication_options(proof, lane):
    """Project only the date bases already admitted by the authoritative validator."""
    meta = proof["metadata"]
    if meta["dates"]:
        return deepcopy(meta["dates"])
    if not meta.get("article_core"):
        return []
    url = proof["access"]["requested_url"]
    options = []
    declared = broker._lane_declared_date(lane, url)
    if declared:
        try:
            day = rc.normalize_published_at(declared["published_at"])
        except rc.RunContractError:
            day = ""
        if day:
            options.append({"parser_rule": "pool-declared/1", "published_at": day, "published_at_source": declared["published_at_source"]})
    day = broker._url_path_declared_day(url)
    if day:
        options.append({"parser_rule": "url-path/1", "published_at": day, "published_at_source": "url_path"})
    return options


def bind_registered_proof_paths(snapshot, ledger):
    """Raw broker proofs lack display paths; bind only actual hash-matched ledger refs."""
    if broker.digest(ledger) != snapshot["broker_evidence_sha256"]:
        raise rc.RunContractError("broker ledger changed before handoff")
    events = ledger["events"]
    if not events or events[-1]["kind"] != "sealed" or events[-1]["at"] != snapshot["completed_at"]:
        raise rc.RunContractError("sealed clock mismatch before handoff")
    refs = {}
    for event in events:
        if event["kind"] not in {"http_recorded", "fetch_recorded"}:
            continue
        if event["id"] in refs:
            raise rc.RunContractError("ambiguous registered proof reference")
        refs[event["id"]] = event
    bound = deepcopy(snapshot)
    for proof in bound["proofs"]:
        ref = refs.get(proof["id"])
        if not ref or not ref.get("proof_path") or ref.get("proof_sha256") != proof["proof_sha256"]:
            raise rc.RunContractError("missing or hash-mismatched registered proof reference")
        proof["proof_path"] = ref["proof_path"]
    return bound


def compact_packet(snapshot, lane, *, preview_chars=2400):
    if not snapshot.get("completed_at") or snapshot["next_action"]["action"] != "sealed":
        raise rc.RunContractError("sealed broker evidence required; collecting is not completion")
    proofs = []
    for proof in snapshot["proofs"]:
        body = proof.get("body_text", "")
        proofs.append({
            "id": proof["id"],
            "proof_path": proof["proof_path"],
            "broker_body_proof_sha256": proof["proof_sha256"],
            "access_check": deepcopy(proof["access"]),
            "metadata": deepcopy(proof["metadata"]),
            "published_at_proof_options": publication_options(proof, lane),
            "body_text_sha256": proof["body_text_sha256"],
            "native_body_truncated": proof["body_text_truncated"],
            "preview_text": body[:preview_chars],
            "preview_truncated": len(body) > preview_chars,
        })
    return {
        "state": "sealed",
        **{key: deepcopy(snapshot[key]) for key in ["request_sha256", "gap_id", "started_at", "completed_at", "broker_evidence_sha256", "executed_queries", "access_log", "required_bound_candidate_ids"]},
        "stop_reason": snapshot["next_action"]["stop_reason"],
        "proofs": proofs,
        "instruction": "Dates are projected evidence, not model certification. Use only existing validator-admitted bases, never override a body date; window, source quality, event identity and semantic gates still apply. Preview truncation is not native tool truncation. The context already supplies draft_schema: at most one batched read of registered proofs/lane, then persist the registered dynamic draft before optional validation. Parent alone finalizes.",
    }


def draft_contract(request_path, gap_id):
    """Recover only the frozen write contract when large context output is unavailable."""
    context = build_agent_context(request_path, gap_id, candidate_limit=1)
    fields = (
        "contract_version", "run_id", "request_path", "request_sha256", "lane",
        "window", "draft_path", "draft_dynamic_fields", "draft_parent_derived_fields",
        "draft_schema", "required_bound_candidate_ids", "finalize_command",
    )
    recovered = {key: deepcopy(context[key]) for key in fields}
    required_ids = set(context["required_bound_candidate_ids"])
    recovered["required_bound_candidates"] = [
        {"candidate_id": candidate["candidate_ref"], "url": candidate["url"]}
        for candidate in context["bound_candidates"]
        if candidate["candidate_ref"] in required_ids
    ]
    recovered["turns_used_rule"] = (
        "Count actual completed evidence-checking rounds, not supervisor messages or URL/tool calls. "
        "One bound-check plus broker discovery/fetch sequence is one round; zero is only valid "
        "for initialization failure before any evidence. Never exceed the registered max_turns."
    )
    recovered["max_turns"] = context["gap"]["max_turns"]
    return recovered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--gap-id", required=True)
    parser.add_argument("--draft-contract", action="store_true", help="Read-only frozen schema recovery; no evidence acquisition or clock change")
    args = parser.parse_args()
    if args.draft_contract:
        print(json.dumps(draft_contract(args.request, args.gap_id), ensure_ascii=False))
        return
    _, _, packet, _, lane, _ = broker._bound(args.request, args.gap_id)
    snapshot = broker.evidence(args.request, args.gap_id)
    ledger = rc.load_manifest(packet["run_manifest_path"])["article_broker_evidence"][args.gap_id]
    snapshot = bind_registered_proof_paths(snapshot, ledger)
    print(json.dumps(compact_packet(snapshot, lane), ensure_ascii=False))


if __name__ == "__main__":
    main()
