from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests.common import SKILL_ROOT


MAP_PATH = Path(__file__).with_name("negative_case_map.json")
REFERENCE_PATH = SKILL_ROOT / "references" / "validation-cases.md"
CASE_IDS = [f"N{number:02d}" for number in range(1, 67)]
SURFACES = {
    "validator": ("scripts/validate_outputs.py",),
    "initializer": ("scripts/init_workspace.py",),
    "initializer_state": ("scripts/init_workspace.py", "scripts/runtime_tx.py"),
    "transaction": ("scripts/runtime_tx.py", "scripts/commit_run.py"),
    "lifecycle": ("scripts/validate_outputs.py",),
    "lifecycle_transaction": ("scripts/validate_outputs.py", "scripts/runtime_tx.py"),
    "refresh": ("scripts/init_workspace.py", "scripts/validate_outputs.py"),
    "preflight": (
        "scripts/preflight_intake.py",
        "scripts/init_workspace.py",
        "scripts/research_plan.py",
    ),
    "governance": ("scripts/governance.py",),
    "governance_lifecycle": (
        "scripts/governance.py",
        "scripts/validate_outputs.py",
    ),
    "candidate_transaction": (
        "scripts/build_candidate.py",
        "scripts/research_plan.py",
        "scripts/commit_run.py",
    ),
    "planning": ("scripts/preflight_intake.py", "scripts/research_plan.py"),
    "capability": ("scripts/capability_receipt.py", "scripts/research_plan.py"),
    "evidence_validator": ("scripts/validate_outputs.py",),
    "evidence_cache": ("scripts/research_plan.py", "scripts/validate_outputs.py"),
}


def load_reference_contracts() -> dict[str, dict[str, object]]:
    contracts: dict[str, dict[str, object]] = {}
    pattern = re.compile(r"^\|\s*(N\d{2})\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$")
    for line in REFERENCE_PATH.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match or match.group(1) not in CASE_IDS:
            continue
        case_id, mutation, expected = match.groups()
        contracts[case_id] = {
            "mutation": mutation,
            "expected": expected,
            "error_tokens": re.findall(r"`([^`]+)`", expected),
        }
    return contracts


class NegativeCaseMapCompletenessTests(unittest.TestCase):
    def test_N01_N66_contract_mapping(self):
        """Every published negative case resolves to one unique behavior test."""
        payload = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        contracts = load_reference_contracts()
        cases = {case["case_id"]: case for case in payload["cases"]}
        self.assertEqual(payload["schema"], "discovery-call-negative-case-map/v1")
        self.assertEqual(payload["source"], "references/validation-cases.md")
        self.assertEqual(
            payload["contract_test_id"],
            "tests.test_negative_case_map.NegativeCaseMapCompletenessTests.test_N01_N66_contract_mapping",
        )
        self.assertEqual(sorted(contracts), CASE_IDS)
        self.assertEqual(sorted(cases), CASE_IDS)
        self.assertEqual(len(payload["cases"]), 66)
        test_ids = [case["test_id"] for case in payload["cases"]]
        self.assertEqual(len(set(test_ids)), 66, "每个负例必须有独立的行为测试路径")
        self.assertNotIn(payload["contract_test_id"], test_ids)

        for case_id in CASE_IDS:
            with self.subTest(case_id=case_id):
                case = cases[case_id]
                contract = contracts[case_id]
                self.assertIn(case["surface"], SURFACES)
                self.assertEqual(case["coverage"], "behavior")
                self.assertTrue(case["test_id"].startswith("tests."))
                self.assertTrue(str(contract["mutation"]).strip())
                self.assertTrue(str(contract["expected"]).strip())
                self.assertTrue(
                    contract["error_tokens"]
                    or re.search(r"退出[23]", str(contract["expected"]))
                    or "前后值断言" in str(contract["expected"]),
                    f"{case_id}缺少机器可判定的错误码、退出码或状态断言",
                )
                for relative in SURFACES[case["surface"]]:
                    self.assertTrue((SKILL_ROOT / relative).is_file(), relative)
                suite = unittest.defaultTestLoader.loadTestsFromName(case["test_id"])
                self.assertEqual(suite.countTestCases(), 1, case["test_id"])


if __name__ == "__main__":
    unittest.main()
