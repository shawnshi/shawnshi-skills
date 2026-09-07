"""Explicit, source-bound annotations; no transcript classification or collection.

Only compact annotation projections and delivery fingerprints are retained. Evidence
pointers are declarations, not independently opened or authenticated by this module.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict

EVENT_TYPE = "collaboration_annotation"
INTERVENTIONS = ("necessary_decision", "new_requirement", "information_completion",
                 "repeated_authorization", "correction", "recovery_nudge", "unknown")
REWORK = ("changed_requirement", "misunderstanding", "execution", "quality", "recovery", "unknown")
OUTCOMES = ("success", "failed", "blocked", "abandoned", "incomplete", "unknown")
COMMON = {"kind", "provenance", "evidence"}
FIELDS = {
    "outcome": {"result", "lifecycle", "lifecycle_source", "lifecycle_evidence",
                "acceptance", "acceptance_evidence", "deliverable_id", "outcome_version"},
    "intervention": {"reason"},
    "rework": {"reason", "original_root_task_id", "original_deliverable_id", "revision_id"},
    "remedy": {"remedy_id", "remedy_version", "failure_signature", "cohort", "implementation_validation"},
    "followup": {"remedy_id", "remedy_version", "failure_signature", "cohort", "exposure_id",
                 "after_remedy", "comparability", "recurrence", "operational_validation"},
}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", value) is not None


def _pointers(value):
    # source:line[-line] or source#stable-anchor; no free-form evidence prose.
    return isinstance(value, list) and bool(value) and all(
        isinstance(v, str) and re.fullmatch(r"[^\s]+(?::[1-9][0-9]*(?:-[1-9][0-9]*)?|#[A-Za-z0-9._:-]+)", v)
        for v in value)


def _positive_int(value):
    return type(value) is int and value > 0


def _fraction(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


def _validate(a):
    if not isinstance(a, dict) or not isinstance(a.get("kind"), str) or a["kind"] not in FIELDS:
        return "annotation kind must be recognized"
    kind = a["kind"]
    if set(a) - COMMON - FIELDS[kind]:
        return "annotation contains unsupported fields"
    if a.get("provenance") not in ("user", "runtime", "reviewer") or not _pointers(a.get("evidence")):
        return "annotation requires provenance and nonempty evidence pointers"
    if kind == "outcome":
        if (a.get("result") not in OUTCOMES or a.get("lifecycle") not in ("settled", "in_progress", "unknown")
                or a.get("acceptance") not in ("passed", "failed", "not_run", "unknown")):
            return "outcome requires closed result, lifecycle and acceptance labels"
        if a["result"] == "success" and a["acceptance"] == "failed":
            return "success contradicts failed acceptance"
        if "outcome_version" in a and not _positive_int(a["outcome_version"]):
            return "outcome_version must be a positive integer (not bool)"
        if a["lifecycle"] == "settled" and (a.get("lifecycle_source") != "runtime_settled"
                                               or not _pointers(a.get("lifecycle_evidence"))):
            return "settled lifecycle requires runtime source and evidence"
        if "lifecycle_source" in a and a["lifecycle_source"] not in ("runtime_settled", "unknown"):
            return "unrecognized lifecycle source"
        if a["acceptance"] in ("passed", "failed") and (
                not _pointers(a.get("acceptance_evidence")) or not _identifier(a.get("deliverable_id"))):
            return "acceptance requires evidence and the tested deliverable ID"
        for field in ("lifecycle_evidence", "acceptance_evidence"):
            if field in a and not _pointers(a[field]):
                return "supplied evidence pointers must be nonempty lists"
        if "deliverable_id" in a and not _identifier(a["deliverable_id"]):
            return "deliverable_id must be nonempty"
    elif kind in ("intervention", "rework"):
        if a.get("reason") not in (INTERVENTIONS if kind == "intervention" else REWORK):
            return "reason must use the documented vocabulary (unknown is valid)"
        if kind == "rework" and not all(_identifier(a.get(f)) for f in
                                       ("original_root_task_id", "original_deliverable_id", "revision_id")):
            return "rework requires original task, deliverable and revision IDs"
    else:
        if not all(_identifier(a.get(f)) for f in ("remedy_id", "failure_signature", "cohort")) or not _positive_int(a.get("remedy_version")):
            return "remedy link requires IDs, cohort and positive integer version"
        if kind == "remedy":
            if a.get("implementation_validation") not in ("passed", "failed", "not_run", "unknown"):
                return "implementation_validation must use the documented vocabulary"
        elif (not _identifier(a.get("exposure_id")) or type(a.get("after_remedy")) is not bool
              or a.get("comparability") not in ("comparable", "not_comparable", "unknown")
              or a.get("recurrence") not in ("observed", "not_observed", "unknown")
              or a.get("operational_validation") not in ("passed", "failed", "not_run", "unknown")):
            return "followup requires exposure, boolean order assertion and closed observation labels"
    return None


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _link(a):
    return tuple(a[f] for f in ("remedy_id", "remedy_version", "failure_signature", "cohort"))


class CollaborationAnalysis:
    def __init__(self):
        self.roots = set()
        self.deliveries = {}
        self.conflicts = set()
        self.invalid_without_identity = 0
        self.invalid_roots = set()
        self.conflicting_links = set()
        self.supplied_exposures = set()
        self.issues = []

    def _issue(self, category, detail):
        issue = {"source": "<collaboration_annotations>", "category": category, "detail": detail}
        if issue not in self.issues:
            self.issues.append(issue)

    def update(self, record):
        root = record.get("root_task_id")
        if _text(root):
            self.roots.add(root)
        if str(record.get("event_type", "")).strip().lower() != EVENT_TYPE:
            return
        event_id = record.get("event_id")
        if not _identifier(root) or not _identifier(event_id) or record.get("event_identity") != "occurrence":
            self.invalid_without_identity += 1
            if _text(root):
                self.invalid_roots.add(root)
            self._issue("invalid_collaboration_annotation", "occurrence identity and root task are required")
            return
        key = (root, event_id)
        a = record.get("annotation")
        if _validate(a) is None and a["kind"] == "followup":
            self.supplied_exposures.add((_link(a), a["exposure_id"]))
        fingerprint = hashlib.sha256(_canonical(a).encode("utf-8")).hexdigest()
        if key in self.deliveries:
            if self.deliveries[key][0] != fingerprint:
                self.conflicts.add(key)
                for claim in (self.deliveries[key][1], a):
                    if _validate(claim) is None and claim["kind"] in ("remedy", "followup"):
                        self.conflicting_links.add(_link(claim))
                self._issue("conflicting_collaboration_annotation", "same occurrence identity has conflicting annotations")
            return
        error = _validate(a)
        if error:
            self.invalid_roots.add(root)
            self._issue("invalid_collaboration_annotation", error)
        # Invalid payloads are not retained; arbitrary prose never enters the report.
        self.deliveries[key] = (fingerprint, None if error else dict(a))

    def finalize(self, coverage: dict) -> tuple[dict, dict]:
        valid = [(root, eid, a) for (root, eid), (_, a) in self.deliveries.items()
                 if a is not None and (root, eid) not in self.conflicts]
        by_kind = defaultdict(list)
        for root, eid, a in valid:
            by_kind[a["kind"]].append((root, eid, a))
        tasks = self._tasks(by_kind["outcome"])
        remedies = self._remedies(by_kind["remedy"], by_kind["followup"])
        observed = len(self.deliveries) + self.invalid_without_identity
        result = {
            "analysis_version": 1,
            "status": "partial" if self.issues else "available" if valid else "unavailable",
            "scope": "supplied_records_only",
            "source_coverage_status": "partial" if self.issues else coverage.get("status", "not_provided"),
            "annotation_observation_count": observed,
            "valid_annotation_count": len(valid),
            "annotation_coverage": _fraction(len(valid), observed),
            "conflicting_identity_count": len(self.conflicts),
            "task_outcomes": tasks,
            "user_interventions": self._labels(by_kind["intervention"], INTERVENTIONS),
            "rework": self._labels(by_kind["rework"], REWORK),
            "remediation_followup": remedies,
            "evidence_sources": sorted({p for _, _, a in valid for field in
                                        ("evidence", "lifecycle_evidence", "acceptance_evidence")
                                        for p in a.get(field, [])}),
            "limitations": ["Pointers and provenance are supplied assertions, not authenticated source contents.",
                            "Coverage concerns supplied annotations, not all user messages or historical tasks.",
                            "No attention minutes, causal savings, personality inference or operational benefit score.",
                            "Implementation validation is not operational benefit; no observed exposure is not zero recurrence."],
        }
        if self.issues:
            coverage = {**coverage, "status": "partial", "issues": [*coverage.get("issues", []), *self.issues]}
        return result, coverage

    def _tasks(self, records):
        groups = defaultdict(list)
        for root, eid, a in records:
            groups[root].append((eid, a))
        rows = []
        for root in sorted(self.roots):
            entries = groups[root]
            status, reason = "unknown", "missing_outcome_evidence"
            chosen = None
            if entries:
                # Identical claims may have different deliveries; never choose by file order.
                unique = {_canonical(a): a for _, a in entries}
                claims = list(unique.values())
                if len(claims) == 1:
                    chosen = claims[0]
                elif (all("outcome_version" in a for a in claims)
                      and len({a["outcome_version"] for a in claims}) == len(claims)):
                    chosen = max(claims, key=lambda a: a["outcome_version"])
                else:
                    status, reason = "conflict", "unordered_or_conflicting_outcome_history"
                    self._issue("conflicting_task_outcome", "outcome histories require distinct explicit versions")
            if root in self.invalid_roots:
                chosen = None
                status, reason = "unknown", "invalid_annotation_evidence"
            if any(key[0] == root for key in self.conflicts):
                # Cannot establish which connection a conflicting delivery intended to change.
                chosen = None
                status, reason = "conflict", "conflicting_annotation_identity"
            if chosen:
                status, reason = chosen["result"], "explicit_outcome"
                if status == "success" and not (chosen["lifecycle"] == "settled" and chosen["acceptance"] == "passed"):
                    status, reason = "unknown", "success_requires_settled_lifecycle_and_passed_acceptance"
                elif status in ("failed", "abandoned") and chosen["lifecycle"] != "settled":
                    status, reason = "unknown", "terminal_result_requires_settled_lifecycle"
            rows.append({"root_task_id": root, "status": status, "reason": reason,
                         "selected_outcome_version": chosen.get("outcome_version") if chosen else None,
                         "selected_outcome": chosen,
                         "evidence": sorted({p for _, a in entries for f in
                                             ("evidence", "lifecycle_evidence", "acceptance_evidence") for p in a.get(f, [])})})
        counts = {s: sum(r["status"] == s for r in rows) for s in (*OUTCOMES, "conflict")}
        known = sum(counts[s] for s in OUTCOMES if s != "unknown")
        return {"status": "available" if known else "unavailable", "root_task_count": len(rows),
                "classified_task_count": known, "classification_coverage": _fraction(known, len(rows)),
                "status_counts": counts, "accepted_success_count": counts["success"],
                "success_denominator": known, "accepted_success_rate": _fraction(counts["success"], known),
                "tasks": rows}

    @staticmethod
    def _labels(records, vocabulary):
        counts = Counter(a["reason"] for _, _, a in records)
        labeled = len(records) - counts["unknown"]
        return {"status": "available" if labeled else "unavailable", "evidenced_annotation_count": len(records),
                "labeled_count": labeled, "unknown_reason_count": counts["unknown"],
                "label_coverage": _fraction(labeled, len(records)),
                "reason_counts": {label: counts[label] for label in vocabulary},
                "annotations": [{"root_task_id": root, "event_id": eid, **a}
                                for root, eid, a in sorted(records, key=lambda r: (r[0], r[1]))]}

    def _remedies(self, remedies, followups):
        groups, exposures = defaultdict(list), defaultdict(list)
        for _, _, a in remedies:
            groups[_link(a)].append(a)
        for _, _, a in followups:
            exposures[(_link(a), a["exposure_id"])].append(a)
        rows = []
        for link in sorted(set(groups) | {k[0] for k in exposures} | self.conflicting_links):
            declarations = {_canonical(a) for a in groups[link]}
            conflict = len(declarations) > 1 or link in self.conflicting_links
            if conflict:
                self._issue("conflicting_remedy_evidence", "same remedy version has conflicting implementation evidence")
            linked = len(declarations) == 1
            eligible, observed, recurrent, passed = 0, 0, 0, 0
            total = sum(key == link for key, _ in self.supplied_exposures)
            pointers = {p for a in groups[link] for p in a["evidence"]}
            for (key, _), values in exposures.items():
                if key != link:
                    continue
                pointers.update(p for a in values for p in a["evidence"])
                if len({_canonical(a) for a in values}) != 1:
                    conflict = True
                    self._issue("conflicting_followup_evidence", "same exposure identity has conflicting observations")
                    continue
                a = values[0]
                if linked and a["after_remedy"] and a["comparability"] == "comparable":
                    eligible += 1
                    if a["recurrence"] != "unknown":
                        observed += 1
                        recurrent += a["recurrence"] == "observed"
                    passed += a["operational_validation"] == "passed"
            if conflict:
                eligible = observed = recurrent = passed = 0
            rows.append({"remedy_id": link[0], "remedy_version": link[1], "failure_signature": link[2], "cohort": link[3],
                         "status": "conflict" if conflict else "available" if observed else "unavailable",
                         "reason": "conflicting_evidence" if conflict else "missing_remedy_link" if not linked
                         else "no_comparable_observed_exposure" if not observed else "observed_subset_only",
                         "supplied_exposure_count": total, "comparable_exposure_count": eligible,
                         "observed_recurrence_denominator": observed,
                         "recurrence_count": recurrent if observed else None,
                         "recurrence_rate": _fraction(recurrent, observed),
                         "observation_coverage": _fraction(observed, eligible),
                         "operational_validation_pass_count": passed if eligible else None,
                         "implementation_validation": groups[link][0]["implementation_validation"] if linked else "unknown",
                         "evidence": sorted(pointers)})
        return {"status": "available" if any(r["status"] == "available" for r in rows) else "unavailable", "cohorts": rows}
