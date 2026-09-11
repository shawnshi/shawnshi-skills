"""Regression tests for build_candidate run versions and draft-only commits."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.common import run_python
from tests.fixture_builder import (
    build_pending_letter_workspace,
    build_pending_strategy_workspace,
)
from tests.test_candidate_revision import b, v


def formal_bytes(workspace: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in workspace.glob("*.md")} | {
        "runtime/manifest.json": (workspace / "runtime/manifest.json").read_bytes()
    }


def document(workspace: Path, suffix: str):
    path = next(workspace.glob("*" + suffix))
    text = path.read_text(encoding="utf-8")
    return v.Document(path, text, b.tx.parse_frontmatter(text), v.body_from_text(text))


class BuildCandidateHistoryTests(unittest.TestCase):
    def assert_valid(self, workspace):
        result = run_python("validate_outputs.py", [str(workspace), "--json"])
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(json.loads(result.stdout)["errors"], 0)

    def commit(self, workspace, candidate, result):
        args = [
            str(workspace),
            "--candidate-workspace",
            str(candidate),
            "--expected-manifest-revision",
            str(result["expected_manifest_revision"]),
            "--expected-manifest-sha256",
            result["expected_manifest_sha256"],
            "--json",
        ]
        accepted = run_python("commit_run.py", args)
        self.assertEqual(accepted.returncode, 0, accepted.stderr or accepted.stdout)
        self.assert_valid(workspace)
        self.assertEqual(
            document(workspace, "客户研究与拜访准备报告.md").frontmatter[
                "ready_for_use"
            ],
            "false",
        )
        # A stale candidate cannot overwrite the newly committed manifest.
        committed = formal_bytes(workspace)
        refused = run_python("commit_run.py", args)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("CAS", refused.stderr)
        self.assertEqual(formal_bytes(workspace), committed)
        with self.assertRaises(b.tx.CASMismatch):
            b.finalize(workspace, candidate)
        self.assertEqual(formal_bytes(workspace), committed)

    def finalize_twice(self, workspace, root):
        before = formal_bytes(workspace)
        candidate = b.prepare(workspace, root / "candidates")
        result = None
        first_versions = None
        for attempt in range(2):
            result = b.finalize(workspace, candidate)
            self.assertEqual(result["errors"], [], result)
            self.assert_valid(candidate)
            self.assertEqual(formal_bytes(workspace), before)
            total = document(candidate, "客户研究与拜访准备报告.md")
            history = v.version_history_rows(total, [])
            versions = [row[1] for row in history]
            self.assertEqual(len({row[2] for row in history}), len(history))
            self.assertEqual(versions, [str(i) for i in range(1, len(history) + 1)])
            if attempt == 0:
                first_versions = versions
            else:
                self.assertEqual(versions, first_versions)
        assert result is not None
        return candidate, result, before

    def test_new_initialization_finalize_and_commit_keeps_allocated_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            seed = build_pending_strategy_workspace(root / "synthetic-content")
            initialized = run_python(
                "init_workspace.py",
                [
                    "示例医院",
                    "--output-root",
                    str(root / "formal"),
                    "--business-mode",
                    "standard_visit",
                    "--task-timezone",
                    "Asia/Shanghai",
                    "--runtime-owner",
                    "测试负责人",
                    "--json",
                ],
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            workspace = Path(json.loads(initialized.stdout)["workspace"])
            self.assert_valid(workspace)
            before = formal_bytes(workspace)
            candidate = b.prepare(workspace, root / "candidates")
            # Populate only candidate drafts with synthetic fixture content,
            # inheriting the real initializer's identity and run. No manifest edit.
            for path in candidate.glob("*.md"):
                source = (seed / path.name).read_text(encoding="utf-8")
                source_meta = b.tx.parse_frontmatter(source)
                original_meta = b.tx.parse_frontmatter(path.read_text(encoding="utf-8"))
                source = source.replace(
                    source_meta["latest_run_id"], original_meta["latest_run_id"]
                )
                source = source.replace(
                    source_meta["updated_at"], original_meta["updated_at"]
                )
                inherited = {
                    key: original_meta[key]
                    for key in (
                        "context_id",
                        "customer_id",
                        "customer_display_name",
                        "organization_scope",
                        "safe_name",
                        "content_version",
                        "latest_run_id",
                        "updated_at",
                    )
                }
                path.write_text(
                    b.init.replace_frontmatter(source, inherited), encoding="utf-8"
                )
            result = b.finalize(workspace, candidate)
            self.assertEqual(result["errors"], [], result)
            self.assert_valid(candidate)
            self.assertEqual(
                document(candidate, "客户研究与拜访准备报告.md").frontmatter[
                    "content_version"
                ],
                "1",
            )
            self.assertEqual(formal_bytes(workspace), before)
            self.commit(workspace, candidate, result)
            self.assertNotEqual(formal_bytes(workspace), before)

    def test_resume_strategy_finalize_and_commit_has_contiguous_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = build_pending_strategy_workspace(root / "formal")
            self.assert_valid(workspace)
            old_history = v.version_history_rows(
                document(workspace, "客户研究与拜访准备报告.md"), []
            )
            resumed = run_python(
                "init_workspace.py",
                [
                    "示例医院",
                    "--output-root",
                    str(workspace.parent),
                    "--resume",
                    "--business-mode",
                    "standard_visit",
                    "--json",
                ],
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assert_valid(workspace)
            candidate, result, before = self.finalize_twice(workspace, root)
            self.assertEqual(
                v.version_history_rows(
                    document(candidate, "客户研究与拜访准备报告.md"), []
                )[:-1],
                old_history,
            )
            self.commit(workspace, candidate, result)
            self.assertNotEqual(formal_bytes(workspace), before)

    def test_pending_letter_same_run_finalize_is_structurally_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = build_pending_letter_workspace(root / "formal")
            self.assert_valid(workspace)
            original = document(workspace, "客户信（内部待审核稿）.md")
            candidate, result, before = self.finalize_twice(workspace, root)
            letter = document(candidate, "客户信（内部待审核稿）.md")
            self.assertEqual(
                letter.frontmatter["content_version"],
                original.frontmatter["content_version"],
            )
            self.assertEqual(len(v.letter_review_history_rows(letter, [])), 1)
            self.assertEqual(letter.frontmatter["review_status"], "pending")
            self.assertTrue(
                all(not letter.frontmatter[key] for key in v.APPROVAL_FIELDS)
            )
            self.assertEqual(
                v.extract_external_body(letter), v.extract_external_body(original)
            )
            self.commit(workspace, candidate, result)
            self.assertNotEqual(formal_bytes(workspace), before)

    def test_pending_letter_new_run_appends_once_and_preserves_old_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = build_pending_letter_workspace(root / "formal")
            self.assert_valid(workspace)
            original = document(workspace, "客户信（内部待审核稿）.md")
            old_history = v.letter_review_history_rows(original, [])
            resumed = run_python(
                "init_workspace.py",
                [
                    "示例医院",
                    "--output-root",
                    str(workspace.parent),
                    "--resume",
                    "--business-mode",
                    "letter",
                    "--json",
                ],
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            candidate, result, before = self.finalize_twice(workspace, root)
            letter = document(candidate, "客户信（内部待审核稿）.md")
            history = v.letter_review_history_rows(letter, [])
            self.assertEqual(history[:-1], old_history)
            self.assertEqual([row[1] for row in history], ["1", "2"])
            self.assertEqual(len({row[2] for row in history}), 2)
            self.assertEqual(letter.frontmatter["review_status"], "pending")
            self.commit(workspace, candidate, result)
            self.assertNotEqual(formal_bytes(workspace), before)

    def test_existing_approved_guard_is_not_bypassed_by_candidate_downgrade(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = build_pending_letter_workspace(root / "formal")
            before = formal_bytes(workspace)
            candidate = b.prepare(workspace, root / "candidates")
            parse = b.tx.parse_frontmatter

            def approved_original(text):
                meta = parse(text)
                if meta.get("artifact_type") == "customer_letter_internal":
                    meta["review_status"] = "approved"
                return meta

            # Inject only the original-metadata seam. Never execute an approval
            # or fabricate a successful business manifest to exercise this guard.
            with (
                patch.object(b.tx, "parse_frontmatter", side_effect=approved_original),
                self.assertRaisesRegex(ValueError, "已批准成果"),
            ):
                b.finalize(workspace, candidate)
            self.assertEqual(formal_bytes(workspace), before)

    def test_candidate_cannot_elevate_approval_ready_or_authorization(self):
        for key, value in [
            ("review_status", "approved"),
            ("ready_for_use", "true"),
            ("authorization_owner", "ungranted-owner"),
        ]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                workspace = build_pending_letter_workspace(root / "formal")
                before = formal_bytes(workspace)
                candidate = b.prepare(workspace, root / "candidates")
                letter = document(candidate, "客户信（内部待审核稿）.md")
                letter.path.write_text(
                    b.init.replace_frontmatter(letter.text, {key: value}),
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError):
                    b.finalize(workspace, candidate)
                self.assertEqual(formal_bytes(workspace), before)
