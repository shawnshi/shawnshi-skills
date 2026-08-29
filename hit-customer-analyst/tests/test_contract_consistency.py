from __future__ import annotations

import unittest
from pathlib import Path

from tests.common import SKILL_ROOT, SCRIPTS, load_module


VALIDATOR = load_module("institution_review_contract_validator", SCRIPTS / "validate_outputs.py")


class ContractConsistencyTests(unittest.TestCase):
    def test_institution_review_contract_matches_runtime_validator(self):
        institution = (
            SKILL_ROOT / "references" / "subskill-institution-research.md"
        ).read_text(encoding="utf-8")
        self.assertIn("completed", institution)
        self.assertIn("review_status: pending", institution)
        self.assertIn("not_started → pending → approved", institution)
        self.assertNotIn("始终保持`review_status: not_required`", institution)

    def test_all_selected_research_carriers_are_listed_in_runtime_review_gate(self):
        runtime = (SKILL_ROOT / "references" / "workbuddy-runtime.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "institution/leader/internal/visit_strategy",
            runtime,
        )

    def test_completed_institution_cannot_bypass_review_as_not_required(self):
        metadata = {
            "schema": VALIDATOR.SCHEMA,
            "artifact_type": "institution_research",
            "context_id": "dcx-20260827-Abcd1234",
            "latest_run_id": "dcr-20260827T040000-Ab12",
            "customer_id": "cust-example",
            "customer_display_name": "示例医院",
            "organization_scope": "示例医院",
            "safe_name": "示例医院",
            "module_status": "completed",
            "review_status": "not_required",
            "connector_status": "not_applicable",
            "freshness_status": "current",
            "content_version": "1",
            "evidence_cutoff_date": "2026-08-27",
            "updated_at": "2026-08-27T04:00:00Z",
            "runtime_owner": "测试负责人",
            **{field: "" for field in VALIDATOR.GENERIC_REVIEW_FIELDS},
        }
        document = VALIDATOR.Document(
            Path("/tmp/示例医院机构研究报告.md"),
            "",
            metadata,
            "# 示例医院机构研究报告\n",
        )
        issues = []
        VALIDATOR.validate_frontmatter(document, issues, strict=False)
        self.assertIn("review_submission_missing", {issue.code for issue in issues})


if __name__ == "__main__":
    unittest.main()
