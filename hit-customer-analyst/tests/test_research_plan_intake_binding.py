from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.common import research_plan as rp, write_intake


class _FakeRuntimeWorkspace:
    last_plan: dict | None = None
    last_project_id: str | None = None

    def __init__(self, workspace: Path | str, *, source_workspace: Path | str):
        self.workspace = Path(workspace)
        self.source_workspace = Path(source_workspace)

    def materialize(self, plan, *, project_id=None, generated_at=None):
        type(self).last_plan = dict(plan)
        type(self).last_project_id = project_id
        runtime = self.workspace / "runtime"
        return {
            "search_plan": runtime / "search-plan.json",
            "source_cache": runtime / "source-cache.json",
            "evidence_manifest": runtime / "evidence-manifest.json",
            "run_metrics": runtime / "run-metrics.json",
        }


def _append_field(path: Path, field: str, value: str) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["candidate_sets"].append(
        {
            "field": field,
            "candidates": [
                {
                    "candidate_id": f"{field}-1",
                    "value": value,
                    "status": "asserted",
                    "source_ref": "test:user-turn:1",
                }
            ],
        }
    )
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class ResearchPlanIntakeBindingTests(unittest.TestCase):
    def _arguments(self, root: Path, intake: Path) -> list[str]:
        return [
            "research_plan.py",
            "plan",
            "--workspace",
            str(root / "candidate"),
            "--source-workspace",
            str(root / "source"),
            "--business-mode",
            "briefing",
            "--context-id",
            "dcx-20260827-Abcd1234",
            "--run-id",
            "dcr-20260827T040000-Ab12",
            "--customer-name",
            "示例医院",
            "--customer-id",
            "customer.demo",
            "--organization-scope",
            "示例医院",
            "--intake-input",
            str(intake),
        ]

    def _run_main(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(sys, "argv", arguments),
            mock.patch.object(rp, "RuntimeWorkspace", _FakeRuntimeWorkspace),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            return rp.main(), stdout.getvalue(), stderr.getvalue()

    def test_project_id_is_inherited_from_the_same_ready_intake(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake = write_intake(root, "示例医院", "briefing")
            _append_field(intake, "project_id", "project.demo")

            code, stdout, stderr = self._run_main(self._arguments(root, intake))

            self.assertEqual(code, 0, stderr)
            self.assertNotIn("NameError", stderr)
            self.assertEqual(_FakeRuntimeWorkspace.last_project_id, "project.demo")
            self.assertEqual(
                _FakeRuntimeWorkspace.last_plan["authorization_context"]["project_id"],
                "project.demo",
            )
            self.assertIn('"planning_ready": true', stdout)

    def test_project_id_conflict_is_rejected_before_workspace_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake = write_intake(root, "示例医院", "briefing")
            _append_field(intake, "project_id", "project.intake")
            arguments = self._arguments(root, intake) + ["--project-id", "project.cli"]

            code, _stdout, stderr = self._run_main(arguments)

            self.assertEqual(code, 2)
            self.assertIn("--project-id与intake预检确认的项目范围不一致", stderr)
            self.assertNotIn("NameError", stderr)

    def test_person_without_confirmed_target_person_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake = write_intake(root, "示例医院", "briefing")
            arguments = self._arguments(root, intake) + ["--person", "张三"]

            code, _stdout, stderr = self._run_main(arguments)

            self.assertEqual(code, 2)
            self.assertIn("--person必须先由intake预检确认target_person", stderr)


if __name__ == "__main__":
    unittest.main()
