"""Synthetic-only Phase 2 acceptance fixtures; never actual user sessions."""
import copy
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
validate_report_payload = importlib.import_module("validate_agent_audit").validate_report_payload


def event(kind, eid="synthetic-event", root="synthetic-task", **fields):
    return {"event_type": "collaboration_annotation", "root_task_id": root,
            "event_identity": "occurrence", "event_id": eid,
            "annotation": {"kind": kind, "provenance": "reviewer", "evidence": ["synthetic.jsonl:1"], **fields}}


def outcome(eid="outcome", **fields):
    a: dict[str, Any] = dict(result="success", lifecycle="settled", lifecycle_source="runtime_settled",
             lifecycle_evidence=["synthetic-runtime.jsonl:1"], acceptance="passed",
             acceptance_evidence=["synthetic-acceptance.json:1"], deliverable_id="synthetic-deliverable")
    a.update(fields)
    return event("outcome", eid, **a)


def remedy(eid="remedy", **fields):
    a: dict[str, Any] = dict(remedy_id="R-01", remedy_version=1, failure_signature="synthetic_timeout",
             cohort="synthetic-v1-small", implementation_validation="passed")
    a.update(fields)
    return event("remedy", eid, **a)


def followup(eid="followup", **fields):
    a: dict[str, Any] = dict(remedy_id="R-01", remedy_version=1, failure_signature="synthetic_timeout",
             cohort="synthetic-v1-small", exposure_id=eid, after_remedy=True,
             comparability="comparable", recurrence="not_observed", operational_validation="passed")
    a.update(fields)
    return event("followup", eid, **a)


def supported():
    return [outcome(), event("intervention", "decision", reason="necessary_decision"),
            event("rework", "revision", reason="unknown", original_root_task_id="synthetic-task",
                  original_deliverable_id="synthetic-deliverable", revision_id="revision-1"),
            remedy(), followup("exposure-1", recurrence="observed"), followup("exposure-2")]


class CollaborationAnalysisTests(unittest.TestCase):
    def report(self, records):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "synthetic.jsonl"
            source.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
            loaded, coverage = engine.load_records(source)
            report = engine.aggregate(loaded, coverage)
            streamed = engine.aggregate_path(source)
            self.assertEqual(report, streamed, "list/stream full-report parity")
            self.assertEqual(validate_report_payload(report), [])
            return report

    def analysis(self, records):
        return self.report(records)["collaboration_analysis"]

    def test_legacy_is_valid_but_unavailable(self):
        report = self.report([dict(event_type="tool_call", root_task_id="synthetic-task", status="ok")])
        self.assertEqual(report["coverage"]["status"], "complete")
        a = report["collaboration_analysis"]
        self.assertEqual(a["status"], "unavailable")
        self.assertIsNone(a["task_outcomes"]["accepted_success_rate"])
        self.assertEqual(a["task_outcomes"]["status_counts"]["unknown"], 1)
        self.assertEqual(a["user_interventions"]["status"], "unavailable")
        self.assertEqual(a["remediation_followup"]["status"], "unavailable")

    def test_three_connections_end_to_end(self):
        a = self.analysis(supported())
        self.assertEqual(a["status"], "available")
        self.assertEqual(a["task_outcomes"]["accepted_success_count"], 1)
        self.assertEqual(a["user_interventions"]["reason_counts"]["necessary_decision"], 1)
        self.assertNotIn("waste", json.dumps(a))
        self.assertEqual(a["rework"]["unknown_reason_count"], 1)
        self.assertEqual(a["rework"]["label_coverage"], 0)
        row = a["remediation_followup"]["cohorts"][0]
        self.assertEqual((row["recurrence_count"], row["observed_recurrence_denominator"], row["recurrence_rate"]), (1, 2, 0.5))
        self.assertIn("synthetic-runtime.jsonl:1", a["evidence_sources"])

    def test_all_closed_intervention_and_rework_labels(self):
        from collaboration_analysis import INTERVENTIONS, REWORK
        records = [event("intervention", f"i-{i}", reason=reason) for i, reason in enumerate(INTERVENTIONS)]
        records += [event("rework", f"r-{i}", reason=reason, original_root_task_id="synthetic-original",
                          original_deliverable_id="original", revision_id=f"r-{i}") for i, reason in enumerate(REWORK)]
        a = self.analysis(records)
        self.assertEqual(a["user_interventions"]["labeled_count"], 6)
        self.assertEqual(a["rework"]["labeled_count"], 5)
        self.assertEqual(a["rework"]["annotations"][0]["original_root_task_id"], "synthetic-original")

    def test_missing_vs_malformed_annotations(self):
        for changes in ({"evidence": []}, {"provenance": "inferred"}, {"reason": None},
                        {"reason": "waste"}, {"raw_prompt": "synthetic-not-permitted"}, {"kind": []}):
            with self.subTest(changes=changes):
                record = event("intervention", reason="unknown")
                record["annotation"].update(changes)
                report = self.report([record])
                self.assertEqual(report["coverage"]["status"], "partial")
                self.assertEqual(report["collaboration_analysis"]["valid_annotation_count"], 0)
        self.assertEqual(self.report([event("intervention", reason="unknown")])["coverage"]["status"], "complete")

    def test_replay_does_not_inflate_any_new_metric(self):
        records = supported()
        self.assertEqual(self.analysis(records), self.analysis(records + copy.deepcopy(records)))

    def test_conflicting_occurrence_retracts_positive_results_both_orders(self):
        first, second = outcome(), outcome(acceptance="failed")
        for records in ([first, second], [second, first]):
            report = self.report(records)
            self.assertEqual(report["coverage"]["status"], "partial")
            a = report["collaboration_analysis"]
            self.assertEqual(a["conflicting_identity_count"], 1)
            self.assertEqual(a["task_outcomes"]["accepted_success_count"], 0)

    def test_premature_success_is_unknown(self):
        for fields in ({"lifecycle": "in_progress"}, {"acceptance": "not_run"}, {"acceptance": "unknown"}):
            report = self.report([outcome(**fields)])
            self.assertEqual(report["coverage"]["status"], "complete")
            self.assertEqual(report["collaboration_analysis"]["task_outcomes"]["status_counts"]["unknown"], 1)

    def test_bare_success_and_unsubstantiated_acceptance_are_invalid(self):
        for field in ("lifecycle_evidence", "lifecycle_source", "acceptance_evidence", "deliverable_id"):
            record = outcome()
            record["annotation"].pop(field)
            report = self.report([record])
            self.assertEqual(report["coverage"]["status"], "partial")
            self.assertEqual(report["collaboration_analysis"]["task_outcomes"]["accepted_success_count"], 0)

    def test_unordered_outcomes_conflict_and_versions_resolve(self):
        first, last = outcome("first", result="blocked", acceptance="not_run"), outcome("last")
        for records in ([first, last], [last, first]):
            report = self.report(records)
            self.assertEqual(report["coverage"]["status"], "partial")
            self.assertEqual(report["collaboration_analysis"]["task_outcomes"]["status_counts"]["conflict"], 1)
        first["annotation"]["outcome_version"] = 1
        last["annotation"]["outcome_version"] = 2
        self.assertEqual(self.analysis([last, first])["task_outcomes"]["accepted_success_count"], 1)
        last["annotation"]["outcome_version"] = 1
        self.assertEqual(self.report([first, last])["coverage"]["status"], "partial")

    def test_failed_blocked_abandoned_incomplete_in_denominator(self):
        records = []
        for result in ("success", "failed", "blocked", "abandoned", "incomplete"):
            r = outcome(result, result=result, acceptance="passed" if result == "success" else "not_run")
            r["root_task_id"] = "synthetic-" + result
            records.append(r)
        records.append(dict(event_type="tool_call", root_task_id="synthetic-unlabeled"))
        a = self.analysis(records)["task_outcomes"]
        self.assertEqual(a["root_task_count"], 6)
        self.assertEqual(a["success_denominator"], 5)
        self.assertEqual(a["accepted_success_rate"], 0.2)

    def test_numeric_versions_reject_bool_float_negative_and_strings(self):
        for bad in (True, False, 1.0, 0, -1, "1", [], None):
            for record in (outcome(outcome_version=bad), remedy(remedy_version=bad), followup(remedy_version=bad)):
                self.assertEqual(self.report([record])["coverage"]["status"], "partial")
        self.assertEqual(self.report([followup(after_remedy=1)])["coverage"]["status"], "partial")

    def test_no_exposure_is_not_zero_recurrence_or_operational_benefit(self):
        row = self.analysis([remedy()])["remediation_followup"]["cohorts"][0]
        self.assertEqual(row["implementation_validation"], "passed")
        self.assertEqual(row["status"], "unavailable")
        self.assertIsNone(row["recurrence_count"])
        self.assertIsNone(row["recurrence_rate"])
        self.assertIsNone(row["operational_validation_pass_count"])

    def test_followup_requires_link_order_comparability_and_observation(self):
        records = [remedy(), followup("ok"), followup("unknown", recurrence="unknown"),
                   followup("before", after_remedy=False), followup("different", comparability="not_comparable"),
                   followup("other-version", remedy_version=2)]
        rows = self.analysis(records)["remediation_followup"]["cohorts"]
        self.assertEqual(rows[0]["comparable_exposure_count"], 2)
        self.assertEqual(rows[0]["observed_recurrence_denominator"], 1)
        self.assertEqual(rows[0]["observation_coverage"], 0.5)
        self.assertEqual(rows[1]["reason"], "missing_remedy_link")
        self.assertIsNone(rows[1]["recurrence_rate"])

    def test_same_exposure_different_deliveries_deduplicated_or_conflict(self):
        first = followup("first", exposure_id="same-exposure")
        replay = copy.deepcopy(first)
        replay["event_id"] = "different-delivery"
        row = self.analysis([remedy(), first, replay])["remediation_followup"]["cohorts"][0]
        self.assertEqual(row["observed_recurrence_denominator"], 1)
        replay["annotation"]["recurrence"] = "observed"
        report = self.report([remedy(), first, replay])
        self.assertEqual(report["coverage"]["status"], "partial")
        self.assertIsNone(report["collaboration_analysis"]["remediation_followup"]["cohorts"][0]["recurrence_rate"])

    def test_conflicting_followup_identity_poison_cohort(self):
        records = [remedy(), followup("first"), followup("second"), followup("first", recurrence="observed")]
        row = self.analysis(records)["remediation_followup"]["cohorts"][0]
        self.assertEqual(row["status"], "conflict")
        self.assertIsNone(row["recurrence_rate"])
        self.assertEqual(row["supplied_exposure_count"], 2)
        reversed_row = self.analysis(list(reversed(records)))["remediation_followup"]["cohorts"][0]
        self.assertEqual(reversed_row["supplied_exposure_count"], 2)

    def test_annotation_event_type_variants_fail_closed(self):
        for kind in (" collaboration_annotation ", "COLLABORATION_ANNOTATION", " Collaboration_Annotation "):
            with self.subTest(kind=kind):
                bad = outcome("bad", acceptance_evidence=[])
                bad["event_type"] = kind
                report = self.report([outcome(), bad])
                self.assertEqual(report["coverage"]["status"], "partial")
                self.assertEqual(report["collaboration_analysis"]["task_outcomes"]["accepted_success_count"], 0)

    def test_invalid_new_claim_cannot_leave_old_success_green(self):
        bad = outcome("bad", acceptance_evidence=[])
        a = self.analysis([outcome(), bad])
        self.assertEqual(a["task_outcomes"]["accepted_success_count"], 0)

    def test_no_inferred_intervention_from_continue_or_approval_count(self):
        a = self.analysis([dict(event_type="approval_request", root_task_id="synthetic-task", task_mode="read_only"),
                           dict(event_type="message", root_task_id="synthetic-task", status="continue")])
        self.assertEqual(a["user_interventions"]["status"], "unavailable")

    def test_malformed_payloads_and_pointer_prose_fail_closed(self):
        for payload in (None, [], "synthetic prose", {}, {"kind": {}}, {"kind": True}):
            r = outcome()
            r["annotation"] = payload
            self.assertEqual(self.report([r])["coverage"]["status"], "partial")
        for pointer in ("synthetic prose without locator", "synthetic.jsonl", "synthetic.jsonl:0", 1, True):
            r = event("intervention", reason="unknown", evidence=[pointer])
            self.assertEqual(self.report([r])["coverage"]["status"], "partial")
        r = event("rework", reason="unknown", original_root_task_id="synthetic original prose",
                  original_deliverable_id="original", revision_id="revision")
        self.assertEqual(self.report([r])["coverage"]["status"], "partial")

    def test_version_order_cannot_hide_internally_conflicting_evidence(self):
        records = [outcome("old", outcome_version=1, acceptance="failed"), outcome("new", outcome_version=2)]
        report = self.report(records)
        self.assertEqual(report["coverage"]["status"], "partial")
        self.assertEqual(report["collaboration_analysis"]["task_outcomes"]["accepted_success_count"], 0)

    def test_selected_outcome_preserves_provenance_and_acceptance_link(self):
        row = self.analysis([outcome()])["task_outcomes"]["tasks"][0]
        self.assertEqual(row["selected_outcome"]["provenance"], "reviewer")
        self.assertEqual(row["selected_outcome"]["deliverable_id"], "synthetic-deliverable")
        self.assertEqual(row["selected_outcome"]["acceptance"], "passed")

    def test_missing_occurrence_identity_invalid(self):
        for field in ("event_id", "event_identity"):
            r = outcome()
            r.pop(field)
            self.assertEqual(self.report([r])["coverage"]["status"], "partial")

    def test_strict_cli_exit_codes_and_validator_compatibility(self):
        cases = [(supported(), 0), ([dict(event_type="tool_call", root_task_id="synthetic-old")], 0),
                 ([event("intervention", reason="bad")], 2), ([outcome(), outcome(acceptance="failed")], 2),
                 ([outcome(lifecycle="in_progress")], 0), ([], 1)]
        for kind in (" collaboration_annotation ", "COLLABORATION_ANNOTATION", " Collaboration_Annotation "):
            bad = outcome("bad", acceptance_evidence=[])
            bad["event_type"] = kind
            cases.append(([outcome(), bad], 2))
        with tempfile.TemporaryDirectory() as tmp:
            for index, (records, expected) in enumerate(cases):
                source, output = Path(tmp) / f"synthetic-{index}.jsonl", Path(tmp) / f"report-{index}.json"
                source.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
                run = subprocess.run([sys.executable, str(ROOT / "generate_final_report.py"), "--input", str(source),
                                      "--output", str(output), "--strict"], capture_output=True, text=True,
                                     env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                self.assertEqual(run.returncode, expected, run.stderr)
                errors = validate_report_payload(json.loads(output.read_text(encoding="utf-8")))
                # Existing empty-input CLI/validator behavior is intentionally unchanged.
                self.assertEqual(errors, ["coverage.issues must explain empty coverage"] if not records else [])


if __name__ == "__main__":
    unittest.main()
