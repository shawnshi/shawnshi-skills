import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]

class WorkflowTemplateTests(unittest.TestCase):
    def workflow(self, name):
        return yaml.load((ROOT / "assets" / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    def test_manual_only_triggers(self):
        for name in ["fleet-dispatch.yml", "fleet-merge.yml"]:
            self.assertEqual(set(self.workflow(name)["on"]), {"workflow_dispatch"})

    def test_merge_approval_and_dry_run_defaults(self):
        inputs = self.workflow("fleet-merge.yml")["on"]["workflow_dispatch"]["inputs"]
        for name in ["base_branch", "pr_number", "head_sha", "task_id", "fleet_date", "approved"]:
            self.assertEqual(inputs[name]["required"], "true")
        self.assertEqual(inputs["approved"]["default"], "false")
        self.assertEqual(inputs["dry_run"]["default"], "true")

    def test_trusted_checkout_and_one_shared_entry_no_shell_interpolation(self):
        workflow = self.workflow("fleet-merge.yml")
        steps = workflow["jobs"]["approved-merge"]["steps"]
        self.assertEqual(steps[0]["with"]["ref"], "${{ github.event.repository.default_branch }}")
        self.assertEqual(steps[0]["with"]["persist-credentials"], "false")
        runs = [s for s in steps if "run" in s]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["run"], "bun scripts/fleet/fleet-merge.ts")
        for name in ["BASE_BRANCH", "PR_NUMBER", "HEAD_SHA", "TASK_ID", "DATE", "APPROVED", "DRY_RUN", "REPO"]:
            self.assertIn("FLEET_" + name, runs[0]["env"])
        self.assertNotIn("permissions", workflow)
        text = (ROOT / "assets/fleet-merge.yml").read_text(encoding="utf-8")
        for removed in ["TASK_PROMPT", "createSession", "gh pr close", "gh pr list", "bun install", "JULES_API_KEY"]:
            self.assertNotIn(removed, text)

if __name__ == "__main__":
    unittest.main()
