from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.common import SCRIPTS, load_module, run_python
from tests.common import runtime_tx as tx
from tests.fixture_builder import (
    _rebuild_manifest,
    _replace_frontmatter,
    build_pending_letter_workspace,
    build_pending_strategy_workspace,
)

validator = load_module("stage2_validator", SCRIPTS / "validate_outputs.py")
initializer = load_module("stage2_initializer", SCRIPTS / "init_workspace.py")


def update_metadata(path: Path, **updates: str) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(_replace_frontmatter(text, updates) + text.split("---", 2)[2], encoding="utf-8")


def workspace_bytes(workspace: Path) -> dict[str, bytes]:
    return {p.relative_to(workspace).as_posix(): p.read_bytes() for p in workspace.rglob("*")
            if p.is_file() and p.suffix in {".md", ".json"}}


class Stage2BusinessFlowTests(unittest.TestCase):
    def govern(self, workspace: Path, *args: str) -> dict:
        result = run_python("validate_outputs.py", [str(workspace), *args, "--json"])
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def approve_and_ready(self, workspace: Path) -> None:
        for module in ("leader", "strategy"):
            self.govern(workspace, "--approve-artifact", module, "--reviewer", "合成审核员甲（测试岗）")
        self.govern(workspace, "--mark-ready", "--reviewer", "合成审核员乙（测试岗）")
        self.govern(workspace, "--strict")

    def resume_args(self, workspace: Path, *extra: str, refresh: bool = True):
        args = ["示例医院", "--output-root", str(workspace.parent), "--resume"]
        if refresh:
            args += ["--refresh-modules", "institution,leader"]
        return initializer.build_parser().parse_args([*args, *extra])

    def test_B01_standard_and_strategic_role_only_real_approval_chain(self):
        for mode in ("standard_visit", "strategic_account"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_strategy_workspace(Path(temporary), business_mode=mode,
                                                            role_only=True, official_template=True)
                leader = next(workspace.glob("*人物研究报告.md"))
                self.assertIn("不含具名主张", leader.read_text(encoding="utf-8"))
                self.assertNotIn("张主任", leader.read_text(encoding="utf-8"))
                self.govern(workspace)
                self.approve_and_ready(workspace)
                manifest = json.loads((workspace / tx.MANIFEST_REL).read_text(encoding="utf-8"))
                self.assertTrue(manifest["ready_for_use"])
                self.assertIn("leader", manifest["selected_modules"])

    def test_B01_partial_and_named_conflict_cannot_be_approved(self):
        for status in ("partial", "conflicted"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_strategy_workspace(Path(temporary))
                leader = next(workspace.glob("*人物研究报告.md"))
                if status == "partial":
                    update_metadata(leader, module_status="partial")
                else:
                    leader.write_text(leader.read_text(encoding="utf-8").replace("verified_single", "conflicted"), encoding="utf-8")
                _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
                before = workspace_bytes(workspace)
                result = run_python("validate_outputs.py", [str(workspace), "--approve-artifact", "leader",
                                                            "--reviewer", "合成审核员甲（测试岗）", "--json"])
                self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
                codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
                self.assertIn("output_uses_incomplete_research" if status == "partial" else "leader_completed_conflict", codes)
                self.assertEqual(workspace_bytes(workspace), before)

    def test_U01_official_template_missing_materials_section_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(Path(temporary), official_template=True)
            strategy = next(workspace.glob("*交流策略与议题设计.md"))
            text = strategy.read_text(encoding="utf-8")
            self.assertIn("## 6. 材料与演示计划", text)
            start, end = text.index("## 6. 材料与演示计划"), text.index("## 7. 问题清单")
            strategy.write_text(text[:start] + text[end:], encoding="utf-8")
            _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
            for module in ("leader", "strategy"):
                self.govern(workspace, "--approve-artifact", module, "--reviewer", "合成审核员甲（测试岗）")
            before = workspace_bytes(workspace)
            result = run_python("validate_outputs.py", [str(workspace), "--mark-ready", "--reviewer", "合成审核员乙（测试岗）", "--json"])
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("presales_loop_incomplete", result.stdout)
            self.assertEqual(workspace_bytes(workspace), before)

    def test_U02_pending_normal_passes_strict_and_external_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_letter_workspace(Path(temporary))
            self.govern(workspace)
            before = workspace_bytes(workspace)
            strict = run_python("validate_outputs.py", [str(workspace), "--strict", "--json"])
            self.assertEqual(strict.returncode, 1)
            self.assertIn("ready_for_use_required", strict.stdout)
            external = run_python("validate_outputs.py", [str(workspace), "--emit-external", "--json"])
            self.assertEqual(external.returncode, 1)
            self.assertEqual(workspace_bytes(workspace), before)

    def test_B04_natural_expiry_normal_refresh_preserves_evidence_and_blocks_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(Path(temporary), role_only=True)
            self.approve_and_ready(workspace)
            total = next(workspace.glob("*客户研究与拜访准备报告.md"))
            update_metadata(total, workflow_stage="closed")
            _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
            self.govern(workspace, "--strict")
            before = {p.name: tx.parse_frontmatter(p.read_text(encoding="utf-8"))["evidence_cutoff_date"]
                      for p in workspace.glob("*.md")}
            research_bytes = {p: p.read_bytes() for p in workspace.glob("*.md") if p != total}
            future = datetime.now(timezone.utc) + timedelta(days=100)

            class FutureClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return future.astimezone(tz) if tz else future.replace(tzinfo=None)

            # Execute the real validator CLI entrypoint with a frozen clock; no result mocks.
            def clocked_cli(command, **kwargs):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), patch.object(sys, "argv", command[1:]):
                    code = validator.main()
                return subprocess.CompletedProcess(command, code, output.getvalue(), "")

            with patch.object(validator, "datetime", FutureClock), patch.object(initializer.subprocess, "run", side_effect=clocked_cli):
                with self.assertRaisesRegex(initializer.InitError, "freshness_ttl_exceeded"):
                    initializer.initialize(self.resume_args(workspace, refresh=False))
                result = initializer.initialize(self.resume_args(workspace))
                self.assertEqual(result["recovery"], "not_requested")
                issues, *_ = validator.validate(workspace, strict=True, emit=False)
                self.assertIn("freshness_ttl_exceeded", {issue.code for issue in issues})
                issues, *_ = validator.validate(workspace, strict=False, emit=False, mark_ready=True,
                                                reviewer="合成审核员乙（测试岗）")
                self.assertTrue(any(issue.severity == "error" for issue in issues))
            meta = tx.parse_frontmatter(total.read_text(encoding="utf-8"))
            self.assertEqual((meta["workflow_stage"], meta["ready_for_use"]), ("planning", "false"))
            self.assertTrue(all(not meta[field] for field in validator.READINESS_FIELDS))
            self.assertEqual(before, {p.name: tx.parse_frontmatter(p.read_text(encoding="utf-8"))["evidence_cutoff_date"]
                                      for p in workspace.glob("*.md")})
            self.assertEqual(research_bytes, {p: p.read_bytes() for p in research_bytes})
            self.govern(workspace)

    def test_B04_explicitly_invalidated_old_reviews_can_enter_planning(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(Path(temporary))
            self.approve_and_ready(workspace)
            total = next(workspace.glob("*客户研究与拜访准备报告.md"))
            strategy = next(workspace.glob("*交流策略与议题设计.md"))
            update_metadata(strategy, freshness_status="stale", review_status="changes_requested",
                            **dict.fromkeys(validator.GENERIC_REVIEW_FIELDS, ""))
            text = total.read_text(encoding="utf-8").replace(
                "| 交流策略 | true | updated | completed | approved | not_applicable | current |",
                "| 交流策略 | true | updated | completed | changes_requested | not_applicable | stale |")
            # Match the current row without assuming which approval run last updated it.
            lines = text.splitlines()
            for index, line in enumerate(lines):
                if line.startswith("| 交流策略 |"):
                    cells = [cell.strip() for cell in line.split("|")[1:-1]]
                    cells[4], cells[6] = "changes_requested", "stale"
                    lines[index] = "| " + " | ".join(cells) + " |"
            total.write_text("\n".join(lines) + "\n", encoding="utf-8")
            update_metadata(total, workflow_stage="closed", freshness_status="stale", ready_for_use="false",
                            **dict.fromkeys(validator.READINESS_FIELDS, ""))
            _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
            initializer.initialize(self.resume_args(workspace))
            self.govern(workspace)
            meta = tx.parse_frontmatter(total.read_text(encoding="utf-8"))
            self.assertEqual((meta["workflow_stage"], meta["ready_for_use"]), ("planning", "false"))
            self.assertEqual(tx.parse_frontmatter(strategy.read_text(encoding="utf-8"))["review_status"], "changes_requested")
            self.assertTrue(all(not meta[field] for field in validator.READINESS_FIELDS))
            before = workspace_bytes(workspace)
            strict = run_python("validate_outputs.py", [str(workspace), "--strict", "--json"])
            self.assertEqual(strict.returncode, 1, strict.stdout)
            self.assertIn("ready_for_use_required", strict.stdout)
            self.assertEqual(workspace_bytes(workspace), before)

    def test_B04_refresh_does_not_ignore_integrity_identity_or_unfinished_transaction(self):
        for damage in ("identity", "body_hash", "manifest", "transaction"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_strategy_workspace(Path(temporary))
                leader = next(workspace.glob("*人物研究报告.md"))
                if damage == "identity":
                    update_metadata(leader, customer_id="different-customer")
                elif damage == "body_hash":
                    leader.write_bytes(leader.read_bytes() + b"\nchanged\n")
                elif damage == "manifest":
                    (workspace / tx.MANIFEST_REL).write_bytes(b"{broken")
                else:
                    tx.journal_path(workspace).write_text("{}", encoding="utf-8")
                before = workspace_bytes(workspace)
                with self.assertRaises((initializer.InitError, tx.TxError)):
                    initializer.initialize(self.resume_args(workspace))
                self.assertEqual(workspace_bytes(workspace), before)

    def test_B04_refresh_code_filter_never_ignores_security_or_cas_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(Path(temporary))
            before = workspace_bytes(workspace)
            for code in ("authorization_expired", "identity_mismatch", "review_body_drift", "manifest_artifact_drift", "cas_conflict", "business_config_read_error"):
                # Inject a mixed validator response at the production preflight boundary.
                payload = {"errors": 2, "issues": [{"severity": "error", "code": item}
                           for item in ("freshness_ttl_exceeded", code)]}
                result = subprocess.CompletedProcess([], 1, json.dumps(payload), "")
                with self.subTest(code=code), patch.object(initializer.subprocess, "run", return_value=result):
                    with self.assertRaisesRegex(initializer.InitError, code):
                        initializer.initialize(self.resume_args(workspace))
                    self.assertEqual(workspace_bytes(workspace), before)

    def test_P2_config_failures_validate_cli_and_production_wrapper_preserve_cause(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = build_pending_strategy_workspace(root / "output")
            copy_scripts = root / "isolated" / "scripts"
            copy_scripts.mkdir(parents=True)
            for name in ("validate_outputs.py", "runtime_tx.py"):
                (copy_scripts / name).write_bytes((SCRIPTS / name).read_bytes())
            config = copy_scripts.parent / "config" / "business-modes.json"
            config.parent.mkdir()
            original_read = Path.read_text
            for raw, cause in ((None, "FileNotFoundError"), (b"{broken", "JSONDecodeError"), (b"\xff", "UnicodeDecodeError"), (b"{}", "profiles")):
                with self.subTest(cause=cause):
                    if raw is not None:
                        config.write_bytes(raw)
                    def config_read(path, *args, **kwargs):
                        if path == SCRIPTS.parent / "config" / "business-modes.json":
                            return original_read(config, *args, **kwargs)
                        return original_read(path, *args, **kwargs)
                    with patch.object(Path, "read_text", config_read):
                        issues, *_ = validator.validate(workspace, strict=False, emit=False)
                    issue = next(issue for issue in issues if issue.code == "business_config_read_error")
                    self.assertIn(cause, issue.message)
                    result = subprocess.run([sys.executable, "-B", str(copy_scripts / "validate_outputs.py"),
                                             str(workspace), "--json"], capture_output=True, text=True,
                                            encoding="utf-8", timeout=30, check=False)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stderr, "")
                    payload = json.loads(result.stdout)
                    self.assertTrue(any(item["code"] == "business_config_read_error" and cause in item["message"]
                                        for item in payload["issues"]))
                    with patch.object(initializer, "__file__", str(copy_scripts / "init_workspace.py")):
                        with self.assertRaisesRegex(initializer.InitError, "business_config_read_error.*" + cause):
                            initializer.validate_workspace_postflight(workspace)


if __name__ == "__main__":
    unittest.main()
