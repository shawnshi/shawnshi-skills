"""Collection/read coverage is not semantic rejection or proof of article quality."""
from __future__ import annotations

from collections import Counter
import re

STRATEGIC_SOURCES = {
    "china_policy": ["国家卫生健康委 (NHC)", "国家医保局 (NHSA)"],
    "china_health_it": ["CHIMA", "动脉网 (VB100)"],
    "health_it": ["healthcareitnews.com", "ehrintelligence.com", "HIMSS News", "HIStalk"],
    "medical_research": ["Nature Digital Medicine", "The Lancet Digital Health", "NEJM"],
}


def source_diagnostics(scan: dict) -> dict:
    statuses = scan.get("metadata", {}).get("sources", {})
    dated = Counter(x.get("source") for x in scan.get("items", []))
    unknown = Counter(x.get("item", {}).get("source") for x in scan.get("quarantine", []))
    groups = {}
    for group, names in STRATEGIC_SOURCES.items():
        observed = [name for name in names if name in statuses]
        failed = []
        for name in observed:
            value = statuses[name]
            status = value.get("status", "") if isinstance(value, dict) else value
            if str(status).upper() not in {"OK", "SUCCESS"}:
                failed.append(name)
        groups[group] = {
            "status": "not_observed" if not observed else ("unavailable" if len(failed) == len(observed) else "partial" if failed else "reachable"),
            "configured": len(observed), "failed_sources": failed,
            "in_window_items": sum(dated[name] for name in observed),
            "unknown_date_items": sum(unknown[name] for name in observed),
        }
    return {
        "groups": groups,
        "unknown_dates_by_source": dict(sorted(unknown.items())),
        "qualification": "Reachability and dated discovery only; not verified article coverage.",
    }


def candidate_reading_priority(candidate: dict) -> int:
    text = str(candidate.get("title") or "").casefold()
    score = int(candidate.get("heuristic_rank", 0))
    # Historical recaps can be newly published without being new decision evidence.
    if re.search(r"first gpu|geforce 256|历史回顾|on this day|retrocomput|history of", text):
        score -= 30
    if candidate.get("source") in {"国家卫生健康委 (NHC)", "国家医保局 (NHSA)", "CHIMA", "HL7 International", "HealthIT.gov"}:
        score += 10
    return score


def shared_infrastructure_failure(result: dict, ledger: dict | None = None) -> bool:
    from pathlib import Path
    import hashlib
    import json
    # Infrastructure business results intentionally have no article access_log.
    # Only a registered native-tool error, not a worker description, proves scope.
    codes = {"TOOL_UNAVAILABLE", "CAPABILITY_UNAVAILABLE", "AUTH_REQUIRED", "CLIENT_CLOSING", "CLIENT_IS_CLOSING"}
    for event in (ledger or {}).get("events", []):
        receipt = event.get("receipt", {}) if event.get("kind") == "query_recorded" else {}
        if event.get("kind") == "fetch_recorded":
            raw = Path(event["proof_path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != event["proof_sha256"]:
                raise ValueError("shared failure native proof bytes changed")
            receipt = json.loads(raw.decode("utf-8")).get("receipt", {})
        error = str(receipt.get("error") or "").strip()
        code = error.split("]", 1)[0].removeprefix("[") if error.startswith("[") else re.split(r"[:\s]", error, maxsplit=1)[0]
        if receipt.get("outcome") == "error" and code in codes:
            return True
    return False


def quality_policy_enabled(manifest: dict) -> bool:
    from pathlib import Path
    import hashlib
    import json
    record = manifest.get("artifacts", {}).get("supplement_request", {})
    if not record.get("artifact_path"):
        return False
    raw = Path(record["artifact_path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != record.get("artifact_sha256"):
        raise ValueError("collection policy request bytes changed")
    return json.loads(raw.decode("utf-8")).get("collection_quality_version") == 1


def expansion_diagnostics(briefing: dict, scan: dict, supplements: dict) -> dict:
    reasons = briefing.get("candidate_funnel", {}).get("quality_gate_reasons", {})
    missing = int(reasons.get("missing_verified_access", 0))
    groups = source_diagnostics(scan)["groups"]
    deficits = [name for name, value in groups.items() if value["status"] != "reachable" or value["unknown_date_items"]]
    lane_failures = [r.get("gap_id") for r in supplements.get("results", []) if r.get("status") in {"failed", "degraded"}]
    blockers = []
    if missing:
        blockers.append(f"{missing} candidates lack verified article evidence")
    if deficits:
        blockers.append("strategic discovery/date coverage incomplete: " + ", ".join(deficits))
    if lane_failures:
        blockers.append("supplement lanes incomplete: " + ", ".join(str(x) for x in lane_failures))
    return {"allow_expansion": not blockers, "blockers": blockers, "missing_verified_access": missing,
            "action": "expand_only_if_supply_is_low" if not blockers else "repair_coverage_or_deliver_incomplete_report"}


def reading_diagnostics(briefing: dict) -> dict:
    if not isinstance(briefing.get("candidate_funnel"), dict):
        return {"disposition_records": None, "unverified": None, "semantic_rejected": None,
                "retained": None, "assessment": "unmeasured"}
    reasons = briefing.get("candidate_funnel", {}).get("quality_gate_reasons", {})
    records = briefing.get("candidate_funnel", {}).get("candidate_dispositions", [])
    missing = int(reasons.get("missing_verified_access", 0))
    return {"disposition_records": len(records), "unverified": missing,
            "semantic_rejected": int(reasons.get("semantic_not_selected", 0)),
            "retained": len(briefing.get("top_10", [])),
            "assessment": "verification_incomplete" if missing else "no_unverified_dispositions_reported"}
