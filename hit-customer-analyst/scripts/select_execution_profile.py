#!/usr/bin/env python3
"""Select a safe discovery-call execution profile before any business side effect.

This selector is a routing aid, not a trust oracle.  A protected workflow still
has to validate every signed receipt in the existing preflight/build/commit
chain.  When those capabilities are absent, only a non-persistent public draft
for the first three business modes is allowed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Iterable


BUSINESS_MODES = ("briefing", "standard_visit", "strategic_account", "letter")
DATA_SCOPES = ("public_only", "authorized_internal", "mixed", "unknown")
REQUESTED_OUTCOMES = (
    "draft",
    "official_workspace",
    "ready",
    "release",
    "external_version",
    "external_send",
)
PUBLIC_DRAFT_MODES = {"briefing", "standard_visit", "strategic_account"}
PUBLIC_DRAFT_VALIDATOR_PATH = Path(__file__).resolve().with_name("validate_public_draft.py")
PUBLIC_DRAFT_VALIDATOR_ARGV = [
    str(Path(sys.executable).resolve()),
    "-B",
    str(PUBLIC_DRAFT_VALIDATOR_PATH),
]
PUBLIC_DRAFT_RESEARCH_BUDGETS = {
    "briefing": {
        "public_tool_calls_max": 6,
        "public_searches_max": 3,
        "direct_sources_target_max": 5,
        "delegated_workers_max": 0,
    },
    "standard_visit": {
        "public_tool_calls_max": 12,
        "public_searches_max": 6,
        "direct_sources_target_max": 10,
        "delegated_workers_max": 0,
    },
    "strategic_account": {
        "public_tool_calls_max": 18,
        "public_searches_max": 9,
        "direct_sources_target_max": 15,
        "delegated_workers_max": 0,
    },
}
HIGH_RISK_RESPONSE_SECTIONS = ["拒绝项", "逐项原因", "可做部分", "所需补充材料", "实名审批路径"]
FORBIDDEN_PUBLIC_DRAFT_OPERATIONS = [
    "approve",
    "create_candidate",
    "create_workspace",
    "external_send",
    "external_write",
    "internal_connector",
    "mark_ready",
    "release",
]
PREFLIGHT_ONLY_FORBIDDEN_OPERATIONS = [
    "approve",
    "build_candidate",
    "commit",
    "create_workspace",
    "external_send",
    "external_write",
    "internal_connector",
    "mark_ready",
    "public_web_open",
    "public_web_search",
    "release",
]


def _json_mapping_present(name: str) -> bool:
    raw = os.environ.get(name, "")
    if not raw:
        return False
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(value, dict) and bool(value)


def _text_present(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capability_manifest() -> dict[str, bool]:
    nonce_available = _text_present("DISCOVERY_CALL_GOVERNANCE_NONCE_DIR")
    return {
        "request_binding": _json_mapping_present("DISCOVERY_CALL_INTAKE_TRUSTED_KEYS_JSON")
        and _json_mapping_present("DISCOVERY_CALL_CURRENT_REQUEST_CONTEXT_JSON"),
        "source_capture": _json_mapping_present("DISCOVERY_CALL_CAPABILITY_TRUSTED_KEYS_JSON"),
        "candidate_attestation": _json_mapping_present("DISCOVERY_CALL_CANDIDATE_TRUSTED_KEYS_JSON")
        and nonce_available,
        "governance": nonce_available
        and _text_present("DISCOVERY_CALL_GOVERNANCE_PUBLIC_KEY_B64")
        and _text_present("DISCOVERY_CALL_GOVERNANCE_TRUSTED_ISSUER")
        and _text_present("DISCOVERY_CALL_GOVERNANCE_TRUSTED_KEY_ID"),
    }


def _base_payload(
    *,
    business_mode: str,
    capabilities: dict[str, bool],
    conflicts: Iterable[str],
) -> dict[str, object]:
    missing = sorted(name for name, available in capabilities.items() if not available)
    return {
        "schema": "discovery-call-execution-profile/v1",
        "business_mode": business_mode,
        "capabilities": capabilities,
        "formal_path_available": not missing,
        "missing_capabilities": missing,
        "conflict_fields": sorted(set(conflicts)),
        "formal_authorized": False,
        "ready_for_use": False,
        "release_eligible": False,
        "requires_output_validation": False,
    }


def select_profile(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    capabilities = capability_manifest()
    payload = _base_payload(
        business_mode=args.business_mode,
        capabilities=capabilities,
        conflicts=args.unresolved_conflict,
    )

    risk_codes = sorted(set(args.risk_code))
    if args.requested_outcome == "external_send" and "direct_external_send" not in risk_codes:
        risk_codes.append("direct_external_send")
        risk_codes.sort()
    if risk_codes:
        payload.update(
            {
                "execution_profile": "blocked_high_risk",
                "allowed": False,
                "allowed_operations": [],
                "forbidden_operations": FORBIDDEN_PUBLIC_DRAFT_OPERATIONS,
                "question_count": 0,
                "reason_codes": risk_codes,
                "response_sections": HIGH_RISK_RESPONSE_SECTIONS,
                "result_state": "blocked",
            }
        )
        return 4, payload

    if args.unresolved_conflict:
        payload.update(
            {
                "execution_profile": "blocked_conflict",
                "allowed": False,
                "allowed_operations": [],
                "forbidden_operations": FORBIDDEN_PUBLIC_DRAFT_OPERATIONS,
                "question_count": 1,
                "reason_codes": ["unresolved_high_impact_conflict"],
                "result_state": "blocked",
            }
        )
        return 3, payload

    formal_path_available = bool(payload["formal_path_available"])
    if formal_path_available:
        payload.update(
            {
                "execution_profile": "protected_workflow_candidate",
                "allowed": True,
                "allowed_operations": ["signed_preflight"],
                "forbidden_operations": PREFLIGHT_ONLY_FORBIDDEN_OPERATIONS,
                "question_count": 0,
                "reason_codes": [],
                "requires_signed_preflight": True,
                "result_state": "preflight_required",
            }
        )
        return 0, payload

    host_required = (
        args.data_scope != "public_only"
        or args.contains_sensitive_material
        or args.business_mode == "letter"
        or args.requested_outcome in {"official_workspace", "ready", "release", "external_version"}
    )
    if host_required:
        reasons = ["protected_host_capability_missing"]
        if args.data_scope != "public_only":
            reasons.append("nonpublic_data_requires_protected_host")
        if args.contains_sensitive_material:
            reasons.append("sensitive_material_requires_protected_host")
        if args.business_mode == "letter":
            reasons.append("letter_requires_protected_host")
        if args.requested_outcome in {"official_workspace", "ready", "release", "external_version"}:
            reasons.append("official_state_requires_protected_host")
        payload.update(
            {
                "execution_profile": "blocked_host_required",
                "allowed": False,
                "allowed_operations": [],
                "forbidden_operations": FORBIDDEN_PUBLIC_DRAFT_OPERATIONS,
                "may_offer_public_draft": (
                    args.business_mode in PUBLIC_DRAFT_MODES
                    and args.data_scope == "public_only"
                    and not args.contains_sensitive_material
                ),
                "question_count": 1,
                "reason_codes": reasons,
                "result_state": "blocked",
            }
        )
        return 3, payload

    payload.update(
        {
            "execution_profile": "public_draft",
            "allowed": True,
            "allowed_operations": [
                "public_web_open",
                "public_web_search",
                "validate_public_draft",
            ],
            "forbidden_operations": FORBIDDEN_PUBLIC_DRAFT_OPERATIONS,
            "question_count": 0,
            "reason_codes": ["protected_host_unavailable_public_draft_only"],
            "requires_signed_preflight": False,
            "requires_output_validation": True,
            "research_budget": PUBLIC_DRAFT_RESEARCH_BUDGETS[args.business_mode],
            "research_stop_contract": {
                "count_search_and_open_calls_together": True,
                "delegate_research": False,
                "on_budget_exhausted": "deliver_partial_with_evidence_warning",
                "validation_after_last_edit_required": True,
            },
            "output_validation": {
                "argv": PUBLIC_DRAFT_VALIDATOR_ARGV,
                "cwd": str(PUBLIC_DRAFT_VALIDATOR_PATH.parents[1]),
                "input_transport": "stdin",
                "must_pass_before_delivery": True,
                "schema": "discovery-call-public-draft-validation/v1",
                "script_sha256": _sha256_file(PUBLIC_DRAFT_VALIDATOR_PATH),
            },
            "result_state": "draft_for_review",
        }
    )
    return 0, payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="在任何检索或业务写入前选择认证正式流程、公开资料草稿或失败关闭。"
    )
    parser.add_argument("--business-mode", required=True, choices=BUSINESS_MODES)
    parser.add_argument("--data-scope", required=True, choices=DATA_SCOPES)
    parser.add_argument("--requested-outcome", required=True, choices=REQUESTED_OUTCOMES)
    parser.add_argument(
        "--unresolved-conflict",
        action="append",
        default=[],
        metavar="FIELD",
        help="尚未消解的高影响字段；可重复，存在时固定只问一个合并问题。",
    )
    parser.add_argument(
        "--risk-code",
        action="append",
        default=[],
        metavar="CODE",
        help="已识别高风险指令；可重复，存在时使用五段拒绝且问题数为0。",
    )
    parser.add_argument("--contains-sensitive-material", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return_code, payload = select_profile(args)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
