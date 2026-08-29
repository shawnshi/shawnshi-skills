from __future__ import annotations

import copy
import hashlib
import json
import unittest

from tests.common import CONFIG, research_plan as rp


class ResearchPlanProductionContractTests(unittest.TestCase):
    def test_production_plan_cli_has_no_config_override_or_unsigned_query_inputs(self):
        parser = rp.build_parser()
        plan = next(
            action
            for action in parser._actions
            if getattr(action, "choices", None)
        ).choices["plan"]
        option_strings = {
            option
            for action in plan._actions
            for option in action.option_strings
        }
        self.assertNotIn("--config", option_strings)
        self.assertNotIn("--alias", option_strings)
        self.assertNotIn("--topic", option_strings)
        self.assertNotIn("--project", option_strings)
        self.assertNotIn("--query", option_strings)

    def test_production_config_is_pinned_to_reviewed_package_bytes(self):
        expected = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
        self.assertEqual(rp.TRUSTED_BUSINESS_CONFIG_SHA256, expected)
        loaded = rp.load_trusted_production_config()
        self.assertEqual(set(loaded["profiles"]), set(rp.BUSINESS_MODES))

    def test_unknown_contract_fields_and_unbounded_budget_fail_closed(self):
        original = json.loads(CONFIG.read_text(encoding="utf-8"))
        cases = []
        unknown_root = copy.deepcopy(original)
        unknown_root["self_asserted_trust"] = True
        cases.append(unknown_root)
        unknown_profile = copy.deepcopy(original)
        unknown_profile["profiles"]["briefing"]["bypass"] = True
        cases.append(unknown_profile)
        huge_budget = copy.deepcopy(original)
        huge_budget["profiles"]["briefing"]["query_budget"]["public_max"] = 10**9
        cases.append(huge_budget)
        unknown_gate = copy.deepcopy(original)
        unknown_gate["profiles"]["briefing"]["planning_gate"]["required"].append(
            "self_asserted_ready"
        )
        cases.append(unknown_gate)
        for index, value in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(rp.PlanError):
                rp.validate_config(value)


if __name__ == "__main__":
    unittest.main()
