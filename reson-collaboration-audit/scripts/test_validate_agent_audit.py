import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))
from validate_agent_audit import validate_agent_payload, validate_report_payload

sys.path.insert(0, str(Path(__file__).parent / "core"))
import engine


class CollaborationAuditValidatorTests(unittest.TestCase):
    def test_literal_template_syntax_in_evidence_is_not_a_placeholder(self):
        payload = {
            "schema_version": 2,
            "coverage": {"status": "complete", "issues": []},
            "record_count": 1,
            "components": [],
            "failure_types": {},
            "operational_metrics": {
                name: {}
                for name in (
                    "wait",
                    "skill_load",
                    "retry",
                    "subagent",
                    "authorization",
                    "context",
                )
            },
            "limitations": ["Source log documents literal {{task_id}} and <TBD> syntax."],
        }

        self.assertEqual(validate_report_payload(payload), [])

    def test_corrected_semantics_reject_legacy_green_status(self):
        report = engine.aggregate(
            [{"event_type": "write_attempt", "root_task_id": "synthetic"}],
            {"status": "complete", "issues": []},
        )
        self.assertEqual(validate_report_payload(report), [])
        report["operational_metrics"]["authorization"]["authorization_evidence_status"] = "no_writes"
        self.assertTrue(any("authorization_evidence_status" in error for error in validate_report_payload(report)))

    def test_corrected_semantics_reject_missing_rationale_as_blind(self):
        report = engine.aggregate([{"event_type": "retry", "root_task_id": "synthetic"}])
        retry = report["operational_metrics"]["retry"]
        retry["blind_retry_count"] = 1
        retry["blind_retry_rate"] = 1.0
        self.assertTrue(any("retry" in error for error in validate_report_payload(report)))

    def test_corrected_semantics_reject_unjustified_numeric_token_share(self):
        report = engine.aggregate([{"event_type": "usage", "root_task_id": "synthetic", "input_tokens": 100}])
        report["operational_metrics"]["context"]["skill_input_token_share"] = 0.2
        self.assertTrue(any("skill_input_token" in error for error in validate_report_payload(report)))

    def test_corrected_semantics_require_conflict_coverage(self):
        records = [{"event_type": "retry", "root_task_id": "synthetic", "hypothesis_changed": False,
                    "changed_variable": "timeout"}]
        report = engine.aggregate(records, {"status": "complete", "issues": []})
        self.assertEqual(validate_report_payload(report), [])
        report["coverage"] = {"status": "complete", "issues": []}
        self.assertIn("coverage must disclose conflicting_retry_evidence", validate_report_payload(report))
        report["operational_metrics"]["skill_load"]["event_identity_conflict_count"] = 1
        self.assertIn("coverage must disclose event_identity_conflict", validate_report_payload(report))

    def test_numeric_token_share_rejects_cross_section_skill_evidence_gaps(self):
        from test_phase1_semantics import load, usage

        legacy = load()
        legacy.pop("event_identity")
        cases = ([legacy, usage()], [load(status="error"), usage()],
                 [load(), load(skill_tokens=11), usage()], [usage()])
        for records in cases:
            with self.subTest(records=records):
                report = engine.aggregate(records, {"status": "complete", "issues": []})
                self.assertEqual(validate_report_payload(report), [])
                report["operational_metrics"]["context"].update(
                    skill_input_token_share=0.1, skill_input_token_share_reason="compatible",
                    skill_input_token_share_numerator=10, skill_input_token_share_denominator=100,
                    skill_input_token_share_coverage=1, compatible_scope_count=1)
                self.assertTrue(any("skill_input_token_share" in error
                                    for error in validate_report_payload(report)))

    def test_numeric_token_share_requires_eligible_observations_and_bounded_operands(self):
        from test_phase1_semantics import load, usage

        # Rounded division alone can hide a numerator exceeding the denominator.
        report = engine.aggregate([load(), usage()], {"status": "complete", "issues": []})
        report["operational_metrics"]["context"].update(
            skill_input_token_share=1.0, skill_input_token_share_numerator=100001,
            skill_input_token_share_denominator=100000)
        self.assertTrue(any("skill_input_token_share" in error for error in validate_report_payload(report)))
        for field in ("input_measurement_observation_count", "compatible_scope_count"):
            report = engine.aggregate([load(), usage()], {"status": "complete", "issues": []})
            report["operational_metrics"]["context"][field] = 0
            self.assertTrue(validate_report_payload(report))

    def test_numeric_token_share_does_not_require_unrelated_evidence(self):
        from test_phase1_semantics import load, usage

        records = [load(), usage(), {"event_type": "retry", "root_task_id": "synthetic"},
                   {"event_type": "write_attempt", "root_task_id": "synthetic"}]
        report = engine.aggregate(records, {"status": "complete", "issues": []})
        self.assertEqual(report["operational_metrics"]["context"]["skill_input_token_share"], 0.1)
        self.assertEqual(validate_report_payload(report), [])

    def test_explicit_unresolved_value_in_required_field_is_rejected(self):
        payload = {
            "version": "1",
            "behavioral_analysis": {
                "points": [{"description": "PENDING_DESCRIPTION"}]
            },
            "friction_analysis": {"categories": []},
            "workflow_engineering": {},
            "suggestions": {},
            "at_a_glance": {},
            "distributions": {},
        }

        errors = validate_agent_payload(payload)

        self.assertIn(
            "behavioral_analysis.points[0].description is unresolved",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
