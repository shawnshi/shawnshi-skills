from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from tests.common import SCRIPTS, load_module
from tests.common import runtime_tx as tx

initializer = load_module("date_boundary_initializer", SCRIPTS / "init_workspace.py")
validator = load_module("date_boundary_validator", SCRIPTS / "validate_outputs.py")
with patch.dict(sys.modules, {"init_workspace": initializer}):
    committer = load_module("date_boundary_committer", SCRIPTS / "commit_run.py")


class DateBoundaryTests(unittest.TestCase):
    @contextlib.contextmanager
    def clock(self, instant: str):
        frozen = datetime.fromisoformat(instant)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

        # Run the real postflight CLI under the same clock, not a mocked result.
        def postflight(command, **kwargs):
            self.assertEqual(Path(command[1]).name, "validate_outputs.py")
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch.object(sys, "argv", command[1:]):
                code = validator.main()
            print("POSTFLIGHT", output.getvalue(), flush=True)
            return subprocess.CompletedProcess(command, code, output.getvalue(), "")

        with patch.object(initializer, "datetime", Clock), patch.object(validator, "datetime", Clock), \
                patch.object(initializer.subprocess, "run", side_effect=postflight):
            yield frozen

    def initialize(self, root: Path, zone: str | None, cutoff: str | None = None) -> Path:
        args = ["日期边界合成医院", "--output-root", str(root), "--modules", "institution",
                "--runtime-owner", "合成测试岗"]
        if zone is not None:
            args += ["--task-timezone", zone]
        if cutoff is not None:
            args += ["--evidence-cutoff-date", cutoff]
        return Path(initializer.initialize(initializer.build_parser().parse_args(args))["workspace"])

    def total(self, workspace: Path) -> Path:
        return next(workspace.glob("*客户研究与拜访准备报告.md"))

    def issues(self, workspace: Path):
        issues, *_ = validator.validate(workspace, strict=False, emit=False)
        print("READ", [(i.code, i.path) for i in issues], flush=True)
        return issues

    def snapshot(self, workspace: Path):
        # Persistent process-lock bookkeeping is not committed artifact state.
        return {p.relative_to(workspace).as_posix(): p.read_bytes() for p in workspace.rglob("*")
                if p.is_file() and p.suffix in {".md", ".json"}}

    def test_init_postflight_and_read_cross_day(self):
        cases = [("Asia/Shanghai", "2026-09-06T22:36:00+00:00", "2026-09-07"),
                 ("America/Los_Angeles", "2026-09-06T02:36:00+00:00", "2026-09-05"),
                 ("UTC", "2026-09-06T22:36:00+00:00", "2026-09-06")]
        for zone, instant, expected in cases:
            with self.subTest(zone=zone), tempfile.TemporaryDirectory() as tmp, self.clock(instant):
                workspace = self.initialize(Path(tmp), zone)
                for path in workspace.glob("*.md"):
                    self.assertEqual(tx.parse_frontmatter(path.read_text(encoding="utf-8"))["evidence_cutoff_date"], expected)
                self.assertEqual(tx.parse_frontmatter(self.total(workspace).read_text(encoding="utf-8"))["task_timezone"], zone)
                self.assertFalse([i for i in self.issues(workspace) if i.severity == "error"])
                tx.verify_manifest_artifacts(workspace, tx.load_manifest(workspace))

    def test_ttl_exact_boundary_and_next_local_day(self):
        cases = [("Asia/Shanghai", "2026-09-06T22:36:00+00:00", "2026-09-07"),
                 ("America/Los_Angeles", "2026-09-06T02:36:00+00:00", "2026-09-05"),
                 ("UTC", "2026-09-06T22:36:00+00:00", "2026-09-06"),
                 (None, "2026-09-06T22:36:00+00:00", "2026-09-06")]
        for zone, instant, today in cases:
            with self.subTest(zone=zone), tempfile.TemporaryDirectory() as tmp:
                ttl = validator.DEFAULT_TTL_DAYS["comprehensive_report"]
                cutoff = (datetime.fromisoformat(today) - timedelta(days=ttl)).date().isoformat()
                with self.clock(instant) as frozen:
                    workspace = self.initialize(Path(tmp), zone, cutoff)
                    self.assertNotIn("freshness_ttl_exceeded", {i.code for i in self.issues(workspace) if i.path == str(self.total(workspace))})
                with self.clock((frozen + timedelta(days=1)).isoformat()):
                    self.assertIn("freshness_ttl_exceeded", {i.code for i in self.issues(workspace) if i.path == str(self.total(workspace))})

    def test_legacy_utc_does_not_require_iana_database(self):
        with tempfile.TemporaryDirectory() as tmp, self.clock("2026-09-06T22:36:00+00:00"), \
                patch.object(validator, "ZoneInfo", side_effect=validator.ZoneInfoNotFoundError("no tzdata")):
            workspace = self.initialize(Path(tmp), None, "2026-09-06")
            self.assertNotIn("task_timezone", tx.parse_frontmatter(self.total(workspace).read_text(encoding="utf-8")))
            self.assertFalse([i for i in self.issues(workspace) if i.severity == "error"])

    def test_future_cutoff_rejected_in_each_calendar(self):
        for zone, future in [("Asia/Shanghai", "2026-09-08"), ("America/Los_Angeles", "2026-09-07"),
                             ("UTC", "2026-09-07"), (None, "2026-09-07")]:
            with self.subTest(zone=zone), tempfile.TemporaryDirectory() as tmp, self.clock("2026-09-06T22:36:00+00:00"):
                with self.assertRaisesRegex(initializer.InitError, "evidence_cutoff_in_future"):
                    self.initialize(Path(tmp), zone, future)
                self.assertFalse(list(Path(tmp).glob("客户研究-*")))

    def test_invalid_iana_and_module_conflict_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp, self.clock("2026-09-06T22:36:00+00:00"):
            with self.assertRaisesRegex(initializer.InitError, "IANA"):
                self.initialize(Path(tmp), "Invalid/TaskZone")
            workspace = self.initialize(Path(tmp), "Asia/Shanghai")
            total = self.total(workspace)
            original = total.read_bytes()
            total.write_bytes(original.replace(b"Asia/Shanghai", b"Invalid/TaskZone"))
            self.assertIn("task_timezone_invalid", {i.code for i in self.issues(workspace)})
            total.write_bytes(original)
            module = next(workspace.glob("*机构研究报告.md"))
            module.write_text(initializer.inject_runtime_frontmatter(module.read_text(encoding="utf-8"), {"task_timezone": "UTC"}), encoding="utf-8")
            self.assertIn("task_timezone_mismatch", {i.code for i in self.issues(workspace)})

    def test_resume_preserves_calendar_absence_and_rejects_change(self):
        for zone in (None, "Asia/Shanghai"):
            with self.subTest(zone=zone), tempfile.TemporaryDirectory() as tmp, self.clock("2026-09-06T22:36:00+00:00"):
                workspace = self.initialize(Path(tmp), zone, "2026-09-06")
                args = ["日期边界合成医院", "--output-root", tmp, "--resume", "--modules", "institution"]
                initializer.initialize(initializer.build_parser().parse_args(args))
                metadata = tx.parse_frontmatter(self.total(workspace).read_text(encoding="utf-8"))
                self.assertEqual(metadata.get("task_timezone"), zone)
                self.assertEqual(metadata["evidence_cutoff_date"], "2026-09-06")
                before = self.snapshot(workspace)
                with self.assertRaisesRegex(initializer.InitError, "task-timezone"):
                    initializer.initialize(initializer.build_parser().parse_args(args + ["--task-timezone", "America/Los_Angeles"]))
                self.assertEqual(self.snapshot(workspace), before)

    def test_manifest_hash_and_candidate_cas_protect_timezone(self):
        for zone in (None, "Asia/Shanghai"):
            with self.subTest(zone=zone), tempfile.TemporaryDirectory() as tmp, self.clock("2026-09-06T22:36:00+00:00"):
                root = Path(tmp)
                workspace = self.initialize(root, zone, "2026-09-06")
                total = self.total(workspace)
                original = total.read_bytes()
                revision, digest = tx.manifest_state(workspace)
                candidate = root / "candidate"
                candidate.mkdir()
                args = committer.build_parser().parse_args([str(workspace), "--candidate-workspace", str(candidate),
                    "--expected-manifest-revision", str(revision), "--expected-manifest-sha256", digest])
                before = self.snapshot(workspace)
                changes = ["UTC", "", "America/Los_Angeles"] if zone else ["UTC", "Asia/Shanghai", ""]
                for changed in changes:
                    text = initializer.inject_runtime_frontmatter(original.decode("utf-8"), {"task_timezone": changed})
                    (candidate / total.name).write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(tx.CASMismatch, "task_timezone"):
                        committer.commit(args)
                    self.assertEqual(self.snapshot(workspace), before)
                if zone:
                    text = "\n".join(line for line in original.decode("utf-8").split("\n") if not line.startswith("task_timezone:"))
                    (candidate / total.name).write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(tx.CASMismatch, "task_timezone"):
                        committer.commit(args)
                total.write_text(initializer.inject_runtime_frontmatter(original.decode("utf-8"), {"task_timezone": "UTC"}), encoding="utf-8")
                with self.assertRaises(tx.CASMismatch):
                    tx.verify_manifest_artifacts(workspace, tx.load_manifest(workspace))
                total.write_bytes(original)
                (candidate / total.name).write_bytes(original)
                committer.commit(args)
                tx.verify_manifest_artifacts(workspace, tx.load_manifest(workspace))
                self.assertEqual(tx.parse_frontmatter(total.read_text(encoding="utf-8")).get("task_timezone"), zone)


if __name__ == "__main__":
    unittest.main()
