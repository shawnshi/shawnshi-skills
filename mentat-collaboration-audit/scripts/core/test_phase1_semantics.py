"""Synthetic, nonprivate regression oracles for phase-1 measured semantics."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import engine

ROOT = Path(__file__).resolve().parents[2]
COMPLETE = {"status": "complete", "issues": []}


def load(event_id="load-1", **changes):
    event = dict(event_type="skill_load", root_task_id="synthetic-task", actor_id="root",
                 context_epoch="1", skill_name="sample", skill_path_sha256="a" * 64,
                 skill_sha256="b" * 64, skill_tokens=10, tokenizer="test-native",
                 event_id=event_id, event_identity="occurrence",
                 token_measurement_basis="model_input", token_scope_id="request-1")
    event.update(changes)
    return event


def usage(**changes):
    event = dict(event_type="usage", root_task_id="synthetic-task", actor_id="root",
                 input_tokens=100, tokenizer="test-native", token_measurement_basis="model_input",
                 token_scope_id="request-1", skill_tokens_included=True,
                 skill_load_coverage_complete=True)
    event.update(changes)
    return event


def candidate(event_id="candidate-1", **changes):
    event = load(event_id, event_type="skill_load_candidate")
    event.update(changes)
    return event


class Phase1SemanticsTests(unittest.TestCase):
    def metrics(self, records):
        materialized = engine.aggregate(records, COMPLETE)["operational_metrics"]
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "synthetic.jsonl"
            source.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
            streamed = engine.aggregate_path(source)["operational_metrics"]
        self.assertEqual(materialized, streamed)
        return materialized

    def test_replayed_delivery_is_not_a_second_load_or_candidate(self):
        first = load(candidate_event_id="candidate-1")
        records = [candidate(), candidate(), first, dict(first), load("load-2"), usage()]
        metrics = self.metrics(records)
        skill = metrics["skill_load"]
        self.assertEqual(skill["skill_load_count"], 2)
        self.assertEqual(skill["skill_load_candidate_count"], 1)
        self.assertEqual(skill["verified_candidate_count"], 1)
        self.assertEqual(skill["occurrence_matched_candidate_count"], 1)
        self.assertEqual(skill["duplicate_load_count"], 1)
        self.assertEqual(skill["duplicate_load_rate"], 0.5)
        self.assertEqual(skill["loaded_tokens"], 20)
        self.assertEqual(metrics["context"]["skill_input_token_share"], 0.2)

    def test_legacy_receipts_do_not_prove_zero_duplicates(self):
        old = load()
        old.pop("event_identity")
        old.pop("event_id")
        skill = self.metrics([old])["skill_load"]
        self.assertEqual(skill["skill_load_count"], 1)
        self.assertEqual(skill["unverified_occurrence_count"], 1)
        self.assertIsNone(skill["duplicate_load_count"])
        self.assertIsNone(skill["duplicate_load_rate"])
        old["event_id"] = "skill-load-bbbbbbbbbbbb-1"
        self.assertIsNone(self.metrics([old])["skill_load"]["duplicate_load_rate"])

    def test_conflicting_event_identity_fails_closed(self):
        metrics = self.metrics([load(), load(skill_tokens=11), usage()])
        self.assertEqual(metrics["skill_load"]["event_identity_conflict_count"], 1)
        self.assertIsNone(metrics["skill_load"]["duplicate_load_rate"])
        self.assertIsNone(metrics["context"]["skill_input_token_share"])

    def test_explicit_candidate_link_cannot_match_another_occurrence(self):
        skill = self.metrics([candidate(), load(candidate_event_id="absent")])["skill_load"]
        self.assertEqual(skill["verified_candidate_count"], 0)
        self.assertEqual(skill["receipt_coverage"], 0)
        legacy = load()
        legacy.pop("event_identity")
        skill = self.metrics([candidate(), legacy])["skill_load"]
        self.assertEqual(skill["verified_candidate_count"], 1)
        self.assertEqual(skill["occurrence_matched_candidate_count"], 0)

    def test_invalid_explicit_candidate_binding_never_falls_back(self):
        for binding in (123, " ", "", [], {}, None, True):
            with self.subTest(binding=binding):
                skill = self.metrics([candidate(), load(candidate_event_id=binding)])["skill_load"]
                self.assertEqual(skill["verified_candidate_count"], 0)
                self.assertEqual(skill["receipt_coverage"], 0)
                self.assertEqual(skill["occurrence_matched_candidate_count"], 0)
        self.assertEqual(self.metrics([candidate(), load()])["skill_load"]["verified_candidate_count"], 1)

    def test_input_measurement_failure_excluded_but_tool_failure_is_not(self):
        context = self.metrics([load(), usage(token_measurement_status="error",
                                            token_measurement_error_type="ValueError")])["context"]
        self.assertIsNone(context["skill_input_token_share"])
        self.assertIsNone(context["skill_input_token_share_denominator"])
        state = engine._TokenShareState()
        state.update(usage(token_measurement_status="error"))
        self.assertEqual(sum(state.tokens.values()), 0)
        self.assertEqual(state.invalid, 1)
        for changes in ({}, {"status": "error", "error_type": "transport"},
                        {"token_measurement_status": "ok", "status": "error"}):
            self.assertEqual(self.metrics([load(), usage(**changes)])["context"]["skill_input_token_share"], 0.1)

    def test_missing_retry_rationale_is_unverified_not_blind(self):
        base = dict(event_type="retry", root_task_id="synthetic-task",
                    error_category="transport", error_signature="timeout")
        records = [dict(base), dict(base, hypothesis_delta="fresh connection"),
                   dict(base, hypothesis_changed=False, retry_evidence="synthetic.jsonl:1-2"),
                   dict(base, hypothesis_changed=False, retry_evidence="synthetic.jsonl:3-4",
                        hypothesis_delta="changed timeout"),
                   dict(base, hypothesis_changed=False, retry_evidence=" ")]
        retry = self.metrics(records)["retry"]
        self.assertEqual(retry["blind_retry_count"], 1)
        self.assertEqual(retry["rationale_recorded_retry_count"], 1)
        self.assertEqual(retry["unverified_retry_count"], 3)
        self.assertEqual(retry["conflicting_retry_evidence_count"], 1)
        self.assertEqual(retry["blind_retry_rate"], 0.5)
        self.assertEqual(retry["retry_classification_coverage"], 0.4)
        self.assertIsNone(self.metrics([base])["retry"]["blind_retry_rate"])

    def test_authorization_distinguishes_intent_outcome_and_fingerprints(self):
        attempt = dict(event_type="write_attempt", root_task_id="synthetic-task", actor_id="root", call_id="call-1")
        commit = dict(attempt, event_type="write_commit", status="ok", authorization_id="auth-1",
                      write_scope_sha256="c" * 64, authorization_scope_sha256="c" * 64)
        cases = [
            ([usage()], "no_write_intent_observed", 0),
            ([dict(attempt, side_effect_state="not_started")], "attempts_without_confirmed_commit", 0),
            ([attempt], "outcome_uncertain", 0),
            ([dict(attempt, side_effect_state="unknown")], "outcome_uncertain", 0),
            ([attempt, commit], "confirmed_commits_matched", 1),
            ([dict(commit, authorization_conflict=True)], "confirmed_commits_unmatched", 1),
            ([dict(commit, authorization_scope_sha256="d" * 64)], "confirmed_commits_unmatched", 1),
            ([dict(commit, status="error")], "outcome_uncertain", 0),
            ([dict(commit, side_effect_state="unknown")], "outcome_uncertain", 0),
            ([dict(commit, authorization_id="approved by user", write_scope_sha256="same", authorization_scope_sha256="same")], "confirmed_commits_unmatched", 1),
        ]
        for records, status, commits in cases:
            with self.subTest(status=status, records=records):
                auth = self.metrics(records)["authorization"]
                self.assertEqual(auth["authorization_evidence_status"], status)
                self.assertEqual(auth["write_commit_count"], commits)
        report = engine.aggregate([commit], {"status": "partial", "issues": [{"category": "missing"}]})
        self.assertEqual(report["operational_metrics"]["authorization"]["authorization_evidence_status"], "outcome_uncertain")

    def test_token_share_requires_compatible_complete_scope(self):
        self.assertEqual(self.metrics([load(), usage()])["context"]["skill_input_token_share"], 0.1)
        cases = [
            [load(token_measurement_basis="skill_text"), usage()],
            [load(), usage(tokenizer="different")],
            [load(), usage(token_scope_id="another-request")],
            [load(), usage(skill_tokens_included=False)],
            [load(), usage(skill_load_coverage_complete=False)],
            [load(), usage(), usage()],
            [load(skill_tokens=101), usage()],
            [load(), usage(input_tokens=0)],
            [load(), usage(token_measurement_basis=None)],
            [load(), usage(), load("load-2", token_scope_id="request-2", tokenizer="other"),
             usage(token_scope_id="request-2", tokenizer="other")],
        ]
        for records in cases:
            with self.subTest(records=records):
                context = self.metrics(records)["context"]
                self.assertIsNone(context["skill_input_token_share"])
                self.assertTrue(context["skill_input_token_share_reason"])
        records = [load(), usage()]
        records[0].pop("event_identity")
        self.assertIsNone(self.metrics(records)["context"]["skill_input_token_share"])

    def test_token_share_replays_and_missing_measurements(self):
        measured = usage(event_id="usage-1", event_identity="occurrence")
        context = self.metrics([load(), measured, dict(measured)])["context"]
        self.assertEqual(context["input_measurement_observation_count"], 1)
        self.assertEqual(context["skill_input_token_share_numerator"], 10)
        self.assertEqual(context["skill_input_token_share_denominator"], 100)
        self.assertEqual(context["skill_input_token_share"], 0.1)
        missing = usage(token_scope_id="request-2")
        missing.pop("input_tokens")
        for extra in (missing, dict(measured, input_tokens=101)):
            self.assertIsNone(self.metrics([load(), measured, extra])["context"]["skill_input_token_share"])
        for value in (True, -1, "100", float("nan"), float("inf")):
            self.assertIsNone(self.metrics([load(), usage(input_tokens=value)])["context"]["skill_input_token_share"])
        alias = usage(prompt_tokens=101)
        self.assertIsNone(self.metrics([load(), alias])["context"]["skill_input_token_share"])
        alias.pop("input_tokens")
        self.assertEqual(self.metrics([load(), alias])["context"]["skill_input_token_share"], 0.099)

    def test_conflicting_load_status_or_measurement_cannot_prove_occurrence(self):
        for record in (load(status="error"), load(token_measurement_status="error")):
            skill = self.metrics([record])["skill_load"]
            self.assertEqual(skill["skill_load_count"], 0)
            self.assertEqual(skill["unverifiable_load_count"], 1)
            self.assertIsNone(skill["duplicate_load_rate"])
        metrics = self.metrics([load(), load(status="error")])
        self.assertEqual(metrics["skill_load"]["event_identity_conflict_count"], 1)
        self.assertIsNone(metrics["skill_load"]["receipt_coverage"])

    def test_unknown_authorization_metadata_and_unrelated_commits_never_green(self):
        commit = {"event_type": "write_commit", "root_task_id": "synthetic-task", "actor_id": "root",
                  "call_id": "call-1", "authorization_id": "auth-1", "write_scope_sha256": "c" * 64,
                  "authorization_scope_sha256": "c" * 64}
        for changes in ({"outcome": "unknown"}, {"status": None}, {"side_effect_state": "rolled_back"}):
            auth = self.metrics([dict(commit, **changes)])["authorization"]
            self.assertEqual(auth["write_commit_count"], 0)
            self.assertEqual(auth["authorization_evidence_status"], "outcome_uncertain")
        for changes in ({"authorization_conflict": "false"}, {"authorization_id": "approved by user"}):
            auth = self.metrics([dict(commit, **changes)])["authorization"]
            self.assertEqual(auth["unmatched_write_count"], 1)
        unrelated = dict(commit, event_type="write_attempt", call_id="other-call")
        auth = self.metrics([unrelated, commit])["authorization"]
        self.assertEqual(auth["write_commit_count"], 1)
        self.assertEqual(auth["uncertain_write_outcome_count"], 1)
        self.assertEqual(auth["authorization_evidence_status"], "outcome_uncertain")
        self.assertEqual(engine.aggregate([commit])["operational_metrics"]["authorization"]["authorization_evidence_status"], "outcome_uncertain")

    def test_sequence_coverage_gaps_have_list_stream_parity(self):
        commit = {"event_type": "write_commit", "root_task_id": "synthetic-task", "actor_id": "root",
                  "authorization_id": "auth-1", "write_scope_sha256": "c" * 64,
                  "authorization_scope_sha256": "c" * 64}
        missing_timestamp = {"event_type": "wait", "root_task_id": "synthetic-task", "state_version": "1"}
        metrics = self.metrics([load(), usage(), commit, missing_timestamp])
        self.assertEqual(metrics["authorization"]["authorization_evidence_status"], "outcome_uncertain")
        self.assertIsNone(metrics["context"]["skill_input_token_share"])
        self.assertEqual(COMPLETE, {"status": "complete", "issues": []})

    def test_conflicting_occurrences_retract_both_versions(self):
        for records in ([load(), load(skill_tokens=11)],
                        [load(skill_tokens=11), load()],
                        [load(), load("load-2"), load(skill_tokens=11), load()]):
            with self.subTest(records=records):
                skill = self.metrics(records)["skill_load"]
                valid = int(any(r["event_id"] == "load-2" for r in records))
                self.assertEqual(skill["skill_load_count"], valid)
                self.assertEqual(skill["occurrence_load_count"], valid)
                self.assertEqual(skill["observed_duplicate_load_count"], 0)
                self.assertEqual(skill["loaded_tokens_by_tokenizer"], {"test-native": 10} if valid else {})
                self.assertEqual(skill["unverifiable_load_count"], 1)
        # Missing status is not semantically equivalent to an explicit unknown status.
        self.assertEqual(self.metrics([load(), load(status=None)])["skill_load"]["skill_load_count"], 0)
        self.assertEqual(self.metrics([load(skill_tokens=0)])["skill_load"]["loaded_tokens_by_tokenizer"],
                         {"test-native": 0})

    def test_strict_semantic_coverage_and_validator_parity(self):
        measured = usage(event_id="usage-1", event_identity="occurrence")
        retry = dict(event_type="retry", root_task_id="synthetic-task", error_category="transport",
                     error_signature="timeout", hypothesis_changed=False, retry_evidence="synthetic:1")
        wait = dict(event_type="wait", root_task_id="synthetic-task", state_version="1")
        legacy = load()
        legacy.pop("event_identity")
        cases = [
            ("skill-conflict", [load(), load(skill_sha256="c" * 64)], "event_identity_conflict"),
            ("candidate-conflict", [candidate(), candidate(context_epoch="2")], "event_identity_conflict"),
            ("input-conflict", [load(), measured, dict(measured, input_tokens=101)], "event_identity_conflict"),
            ("retry-conflict", [dict(retry, changed_variable="timeout")], "conflicting_retry_evidence"),
            ("retry-alias-conflict", [dict(retry, error_type="schema")], "conflicting_retry_evidence"),
            ("retry-conflict-with-malformed-pointer", [dict(retry, changed_variable="timeout", retry_evidence=[])],
             "conflicting_retry_evidence"),
            ("wait-missing", [load(), usage(), wait], "missing_sequence_timestamp"),
            ("wait-regressing", [dict(wait, timestamp="2026-09-06T01:00:02Z"),
                                  dict(wait, timestamp="2026-09-06T01:00:01Z")], "out_of_order_sequence"),
            ("exact-replays", [load(), load(), measured, dict(measured)], None),
            ("legacy-unknown", [legacy, dict(event_type="retry", root_task_id="synthetic-task"),
                                dict(event_type="write_attempt", root_task_id="synthetic-task"),
                                usage(tokenizer="incompatible")], None),
            ("natural-language-not-inferred", [dict(retry, hypothesis_changed=True,
                                                    hypothesis_delta="nothing changed")], None),
        ]
        cases.extend((f"invalid-binding-{index}", [candidate(), load(candidate_event_id=binding)],
                      "invalid_candidate_binding")
                     for index, binding in enumerate((123, " ", "", [], {}, None, True)))
        ok = dict(measured, token_measurement_status="ok")
        error = dict(measured, token_measurement_status="error", token_measurement_error_type="ValueError")
        cases.extend([
            ("input-status-conflict", [load(), ok, error], "event_identity_conflict"),
            ("input-status-conflict-reversed", [load(), error, ok], "event_identity_conflict"),
            ("input-error-type-conflict", [load(), error, dict(error, token_measurement_error_type="TypeError")],
             "event_identity_conflict"),
            ("input-measurement-error", [load(), error], None),
            ("ordinary-tool-error", [load(), dict(ok, status="error", error_type="transport")], None),
            ("absent-binding", [candidate(), load(), usage()], None),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            for name, records, category in cases:
                with self.subTest(name=name):
                    source = Path(tmp) / (name + ".jsonl")
                    target = Path(tmp) / (name + ".json")
                    source.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
                    proc = subprocess.run([sys.executable, "-B", str(ROOT / "generate_final_report.py"),
                                           "--input", str(source), "--output", str(target), "--strict"],
                                          capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 2 if category else 0, proc.stdout + proc.stderr)
                    streamed = json.loads(target.read_text(encoding="utf-8"))
                    listed = engine.aggregate(records, COMPLETE)
                    self.assertEqual(listed["operational_metrics"], streamed["operational_metrics"])
                    self.assertEqual(listed["coverage"]["status"], streamed["coverage"]["status"])
                    self.assertEqual({i["category"] for i in listed["coverage"]["issues"]},
                                     {i["category"] for i in streamed["coverage"]["issues"]})
                    if category:
                        self.assertIn(category, {i["category"] for i in streamed["coverage"]["issues"]})
                        self.assertEqual(listed["operational_metrics"]["authorization"]["authorization_evidence_status"],
                                         "outcome_uncertain")
                        self.assertIsNone(listed["operational_metrics"]["context"]["skill_input_token_share"])
                    validated = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/validate_agent_audit.py"), str(target)],
                                               capture_output=True, text=True)
                    self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
        self.assertEqual(COMPLETE, {"status": "complete", "issues": []})

    def test_actual_receipt_and_report_cli_end_to_end(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "SKILL.md"
            skill.write_text("---\nname: sample\n---\nSynthetic test content.\n", encoding="utf-8")
            receipts = root / "receipts.jsonl"
            command = [sys.executable, "-B", str(ROOT / "scripts/skill_load_receipt.py"),
                       "--skill-path", str(skill), "--root-task-id", "synthetic-task",
                       "--actor-id", "root", "--context-epoch", "1", "--output", str(receipts)]
            for event_id in ("load-1", "load-1", "load-2"):
                proc = subprocess.run(command + ["--event-id", event_id], capture_output=True, text=True, env=env)
                self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(len(receipts.read_text(encoding="utf-8").splitlines()), 2)
            with receipts.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(usage()) + "\n")
                handle.write(json.dumps(dict(event_type="retry", root_task_id="synthetic-task")) + "\n")
                handle.write(json.dumps(dict(event_type="write_attempt", root_task_id="synthetic-task")) + "\n")
            output = root / "report.json"
            proc = subprocess.run([sys.executable, "-B", str(ROOT / "generate_final_report.py"),
                                   "--input", str(receipts), "--output", str(output), "--strict"],
                                  capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            metrics = report["operational_metrics"]
            self.assertEqual(metrics["skill_load"]["duplicate_load_rate"], 0.5)
            self.assertEqual(metrics["retry"]["unverified_retry_count"], 1)
            self.assertEqual(metrics["authorization"]["authorization_evidence_status"], "outcome_uncertain")
            self.assertIsNone(metrics["context"]["skill_input_token_share"])
            proc = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/validate_agent_audit.py"), str(output)],
                                  capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
