"""Deterministic validator for collaboration-audit JSON.

Only machine-verifiable contract violations are fatal. Editorial quality,
keyword coverage, item counts and recommendation quality are warnings.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REQUIRED_TOP_LEVEL = [
    "version",
    "behavioral_analysis",
    "friction_analysis",
    "workflow_engineering",
    "suggestions",
    "at_a_glance",
    "distributions",
]
REPORT_METRIC_SECTIONS = [
    "wait",
    "skill_load",
    "retry",
    "subagent",
    "authorization",
    "context",
]
UNRESOLVED_SENTINELS = {"TBD", "<TBD>", "[TBD]", "LLM_PENDING"}


class ValidationError(Exception):
    pass


def _require_object(payload, key, errors):
    value = payload.get(key)
    if not isinstance(value, dict):
        errors.append(f"{key} must be an object")
        return {}
    return value


def _require_list(container, key, path, errors):
    value = container.get(key)
    if not isinstance(value, list):
        errors.append(f"{path}.{key} must be a list")
        return []
    return value


def _optional_list(container, key, path, errors):
    value = container.get(key, [])
    if not isinstance(value, list):
        errors.append(f"{path}.{key} must be a list when supplied")
        return []
    return value


def _required_item_keys(items, path, keys, errors):
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{path}[{index}] must be an object")
            continue
        missing = [key for key in keys if key not in item]
        if missing:
            errors.append(f"{path}[{index}] missing fields: {', '.join(missing)}")
            continue
        for key in keys:
            value = item[key]
            if isinstance(value, str):
                normalized = value.strip()
                if (
                    not normalized
                    or normalized in UNRESOLVED_SENTINELS
                    or normalized.startswith("PENDING_")
                ):
                    errors.append(f"{path}[{index}].{key} is unresolved")


def validate_agent_payload(payload):
    """Return fatal deterministic errors for the legacy agent schema."""
    if not isinstance(payload, dict):
        return ["report must be a JSON object"]

    errors = []
    for key in REQUIRED_TOP_LEVEL:
        if key not in payload:
            errors.append(f"missing top-level field: {key}")

    if not isinstance(payload.get("version"), str) or not payload.get("version", "").strip():
        errors.append("version must be a non-empty string")

    behavioral = _require_object(payload, "behavioral_analysis", errors)
    points = _require_list(behavioral, "points", "behavioral_analysis", errors)
    _required_item_keys(points, "behavioral_analysis.points", ("description",), errors)

    friction = _require_object(payload, "friction_analysis", errors)
    categories = _require_list(friction, "categories", "friction_analysis", errors)
    _required_item_keys(
        categories,
        "friction_analysis.categories",
        ("category", "description", "root_cause_pattern"),
        errors,
    )

    workflow = _require_object(payload, "workflow_engineering", errors)
    assets = _optional_list(workflow, "prompt_assets", "workflow_engineering", errors)
    candidates = _optional_list(
        workflow, "automation_candidates", "workflow_engineering", errors
    )
    constraints = _optional_list(
        workflow, "auto_constraint_writeback", "workflow_engineering", errors
    )
    _required_item_keys(
        assets,
        "workflow_engineering.prompt_assets",
        ("asset_type", "target_friction", "copy_paste_template"),
        errors,
    )
    _required_item_keys(
        candidates,
        "workflow_engineering.automation_candidates",
        ("candidate_name", "rationale", "implementation_sketch"),
        errors,
    )
    _required_item_keys(
        constraints,
        "workflow_engineering.auto_constraint_writeback",
        ("target_file", "writeback_instruction", "trigger_friction"),
        errors,
    )

    _require_object(payload, "suggestions", errors)
    _require_object(payload, "at_a_glance", errors)
    if not isinstance(payload.get("distributions"), (dict, list)):
        errors.append("distributions must be an object or list")

    return errors


def collect_agent_warnings(payload):
    """Return non-blocking editorial and analytical review prompts."""
    if not isinstance(payload, dict):
        return []
    warnings = []
    if payload.get("schema_version") == 2:
        return (["legacy metric semantics: do not interpret missing occurrence, rationale, outcome or token-basis evidence as verified"]
                if "metric_semantics_version" not in payload else [])
    behavioral = payload.get("behavioral_analysis", {})
    if isinstance(behavioral, dict):
        points = behavioral.get("points", [])
        if isinstance(points, list) and len(points) != 8:
            warnings.append("behavioral_analysis.points does not contain the legacy suggested count of 8")
        summary = behavioral.get("coach_summary", "")
        if not isinstance(summary, str) or len(summary.strip()) < 60:
            warnings.append("coach_summary is short; review whether it explains the evidence")

    friction = payload.get("friction_analysis", {})
    if isinstance(friction, dict) and not friction.get("categories"):
        warnings.append("no friction categories were supplied")

    workflow = payload.get("workflow_engineering", {})
    if isinstance(workflow, dict):
        if not workflow.get("prompt_assets"):
            warnings.append("no prompt assets were proposed")
        if not workflow.get("automation_candidates"):
            warnings.append("no automation candidates were proposed")

    glance = payload.get("at_a_glance", {})
    if isinstance(glance, dict):
        suggested = {"whats_working", "whats_hindering", "quick_wins", "ambitious_workflows"}
        missing = sorted(suggested.difference(glance))
        if missing:
            warnings.append(f"at_a_glance omits suggested sections: {', '.join(missing)}")
    return warnings


def _validate_metric_semantics(payload, errors):
    operational = payload.get("operational_metrics", {})
    if not isinstance(operational, dict):
        return

    def count(section, key):
        value = section.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"metric {key} must be a non-negative integer")
            return 0
        return value

    def rate(section, key, numerator, denominator, available=True):
        expected = round(numerator / denominator, 4) if denominator and available else None
        value = section.get(key)
        if key not in section or isinstance(value, bool) or value != expected:
            errors.append(f"metric {key} is inconsistent with its evidence denominator")

    def conflict_coverage(conflicts, category):
        coverage = payload.get("coverage", {})
        issues = coverage.get("issues", []) if isinstance(coverage, dict) else []
        if conflicts and (not isinstance(coverage, dict) or coverage.get("status") != "partial"
                          or not isinstance(issues, list)
                          or not any(isinstance(issue, dict) and issue.get("category") == category for issue in issues)):
            errors.append(f"coverage must disclose {category}")

    skill = operational.get("skill_load")
    skill_share_eligible = False
    if isinstance(skill, dict):
        loads = count(skill, "skill_load_count")
        unknown = count(skill, "unverified_occurrence_count")
        occurrences = count(skill, "occurrence_load_count")
        invalid = count(skill, "unverifiable_load_count")
        conflicts = count(skill, "event_identity_conflict_count")
        conflict_coverage(conflicts, "event_identity_conflict")
        observed = count(skill, "observed_duplicate_load_count")
        if occurrences + unknown != loads or observed > max(0, occurrences - 1):
            errors.append("skill occurrence counts are inconsistent")
        available = not (unknown or invalid or conflicts)
        skill_share_eligible = (available and occurrences == loads and loads > 0
                                and count(skill, "token_observation_count") == loads)
        if ("duplicate_load_count" not in skill or isinstance(skill["duplicate_load_count"], bool)
                or skill["duplicate_load_count"] != (observed if available else None)):
            errors.append("duplicate_load_count must fail closed without complete occurrence identity")
        rate(skill, "duplicate_load_rate", observed, loads, available)
        candidates = count(skill, "skill_load_candidate_count")
        if not conflicts:
            matched = count(skill, "verified_candidate_count")
            exact = count(skill, "occurrence_matched_candidate_count")
            if not 0 <= exact <= matched <= min(candidates, loads):
                errors.append("candidate receipt counts are inconsistent")
            rate(skill, "receipt_coverage", matched, candidates)
            rate(skill, "occurrence_receipt_coverage", exact, candidates)
        elif any(skill.get(key) is not None for key in ("verified_candidate_count", "receipt_coverage", "occurrence_matched_candidate_count", "occurrence_receipt_coverage")):
            errors.append("candidate coverage must fail closed on identity conflict")

    retry = operational.get("retry")
    if isinstance(retry, dict):
        total = count(retry, "retry_count")
        blind = count(retry, "blind_retry_count")
        rationale = count(retry, "rationale_recorded_retry_count")
        unknown = count(retry, "unverified_retry_count")
        conflicts = count(retry, "conflicting_retry_evidence_count")
        conflict_coverage(conflicts, "conflicting_retry_evidence")
        if blind + rationale + unknown != total or conflicts > unknown:
            errors.append("retry classification counts are inconsistent")
        rate(retry, "blind_retry_rate", blind, blind + rationale)
        rate(retry, "retry_classification_coverage", blind + rationale, total)

    auth = operational.get("authorization")
    if isinstance(auth, dict):
        writes = count(auth, "write_event_count")
        attempts = count(auth, "write_attempt_count")
        commit_events = count(auth, "write_commit_event_count")
        commits = count(auth, "write_commit_count")
        unmatched = count(auth, "unmatched_write_count")
        unknown = count(auth, "uncertain_write_outcome_count")
        if unmatched > commits or commits > commit_events or attempts + commit_events > writes:
            errors.append("write outcome counts are inconsistent")
        rate(auth, "unmatched_write_rate", unmatched, commits)
        coverage = payload.get("coverage", {})
        complete = isinstance(coverage, dict) and coverage.get("status") == "complete"
        expected = ("outcome_uncertain" if not complete or unknown else
                    "confirmed_commits_unmatched" if commits and unmatched else
                    "confirmed_commits_matched" if commits else
                    "attempts_without_confirmed_commit" if writes else "no_write_intent_observed")
        if auth.get("authorization_evidence_status") != expected:
            errors.append("authorization_evidence_status is inconsistent with intent/outcome/coverage")

    context = operational.get("context")
    if isinstance(context, dict):
        required = ("skill_input_token_share", "skill_input_token_share_reason",
                    "skill_input_token_share_numerator", "skill_input_token_share_denominator",
                    "skill_input_token_share_coverage", "input_measurement_observation_count",
                    "compatible_scope_count")
        if any(key not in context for key in required):
            errors.append("context is missing token share evidence fields")
        observations = count(context, "input_measurement_observation_count")
        scopes = count(context, "compatible_scope_count")
        if scopes > observations:
            errors.append("compatible_scope_count exceeds input measurement observations")
        rate(context, "skill_input_token_share_coverage", scopes, observations)
        share = context.get("skill_input_token_share")
        reason = context.get("skill_input_token_share_reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append("skill_input_token_share_reason is required")
        if share is not None:
            numerator = count(context, "skill_input_token_share_numerator")
            denominator = count(context, "skill_input_token_share_denominator")
            if (not isinstance(share, (int, float)) or isinstance(share, bool)
                    or not math.isfinite(share) or not 0 <= share <= 1
                    or reason != "compatible" or context.get("skill_input_token_share_coverage") != 1
                    or not skill_share_eligible or observations <= 0 or scopes <= 0
                    or denominator <= 0 or numerator > denominator
                    or not isinstance(payload.get("coverage"), dict)
                    or payload["coverage"].get("status") != "complete"):
                errors.append("skill_input_token_share requires compatible complete measurement evidence")
            rate(context, "skill_input_token_share", numerator, denominator)
        elif (reason == "compatible" or context.get("skill_input_token_share_numerator") is not None
              or context.get("skill_input_token_share_denominator") is not None):
            errors.append("unavailable skill token share must not carry a compatible basis or operands")


def validate_report_payload(payload):
    """Return fatal deterministic errors for schema-version-2 audit output."""
    if not isinstance(payload, dict):
        return ["report must be a JSON object"]
    errors = []
    if payload.get("schema_version") != 2:
        errors.append("schema_version must be 2")

    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        errors.append("coverage must be an object")
    else:
        status = coverage.get("status")
        if status not in {"complete", "partial", "empty", "not_provided"}:
            errors.append("coverage.status is invalid")
        issues = coverage.get("issues")
        if not isinstance(issues, list):
            errors.append("coverage.issues must be a list")
        elif status in {"partial", "empty"} and not issues:
            errors.append(f"coverage.issues must explain {status} coverage")

    count = payload.get("record_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        errors.append("record_count must be a non-negative integer")
    if not isinstance(payload.get("components"), list):
        errors.append("components must be a list")
    if not isinstance(payload.get("failure_types"), dict):
        errors.append("failure_types must be an object")

    operational = payload.get("operational_metrics")
    if not isinstance(operational, dict):
        errors.append("operational_metrics must be an object")
    else:
        for section in REPORT_METRIC_SECTIONS:
            if not isinstance(operational.get(section), dict):
                errors.append(f"operational_metrics.{section} is missing")

    if not isinstance(payload.get("limitations"), list):
        errors.append("limitations must be a list")
    if "metric_semantics_version" in payload:
        if type(payload["metric_semantics_version"]) is not int or payload["metric_semantics_version"] != 2:
            errors.append("metric_semantics_version must be 2 when supplied")
        else:
            _validate_metric_semantics(payload, errors)
    return errors


def validate_file(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = (
        validate_report_payload(payload)
        if payload.get("schema_version") == 2
        else validate_agent_payload(payload)
    )
    if errors:
        raise ValidationError("\n".join(errors))
    return payload


def main():
    if len(sys.argv) != 2:
        print("Usage: python validate_agent_audit.py <agent_audit_result.json>")
        return 2
    target = sys.argv[1]
    try:
        payload = validate_file(target)
    except FileNotFoundError:
        print(f"VALIDATION_FAIL: file not found: {target}")
        return 1
    except UnicodeDecodeError as exc:
        print(f"VALIDATION_FAIL: input is not valid UTF-8: {exc}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"VALIDATION_FAIL: invalid json: {exc}")
        return 1
    except ValidationError as exc:
        print("VALIDATION_FAIL:")
        for line in str(exc).splitlines():
            print(f" - {line}")
        return 1

    print("VALIDATION_PASS")
    for warning in collect_agent_warnings(payload):
        print(f"[WARN] {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
