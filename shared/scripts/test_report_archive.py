"""Real Windows ACL tests use only uniquely owned temp fixtures; no MEMORY writes."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_archive as archive

CONTENT = """# 数字健康周报｜2000年1月3日—9日

报告周期：2000-01-03 至 2000-01-09
出刊日期：2000-01-09
生成时点：2000-01-10T00:00:00+08:00
报告时区：Asia/Shanghai

## 关键事件与来源

本周期未发现符合纳入标准的事件
"""


@unittest.skipUnless(os.name == "nt", "Windows native ACL publication only")
class ReportArchiveWindowsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.gettempdir()) / ("hit-archive-test-" + uuid.uuid4().hex)
        self.root.mkdir(mode=0o777)
        self.addCleanup(shutil.rmtree, self.root)
        self.parent = self.root / "archive"
        self.parent.mkdir(mode=0o777)
        self.draft_dir = Path(tempfile.mkdtemp(prefix="private-", dir=self.root))
        self.source = self.draft_dir / "DHWB-20000109.md"
        self.source.write_text(CONTENT, encoding="utf-8")
        self.target = self.parent / self.source.name
        self.security = archive.backend()

    def plan(self):
        return archive.validate(self.source, self.target, self.target, "hit-weekly-brief")

    def publish(self):
        result = archive.commit(self.plan(), self.target)
        self.assertEqual("COMMITTED", result["status"], result)
        return result

    def set_protected_fixture_policy(self, path, policy):
        # Fixture creation accepts native canonicalization; publication must
        # still preserve the exact descriptor read back from Windows.
        s = self.security.security
        requested = s.ConvertStringSecurityDescriptorToSecurityDescriptor(policy, 1)
        self.assertTrue(requested.GetSecurityDescriptorControl()[0] & s.SE_DACL_PROTECTED)
        s.SetNamedSecurityInfo(str(path), s.SE_FILE_OBJECT,
            self.security.SECURITY_PARTS | s.PROTECTED_DACL_SECURITY_INFORMATION,
            requested.GetSecurityDescriptorOwner(), requested.GetSecurityDescriptorGroup(),
            requested.GetSecurityDescriptorDacl(), None)
        actual = self.security.descriptor(path)
        installed = s.ConvertStringSecurityDescriptorToSecurityDescriptor(actual, 1)
        self.assertTrue(installed.GetSecurityDescriptorControl()[0] & s.SE_DACL_PROTECTED)
        self.assertEqual(requested.GetSecurityDescriptorOwner(), installed.GetSecurityDescriptorOwner())
        self.assertEqual(requested.GetSecurityDescriptorGroup(), installed.GetSecurityDescriptorGroup())
        return actual

    def test_new_real_owner_inherited_dacl_and_limited_access(self):
        result = self.publish()
        self.assertTrue(self.source.exists())
        self.assertEqual(archive.digest(self.source.read_bytes()), result["sha256"])
        s = self.security.security
        parent = s.ConvertStringSecurityDescriptorToSecurityDescriptor(self.security.descriptor(self.parent), 1)
        final = s.ConvertStringSecurityDescriptorToSecurityDescriptor(self.security.descriptor(self.target), 1)
        self.assertEqual(parent.GetSecurityDescriptorOwner(), final.GetSecurityDescriptorOwner())
        self.assertFalse(final.GetSecurityDescriptorControl()[0] & s.SE_DACL_PROTECTED)
        self.assertEqual("read/write/modify", result["security"]["limited_token_accesscheck"])
        self.assertIn("actual_non_elevated_open", result["security"])

    def test_new_file_preserves_immediate_child_no_propagate_deny(self):
        s = self.security.security
        token, _ = self.security.limited_token()
        try:
            sid = s.ConvertSidToStringSid(s.GetTokenInformation(token, s.TokenUser)[0])
        finally:
            token.Close()
        # Only this fixture parent changes. Anonymous is not the publishing
        # user: its one-generation deny must survive alongside propagating allow.
        policy = f"O:{sid}G:{sid}D:P(D;OICINP;FW;;;AN)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;{sid})(A;OICI;FR;;;AN)"
        self.set_protected_fixture_policy(self.parent, policy)
        probe = self.parent / "immediate-file.md"
        probe.write_bytes(b"")
        expected = self.security.parent_owner_policy(self.parent, probe)
        probe.unlink()
        result = self.publish()
        self.assertEqual(expected, self.security.descriptor(self.target))
        final = s.ConvertStringSecurityDescriptorToSecurityDescriptor(expected, 1)
        aces = [final.GetSecurityDescriptorDacl().GetAce(i)
                for i in range(final.GetSecurityDescriptorDacl().GetAceCount())]
        self.assertTrue(any(ace[0][0] == s.ACCESS_DENIED_ACE_TYPE
                            and s.ConvertSidToStringSid(ace[2]) == "S-1-5-7" for ace in aces))
        self.assertEqual(expected, result["security"]["descriptor"])

    def test_cross_skill_custom_filename_collision_preserves_both_files(self):
        self.target = self.parent / "custom.md"
        scout = CONTENT.replace("# 数字健康周报｜2000年1月3日—9日",
                                "# 医疗数字化文献侦察报告 - 2000-01-09")
        scout = scout.replace("报告时区：Asia/Shanghai", "报告时区：Asia/Shanghai\n命名依据：explicit")
        scout = scout.replace("## 关键事件与来源", "## 本期研究").replace(
            "本周期未发现符合纳入标准的事件", "本周期未发现符合纳入标准的研究\n\n## 来源")
        self.target.write_text(scout, encoding="utf-8")
        before = (self.source.read_bytes(), self.target.read_bytes(), self.security.descriptor(self.target))
        with self.assertRaises(archive.Blocked) as caught:
            archive.validate(self.source, self.target, self.target, "hit-weekly-brief", custom_filename=True)
        self.assertEqual("COLLISION", caught.exception.code)
        self.assertEqual(before, (self.source.read_bytes(), self.target.read_bytes(), self.security.descriptor(self.target)))

    def test_legacy_title_identity_blocks_without_rewriting(self):
        self.target.write_text(CONTENT.replace("# 数字健康周报｜2000年1月3日—9日", "# 旧版标题"), encoding="utf-8")
        before = self.target.read_bytes()
        with self.assertRaises(archive.Blocked) as caught:
            self.plan()
        self.assertEqual("COLLISION", caught.exception.code)
        self.assertEqual(before, self.target.read_bytes())

    def test_private_draft_acl_is_not_published(self):
        # Reproduce the elevated Administrators-owned private policy explicitly;
        # this host's mkdtemp may instead choose the current user as owner.
        policy = self.set_protected_fixture_policy(self.source, "O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)")
        with self.assertRaises(self.security.CapabilityError):
            self.security.effective_access(self.source, self.source.read_bytes())
        self.publish()
        self.assertEqual(policy, self.security.descriptor(self.source))
        self.assertNotEqual(policy, self.security.descriptor(self.target))

    def test_replacement_preserves_custom_protected_owner_group_dacl(self):
        self.publish()
        s = self.security.security
        token, _ = self.security.limited_token()
        try:
            sid = s.ConvertSidToStringSid(s.GetTokenInformation(token, s.TokenUser)[0])
        finally:
            token.Close()
        # Custom protected ACL: no Everyone grant; preserve exact explicit policy.
        policy = f"O:{sid}G:{sid}D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x1301bf;;;{sid})"
        policy = self.set_protected_fixture_policy(self.target, policy)
        original = self.target.read_bytes()
        self.source.write_text(CONTENT + "\n修订说明：格式复核。\n", encoding="utf-8")
        result = self.publish()
        self.assertEqual(policy, self.security.descriptor(self.target))
        backup = Path(result["recovery_directory"]) / "original.md"
        self.assertEqual(original, backup.read_bytes())
        self.assertEqual(policy, self.security.descriptor(backup))
        self.assertEqual("original_retained", result["rollback"])

    def test_replacement_preserves_unprotected_policy(self):
        self.publish()
        old_policy = self.security.descriptor(self.target)
        self.source.write_text(CONTENT + "\n修订。\n", encoding="utf-8")
        self.publish()
        self.assertEqual(old_policy, self.security.descriptor(self.target))

    def test_content_drift_blocks_before_commit(self):
        self.publish()
        plan = self.plan()
        self.target.write_text(CONTENT + "\n另一写者。\n", encoding="utf-8")
        newer = self.target.read_bytes()
        result = archive.commit(plan, self.target)
        self.assertEqual("COLLISION", result["code"])
        self.assertEqual(newer, self.target.read_bytes())

    def test_source_drift_blocks_before_commit(self):
        plan = self.plan()
        self.source.write_text(CONTENT + "\n变更。\n", encoding="utf-8")
        result = archive.commit(plan, self.target)
        self.assertEqual("COLLISION", result["code"])
        self.assertFalse(self.target.exists())

    def test_security_drift_blocks_before_commit(self):
        self.publish()
        plan = self.plan()
        original_policy = self.security.descriptor(self.target)
        policy = self.set_protected_fixture_policy(self.target, original_policy.replace("D:AI", "D:PAI"))
        self.assertNotEqual(original_policy, policy)
        result = archive.commit(plan, self.target)
        self.assertEqual("COLLISION", result["code"])
        self.assertEqual(policy, self.security.descriptor(self.target))

    def test_new_target_race_no_overwrite(self):
        plan = self.plan()
        real_rename = os.rename
        def raced(source, target):
            self.target.write_text("newer unrelated target", encoding="utf-8")
            return real_rename(source, target)
        with patch.object(archive.os, "rename", side_effect=raced):
            result = archive.commit(plan, self.target)
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("newer unrelated target", self.target.read_text())
        self.assertTrue(Path(result["recovery_directory"]).exists())

    def test_cooperative_writer_lock(self):
        plan = self.plan()
        lock = self.parent / (".report-archive-" + archive.digest(self.target.name.lower().encode())[:24] + ".lock")
        lock.write_text("other writer", encoding="utf-8")
        result = archive.commit(plan, self.target)
        self.assertEqual("COLLISION", result["code"])
        self.assertEqual("other writer", lock.read_text())

    def test_postcommit_newer_target_is_never_rolled_back(self):
        self.publish()
        original = self.target.read_bytes()
        self.source.write_text(CONTENT + "\n修订。\n", encoding="utf-8")
        plan = self.plan()
        real_replace = os.replace
        def raced(source, target):
            real_replace(source, target)
            self.target.write_text(CONTENT + "\n更新的并发内容。\n", encoding="utf-8")
        with patch.object(archive.os, "replace", side_effect=raced):
            result = archive.commit(plan, self.target)
        self.assertEqual("POSTCOMMIT", result["code"])
        self.assertIn("更新的并发内容", self.target.read_text(encoding="utf-8"))
        self.assertEqual(original, (Path(result["recovery_directory"]) / "original.md").read_bytes())
        self.assertEqual("not_attempted_preserve_evidence", result["rollback"])

    def test_access_failure_precommit_retains_draft_no_target(self):
        plan = self.plan()
        with patch.object(self.security, "effective_access", side_effect=self.security.CapabilityError("injected denial")):
            result = archive.commit(plan, self.target)
        self.assertEqual("ACCESS_CHECK", result["code"])
        self.assertTrue(self.source.exists())
        self.assertFalse(self.target.exists())
        journal = json.loads((Path(result["recovery_directory"]) / "journal.json").read_text(encoding="utf-8"))
        candidate = Path(journal["candidate"])
        self.assertEqual(self.parent, candidate.parent)
        self.assertTrue(candidate.exists())
        self.assertEqual(self.source.read_bytes(), candidate.read_bytes())

    def test_postcommit_access_failure_preserves_original_and_can_recover_with_fresh_plan(self):
        self.publish()
        original = self.target.read_bytes()
        self.source.write_text(CONTENT + "\n修订。\n", encoding="utf-8")
        plan = self.plan()
        real_access = self.security.effective_access
        def check(path, data):
            if path == self.target and data != original:
                raise self.security.CapabilityError("injected postcommit failure")
            return real_access(path, data)
        with patch.object(self.security, "effective_access", side_effect=check):
            result = archive.commit(plan, self.target)
        self.assertEqual("POSTCOMMIT", result["code"])
        backup = Path(result["recovery_directory"]) / "original.md"
        recovery = archive.validate(backup, self.target, self.target, "hit-weekly-brief")
        restored = archive.commit(recovery, self.target)
        self.assertEqual("COMMITTED", restored["status"], restored)
        self.assertEqual(original, self.target.read_bytes())
        self.assertEqual(plan["expected_target"]["security"], self.security.descriptor(self.target))

    def test_identity_conflict_and_same_path_rejected(self):
        self.target.write_text(CONTENT.replace("2000-01-03 至", "1999-12-27 至"), encoding="utf-8")
        with self.assertRaises(archive.Blocked) as caught:
            self.plan()
        self.assertEqual("COLLISION", caught.exception.code)
        with self.assertRaises(archive.Blocked):
            archive.validate(self.source, self.source, self.source, "hit-weekly-brief")

    def test_hardlink_rejected(self):
        os.link(self.source, self.parent / "alias.md")
        with self.assertRaises(archive.Blocked):
            self.plan()

    def test_exact_whitelist_required(self):
        with self.assertRaises(archive.Blocked):
            archive.validate(self.source, self.target, self.parent / "another.md", "hit-weekly-brief")
        result = archive.commit(self.plan(), self.parent / "another.md")
        self.assertEqual("INPUT", result["code"])
        self.assertFalse(self.target.exists())

    def test_cli_fresh_process_validate_commit_read_and_malformed_plan(self):
        script = Path(archive.__file__)
        def run(*args):
            return subprocess.run([sys.executable, "-B", "-X", "utf8", str(script), *map(str, args)],
                capture_output=True, text=True, encoding="utf-8", timeout=20)
        checked = run("validate", "--source", self.source, "--target", self.target,
                      "--allow-target", self.target, "--skill", "hit-weekly-brief")
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        plan_file = self.draft_dir / "plan.json"
        plan_file.write_text(checked.stdout, encoding="utf-8")
        result = run("commit", "--plan", plan_file, "--allow-target", self.target)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("COMMITTED", json.loads(result.stdout)["status"])
        read = subprocess.run([sys.executable, "-B", "-c",
            "import pathlib,hashlib,sys;print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())", str(self.target)],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(archive.digest(self.source.read_bytes()), read.stdout.strip())
        plan_file.write_text('{"schema":1,"schema":1}', encoding="utf-8")
        self.assertNotEqual(0, run("commit", "--plan", plan_file, "--allow-target", self.target).returncode)


if __name__ == "__main__":
    unittest.main()
