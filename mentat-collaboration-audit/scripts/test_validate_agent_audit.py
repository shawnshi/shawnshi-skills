import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))
from validate_agent_audit import validate_agent_payload, validate_report_payload


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
