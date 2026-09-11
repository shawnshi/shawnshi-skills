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
        self.root = Path(tempfile.gettempdir()) / (
            "hit-archive-test-" + uuid.uuid4().hex
        )
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
        return archive.validate(
            self.source, self.target, self.target, "hit-weekly-brief"
        )

    def publish(self):
        result = archive.commit(self.plan(), self.target)
        self.assertEqual("COMMITTED", result["status"], result)
        return result

    def set_protected_fixture_policy(self, path, policy):
        # Fixture creation accepts native canonicalization; publication must
        # still preserve the exact descriptor read back from Windows.
        s = self.security.security
        requested = s.ConvertStringSecurityDescriptorToSecurityDescriptor(policy, 1)
        self.assertTrue(
            requested.GetSecurityDescriptorControl()[0] & s.SE_DACL_PROTECTED
        )
        s.SetNamedSecurityInfo(
            str(path),
            s.SE_FILE_OBJECT,
            self.security.SECURITY_PARTS | s.PROTECTED_DACL_SECURITY_INFORMATION,
            requested.GetSecurityDescriptorOwner(),
            requested.GetSecurityDescriptorGroup(),
            requested.GetSecurityDescriptorDacl(),
            None,
        )
        actual = self.security.descriptor(path)
        installed = s.ConvertStringSecurityDescriptorToSecurityDescriptor(actual, 1)
        self.assertTrue(
            installed.GetSecurityDescriptorControl()[0] & s.SE_DACL_PROTECTED
        )
        self.assertEqual(
            requested.GetSecurityDescriptorOwner(),
            installed.GetSecurityDescriptorOwner(),
        )
        self.assertEqual(
            requested.GetSecurityDescriptorGroup(),
            installed.GetSecurityDescriptorGroup(),
        )
        return actual

    def test_exact_policy_is_idempotent_without_native_setter(self):
        candidate = self.parent / "exact.md"
        candidate.write_bytes(b"")
        policy = self.security.parent_owner_policy(self.parent, candidate)
        self.assertEqual(policy, self.security.descriptor(candidate))
        with patch.object(self.security.security, "SetNamedSecurityInfo") as setter:
            self.security.apply(candidate, policy)
            self.security.apply(candidate, policy)
            setter.assert_not_called()
        self.assertEqual(policy, self.security.descriptor(candidate))

    def test_different_policy_still_sets_and_checks_exact_descriptor(self):
        candidate = self.parent / "different.md"
        candidate.write_bytes(b"")
        policy = self.security.descriptor(candidate)
        # Inject a mismatch without altering any real ACL: no-op must not mask it.
        with (
            patch.object(self.security, "descriptor", return_value="different-policy"),
            patch.object(self.security.security, "SetNamedSecurityInfo") as setter,
        ):
            with self.assertRaisesRegex(
                self.security.CapabilityError, "fidelity unavailable"
            ):
                self.security.apply(candidate, policy)
            setter.assert_called_once()

    def test_scout_fresh_cli_create_replace_and_readback(self):
        source = self.draft_dir / "DHLS-20000109.md"
        target = self.parent / source.name
        content = CONTENT.replace(
            "# 数字健康周报｜2000年1月3日—9日", "# 医疗数字化文献侦察报告 - 2000-01-09"
        )
        content = content.replace(
            "报告时区：Asia/Shanghai", "报告时区：Asia/Shanghai\n命名依据：explicit"
        )
        content = content.replace("## 关键事件与来源", "## 本期研究").replace(
            "本周期未发现符合纳入标准的事件",
            "本周期未发现符合纳入标准的研究\n\n## 来源",
        )
        script = Path(archive.__file__)
        policies = []
        for suffix in ("", "\n修订：合成测试。\n"):
            source.write_text(content + suffix, encoding="utf-8")
            checked = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-X",
                    "utf8",
                    str(script),
                    "validate",
                    "--source",
                    str(source),
                    "--target",
                    str(target),
                    "--allow-target",
                    str(target),
                    "--skill",
                    "hit-lectures-scout",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
            plan = self.draft_dir / "scout-plan.json"
            plan.write_text(checked.stdout, encoding="utf-8")
            committed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-X",
                    "utf8",
                    str(script),
                    "commit",
                    "--plan",
                    str(plan),
                    "--allow-target",
                    str(target),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            self.assertEqual(
                0, committed.returncode, committed.stdout + committed.stderr
            )
            receipt = json.loads(committed.stdout)
            self.assertEqual("COMMITTED", receipt["status"])
            self.assertEqual(source.read_bytes(), target.read_bytes())
            self.assertEqual(archive.digest(target.read_bytes()), receipt["sha256"])
            self.assertEqual(
                "read/write/modify", receipt["security"]["limited_token_accesscheck"]
            )
            policies.append(self.security.descriptor(target))
        self.assertEqual(policies[0], policies[1])

    def test_new_real_owner_inherited_dacl_and_limited_access(self):
        result = self.publish()
        self.assertTrue(self.source.exists())
        self.assertEqual(archive.digest(self.source.read_bytes()), result["sha256"])
        s = self.security.security
        parent = s.ConvertStringSecurityDescriptorToSecurityDescriptor(
            self.security.descriptor(self.parent), 1
        )
        final = s.ConvertStringSecurityDescriptorToSecurityDescriptor(
            self.security.descriptor(self.target), 1
        )
        self.assertEqual(
            parent.GetSecurityDescriptorOwner(), final.GetSecurityDescriptorOwner()
        )
        self.assertFalse(final.GetSecurityDescriptorControl()[0] & s.SE_DACL_PROTECTED)
        self.assertEqual(
            "read/write/modify", result["security"]["limited_token_accesscheck"]
        )
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
        aces = [
            final.GetSecurityDescriptorDacl().GetAce(i)
            for i in range(final.GetSecurityDescriptorDacl().GetAceCount())
        ]
        self.assertTrue(
            any(
                ace[0][0] == s.ACCESS_DENIED_ACE_TYPE
                and s.ConvertSidToStringSid(ace[2]) == "S-1-5-7"
                for ace in aces
            )
        )
        self.assertEqual(expected, result["security"]["descriptor"])

    def test_cross_skill_custom_filename_collision_preserves_both_files(self):
        self.target = self.parent / "custom.md"
        scout = CONTENT.replace(
            "# 数字健康周报｜2000年1月3日—9日", "# 医疗数字化文献侦察报告 - 2000-01-09"
        )
        scout = scout.replace(
            "报告时区：Asia/Shanghai", "报告时区：Asia/Shanghai\n命名依据：explicit"
        )
        scout = scout.replace("## 关键事件与来源", "## 本期研究").replace(
            "本周期未发现符合纳入标准的事件",
            "本周期未发现符合纳入标准的研究\n\n## 来源",
        )
        self.target.write_text(scout, encoding="utf-8")
        before = (
            self.source.read_bytes(),
            self.target.read_bytes(),
            self.security.descriptor(self.target),
        )
        with self.assertRaises(archive.Blocked) as caught:
            archive.validate(
                self.source,
                self.target,
                self.target,
                "hit-weekly-brief",
                custom_filename=True,
            )
        self.assertEqual("COLLISION", caught.exception.code)
        self.assertEqual(
            before,
            (
                self.source.read_bytes(),
                self.target.read_bytes(),
                self.security.descriptor(self.target),
            ),
        )

    def test_legacy_title_identity_blocks_without_rewriting(self):
        self.target.write_text(
            CONTENT.replace("# 数字健康周报｜2000年1月3日—9日", "# 旧版标题"),
            encoding="utf-8",
        )
        before = self.target.read_bytes()
        with self.assertRaises(archive.Blocked) as caught:
            self.plan()
        self.assertEqual("COLLISION", caught.exception.code)
        self.assertEqual(before, self.target.read_bytes())

    def test_private_draft_acl_is_not_published(self):
        # Reproduce the elevated Administrators-owned private policy explicitly;
        # this host's mkdtemp may instead choose the current user as owner.
        policy = self.set_protected_fixture_policy(
            self.source, "O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)"
        )
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
        # A preserved OS-created DACL need not carry AUTO_INHERITED. Protect
        # either spelling rather than relying on a redundant setter to add AI.
        policy = self.set_protected_fixture_policy(
            self.target, original_policy.replace("D:", "D:P", 1)
        )
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
        lock = self.parent / (
            ".report-archive-"
            + archive.digest(self.target.name.lower().encode())[:24]
            + ".lock"
        )
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
        self.assertEqual(
            original, (Path(result["recovery_directory"]) / "original.md").read_bytes()
        )
        self.assertEqual("not_attempted_preserve_evidence", result["rollback"])

    def test_access_failure_precommit_retains_draft_no_target(self):
        plan = self.plan()
        with patch.object(
            self.security,
            "effective_access",
            side_effect=self.security.CapabilityError("injected denial"),
        ):
            result = archive.commit(plan, self.target)
        self.assertEqual("ACCESS_CHECK", result["code"])
        self.assertTrue(self.source.exists())
        self.assertFalse(self.target.exists())
        journal = json.loads(
            (Path(result["recovery_directory"]) / "journal.json").read_text(
                encoding="utf-8"
            )
        )
        candidate = Path(journal["candidate"])
        self.assertEqual(self.parent, candidate.parent)
        self.assertTrue(candidate.exists())
        self.assertEqual(self.source.read_bytes(), candidate.read_bytes())

    def test_postcommit_access_failure_preserves_original_and_can_recover_with_fresh_plan(
        self,
    ):
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
        recovery = archive.validate(
            backup, self.target, self.target, "hit-weekly-brief"
        )
        restored = archive.commit(recovery, self.target)
        self.assertEqual("COMMITTED", restored["status"], restored)
        self.assertEqual(original, self.target.read_bytes())
        self.assertEqual(
            plan["expected_target"]["security"], self.security.descriptor(self.target)
        )

    def test_identity_conflict_and_same_path_rejected(self):
        self.target.write_text(
            CONTENT.replace("2000-01-03 至", "1999-12-27 至"), encoding="utf-8"
        )
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
            archive.validate(
                self.source, self.target, self.parent / "another.md", "hit-weekly-brief"
            )
        result = archive.commit(self.plan(), self.parent / "another.md")
        self.assertEqual("INPUT", result["code"])
        self.assertFalse(self.target.exists())

    def test_cli_fresh_process_validate_commit_read_and_malformed_plan(self):
        script = Path(archive.__file__)

        def run(*args):
            return subprocess.run(
                [sys.executable, "-B", "-X", "utf8", str(script), *map(str, args)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )

        checked = run(
            "validate",
            "--source",
            self.source,
            "--target",
            self.target,
            "--allow-target",
            self.target,
            "--skill",
            "hit-weekly-brief",
        )
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        plan_file = self.draft_dir / "plan.json"
        plan_file.write_text(checked.stdout, encoding="utf-8")
        result = run("commit", "--plan", plan_file, "--allow-target", self.target)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("COMMITTED", json.loads(result.stdout)["status"])
        read = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "import pathlib,hashlib,sys;print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())",
                str(self.target),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(archive.digest(self.source.read_bytes()), read.stdout.strip())
        plan_file.write_text('{"schema":1,"schema":1}', encoding="utf-8")
        self.assertNotEqual(
            0,
            run(
                "commit", "--plan", plan_file, "--allow-target", self.target
            ).returncode,
        )


# Independent small oracle: fixed historical dates, no validator constants or news.
RADAR_CONTENT = """# 医疗行业雷达｜2000-01-03 至 2000-01-09
报告周期：2000-01-03 至 2000-01-09
出刊日期：2000-01-09
生成时点：2000-01-09T09:00:00+08:00
报告时区：Asia/Shanghai
窗口模式：explicit
报告范围：中国医疗 IT；合成采购
检索状态：complete

## 结论摘要
合成检索完成，没有可纳入事件；不代表全行业无事件。

## 关键事件
| 事件ID | 事件日期 | 发布日期 | 主体 | 已核实动作 | 事件键 | 证据强度 | 来源编号 | 影响（推断） | 限制 |
|---|---|---|---|---|---|---|---|---|---|
本周期未发现符合纳入标准的公开事件

## 检索覆盖
| 检索面 | 状态 | 查询/来源及结果说明 |
|---|---|---|
| 采购 | complete | 合成查询：指定窗口采购公告检索完成，仅旧事件，未纳入 |

## 来源
| 来源编号 | 原始链接 | 血缘 | 类型 | 访问状态 |
|---|---|---|---|---|

## 信息缺口
仅为合成采购面，不证明其他行业面已检索。
"""
RADAR_PARTIAL = (
    RADAR_CONTENT.replace("检索状态：complete", "检索状态：partial")
    .replace("本周期未发现符合纳入标准的公开事件", "覆盖不完整，暂无可纳入的已核实事件")
    .replace(
        "\n\n## 来源", "\n| 政策 | blocked | 合成政策来源超时，未获取证据 |\n\n## 来源"
    )
    .replace(
        "仅为合成采购面，不证明其他行业面已检索。",
        "政策面超时，不能判断政策事件；仅采购面检索完成。",
    )
)
RADAR_BLOCKED = (
    RADAR_CONTENT.replace("检索状态：complete", "检索状态：blocked")
    .replace("本周期未发现符合纳入标准的公开事件", "检索阻塞，不能判定本期事件")
    .replace(
        "| 采购 | complete | 合成查询：指定窗口采购公告检索完成，仅旧事件，未纳入 |",
        "| 采购 | blocked | 合成工具不可用，无检索证据 |",
    )
)


@unittest.skipUnless(os.name == "nt", "Windows native ACL publication only")
class ReportArchiveRadarWindowsTests(unittest.TestCase):
    def setUp(self):
        ReportArchiveWindowsTests.setUp(self)
        self.source.write_text(RADAR_CONTENT, encoding="utf-8")
        self.target = self.parent / "DHWB-Radar-20000109.md"

    def plan(self, custom_filename=False, custom_period=False):
        return archive.validate(
            self.source,
            self.target,
            self.target,
            "hit-industry-radar",
            custom_filename,
            custom_period,
        )

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", "-X", "utf8", archive.__file__, *map(str, args)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )

    def tree_snapshot(self):
        # Rejections must preserve all fixture bytes and security, with no candidate/lock left.
        return {
            str(p.relative_to(self.root)): (
                p.read_bytes() if p.is_file() else None,
                self.security.descriptor(p),
            )
            for p in [self.root, *self.root.rglob("*")]
        }

    def assert_rejected_unchanged(self, code="INPUT", **options):
        before = self.tree_snapshot()
        with self.assertRaises(archive.Blocked) as caught:
            self.plan(**options)
        self.assertEqual(code, caught.exception.code)
        self.assertEqual(before, self.tree_snapshot())

    def test_radar_fresh_cli_new_replace_partial_readback_hash_and_acl(self):
        policies = []
        for content in (RADAR_CONTENT, RADAR_PARTIAL):
            self.source.write_text(content, encoding="utf-8")
            before = self.tree_snapshot()
            checked = self.run_cli(
                "validate",
                "--source",
                self.source,
                "--target",
                self.target,
                "--allow-target",
                self.target,
                "--skill",
                "hit-industry-radar",
            )
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
            self.assertEqual(before, self.tree_snapshot())
            plan = json.loads(checked.stdout)
            self.assertEqual(
                {
                    "skill": "hit-industry-radar",
                    "period_start": "2000-01-03",
                    "period_end": "2000-01-09",
                    "issue_date": "2000-01-09",
                    "window_mode": "explicit",
                    "scope": "中国医疗 IT；合成采购",
                    "report_timezone": "Asia/Shanghai",
                },
                plan["identity"],
            )
            plan_file = self.draft_dir / "radar-plan.json"
            plan_file.write_text(checked.stdout, encoding="utf-8")
            committed = self.run_cli(
                "commit", "--plan", plan_file, "--allow-target", self.target
            )
            self.assertEqual(
                0, committed.returncode, committed.stdout + committed.stderr
            )
            receipt = json.loads(committed.stdout)
            self.assertEqual("COMMITTED", receipt["status"], receipt)
            self.assertEqual(self.source.read_bytes(), self.target.read_bytes())
            self.assertEqual(
                archive.digest(self.source.read_bytes()), receipt["sha256"]
            )
            self.assertEqual(
                "read/write/modify", receipt["security"]["limited_token_accesscheck"]
            )
            self.assertTrue(receipt["security"]["host_token_content_read"])
            self.assertIsInstance(receipt["security"]["actual_non_elevated_open"], bool)
            token, host_is_limited = self.security.limited_token()
            try:
                self.assertEqual(
                    host_is_limited, receipt["security"]["actual_non_elevated_open"]
                )
            finally:
                token.Close()
            policies.append(self.security.descriptor(self.target))
            self.assertEqual(policies[-1], receipt["security"]["descriptor"])
            if content == RADAR_PARTIAL:
                backup = Path(receipt["recovery_directory"]) / "original.md"
                self.assertEqual(RADAR_CONTENT, backup.read_text(encoding="utf-8"))
                self.assertEqual(policies[0], self.security.descriptor(backup))
            readback = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-X",
                    "utf8",
                    "-c",
                    "import sys,pathlib,hashlib,json;sys.path.insert(0,sys.argv[1]);"
                    "import report_archive_windows as w;p=pathlib.Path(sys.argv[2]);d=p.read_bytes();"
                    "print(json.dumps(dict(sha256=hashlib.sha256(d).hexdigest(),"
                    "title=d.decode('utf-8').splitlines()[0],descriptor=w.descriptor(p),"
                    "access=w.effective_access(p,d)),ensure_ascii=False))",
                    str(Path(archive.__file__).parent),
                    str(self.target),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            self.assertEqual(0, readback.returncode, readback.stdout + readback.stderr)
            evidence = json.loads(readback.stdout)
            self.assertEqual(receipt["sha256"], evidence["sha256"])
            self.assertEqual(
                "# 医疗行业雷达｜2000-01-03 至 2000-01-09", evidence["title"]
            )
            self.assertEqual(policies[-1], evidence["descriptor"])
            self.assertEqual(
                "read/write/modify", evidence["access"]["limited_token_accesscheck"]
            )
        self.assertEqual(policies[0], policies[1])
        s = self.security.security
        parent = s.ConvertStringSecurityDescriptorToSecurityDescriptor(
            self.security.descriptor(self.parent), 1
        )
        final = s.ConvertStringSecurityDescriptorToSecurityDescriptor(policies[0], 1)
        self.assertEqual(
            parent.GetSecurityDescriptorOwner(), final.GetSecurityDescriptorOwner()
        )
        self.assertEqual(
            parent.GetSecurityDescriptorGroup(), final.GetSecurityDescriptorGroup()
        )
        self.assertFalse(final.GetSecurityDescriptorControl()[0] & s.SE_DACL_PROTECTED)

    def test_radar_all_window_modes_use_radar_interface_and_period_end_name(self):
        for mode in ("rolling7", "natural_week", "explicit"):
            with self.subTest(mode=mode):
                self.source.write_text(
                    RADAR_CONTENT.replace("窗口模式：explicit", "窗口模式：" + mode),
                    encoding="utf-8",
                )
                before = self.tree_snapshot()
                self.assertEqual(mode, self.plan()["identity"]["window_mode"])
                self.assertEqual(before, self.tree_snapshot())
        self.target = self.parent / "DHWB-Radar-20000110.md"
        self.assert_rejected_unchanged()
        self.assertEqual(
            "2000-01-09", self.plan(custom_filename=True)["identity"]["issue_date"]
        )

    def test_radar_scope_whitespace_canonicalized_for_replacement(self):
        self.target.write_text(RADAR_CONTENT, encoding="utf-8")
        self.source.write_text(
            RADAR_CONTENT.replace(
                "报告范围：中国医疗 IT；合成采购",
                "报告范围： \t\u3000中国医疗 IT；合成采购\u3000\t ",
            ),
            encoding="utf-8",
        )
        result = archive.commit(self.plan(), self.target)
        self.assertEqual("COMMITTED", result["status"], result)
        self.assertEqual(self.source.read_bytes(), self.target.read_bytes())

    def test_radar_identity_collisions_even_with_custom_filename(self):
        variants = {
            "scope": RADAR_CONTENT.replace("中国医疗 IT；合成采购", "全球医疗 AI"),
            "period_start": RADAR_CONTENT.replace("2000-01-03", "2000-01-02"),
            "period_end": RADAR_CONTENT.replace("2000-01-09", "2000-01-08"),
            "mode": RADAR_CONTENT.replace("窗口模式：explicit", "窗口模式：rolling7"),
            "natural_mode": RADAR_CONTENT.replace(
                "窗口模式：explicit", "窗口模式：natural_week"
            ),
            "timezone": RADAR_CONTENT.replace(
                "报告时区：Asia/Shanghai", "报告时区：UTC"
            ),
            "weekly": CONTENT,
            "scout": CONTENT.replace(
                "# 数字健康周报｜2000年1月3日—9日",
                "# 医疗数字化文献侦察报告 - 2000-01-09",
            ).replace(
                "报告时区：Asia/Shanghai", "报告时区：Asia/Shanghai\n命名依据：explicit"
            ),
        }
        for custom in (False, True):
            self.target = self.parent / (
                "custom.md" if custom else "DHWB-Radar-20000109.md"
            )
            for name, content in variants.items():
                with self.subTest(custom=custom, conflict=name):
                    self.target.write_text(content, encoding="utf-8")
                    self.assert_rejected_unchanged("COLLISION", custom_filename=custom)
            self.target.unlink()

    def test_radar_legacy_ambiguous_or_invalid_target_metadata_fails_closed(self):
        headers = RADAR_CONTENT.splitlines()[1:8]
        variants = [RADAR_CONTENT.replace(line + "\n", "", 1) for line in headers]
        variants += [
            RADAR_CONTENT.replace(line, line + "\n" + line, 1) for line in headers
        ]
        variants += [
            RADAR_CONTENT.replace("检索状态：complete", "检索状态：success"),
            RADAR_CONTENT.replace("窗口模式：explicit", "窗口模式：generated"),
            RADAR_CONTENT.replace("报告时区：Asia/Shanghai", "报告时区：Not/AZone"),
            RADAR_CONTENT.replace("出刊日期：2000-01-09", "出刊日期：2000-01-08"),
            RADAR_CONTENT.replace(
                "报告范围：中国医疗 IT；合成采购", "报告范围：\u3000\t "
            ),
            RADAR_CONTENT.replace(
                "# 医疗行业雷达｜2000-01-03 至 2000-01-09", "# 旧标题"
            ),
            RADAR_CONTENT.replace(
                "窗口模式：explicit", "窗口模式：explicit\n命名依据：explicit"
            ),
        ]
        self.target = self.parent / "custom.md"
        for index, content in enumerate(variants):
            with self.subTest(variant=index):
                self.target.write_text(content, encoding="utf-8")
                self.assert_rejected_unchanged("COLLISION", custom_filename=True)

    def test_radar_empty_duplicate_source_metadata_rejected_unchanged(self):
        for custom in (False, True):
            self.target = self.parent / (
                "custom.md" if custom else "DHWB-Radar-20000109.md"
            )
            self.target.write_bytes(RADAR_CONTENT.encode("utf-8"))
            for line in RADAR_CONTENT.splitlines()[1:8]:
                label = line.split("：", 1)[0]
                for blank in ("", " \t\u3000"):
                    duplicate = label + "：" + blank
                    for first in (True, False):
                        replacement = (
                            duplicate + "\n" + line
                            if first
                            else line + "\n" + duplicate
                        )
                        for newline in ("\n", "\r\n"):
                            with self.subTest(
                                custom=custom,
                                label=label,
                                blank=repr(blank),
                                first=first,
                                newline=repr(newline),
                            ):
                                content = RADAR_CONTENT.replace(
                                    line, replacement, 1
                                ).replace("\n", newline)
                                self.source.write_bytes(content.encode("utf-8"))
                                self.assert_rejected_unchanged(
                                    "INPUT", custom_filename=custom
                                )
            self.target.unlink()

    def test_radar_empty_duplicate_target_metadata_collision_unchanged(self):
        for custom in (False, True):
            self.target = self.parent / (
                "custom.md" if custom else "DHWB-Radar-20000109.md"
            )
            for line in RADAR_CONTENT.splitlines()[1:8]:
                label = line.split("：", 1)[0]
                for blank in ("", " \t\u3000"):
                    duplicate = label + "：" + blank
                    for first in (True, False):
                        replacement = (
                            duplicate + "\n" + line
                            if first
                            else line + "\n" + duplicate
                        )
                        for newline in ("\n", "\r\n"):
                            with self.subTest(
                                custom=custom,
                                label=label,
                                blank=repr(blank),
                                first=first,
                                newline=repr(newline),
                            ):
                                content = RADAR_CONTENT.replace(
                                    line, replacement, 1
                                ).replace("\n", newline)
                                self.source.write_bytes(
                                    RADAR_CONTENT.replace("\n", newline).encode("utf-8")
                                )
                                self.target.write_bytes(content.encode("utf-8"))
                                self.assert_rejected_unchanged(
                                    "COLLISION", custom_filename=custom
                                )
            self.target.unlink()

    def test_radar_diagnostic_target_status_is_not_source_success_or_skill_identity(
        self,
    ):
        # Existing body is not migrated/revalidated; valid blocked metadata is
        # distinguishable from unknown status, and never makes a source publishable.
        self.target.write_text(RADAR_BLOCKED, encoding="utf-8")
        self.assertEqual("hit-industry-radar", self.plan()["identity"]["skill"])
        self.source.write_text(RADAR_BLOCKED, encoding="utf-8")
        self.assert_rejected_unchanged()
        self.target.write_text(
            RADAR_BLOCKED.replace(
                "# 医疗行业雷达｜2000-01-03 至 2000-01-09",
                "# 数字健康周报｜2000年1月3日—9日",
            ),
            encoding="utf-8",
        )
        self.source.write_text(RADAR_CONTENT, encoding="utf-8")
        self.assert_rejected_unchanged("COLLISION")

    def test_radar_blocked_and_partial_without_disclosed_gaps_rejected(self):
        variants = [
            RADAR_BLOCKED,
            RADAR_CONTENT.replace("检索状态：complete", "检索状态：partial"),
            RADAR_PARTIAL.replace(
                "政策面超时，不能判断政策事件；仅采购面检索完成。", ""
            ),
            RADAR_PARTIAL.replace("## 信息缺口", "## 其他"),
        ]
        for content in variants:
            with self.subTest(content=content.splitlines()[7]):
                self.source.write_text(content, encoding="utf-8")
                self.assert_rejected_unchanged()
        # Structural validator still allows the honest blocked diagnostic.
        self.source.write_text(RADAR_BLOCKED, encoding="utf-8")
        script = (
            Path(archive.__file__).resolve().parents[2]
            / "hit-industry-radar/scripts/validate_industry_radar.py"
        )
        checked = subprocess.run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                str(script),
                "--file",
                str(self.source),
                "--period-start",
                "2000-01-03",
                "--period-end",
                "2000-01-09",
                "--issue-date",
                "2000-01-09",
                "--cutoff",
                "2000-01-09T09:00:00+08:00",
                "--window-mode",
                "explicit",
                "--allow-custom-filename",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

    def test_radar_cli_rejects_custom_period_blocked_and_legacy_without_writes(self):
        for content, old, flags, code in (
            (RADAR_CONTENT, None, ["--allow-custom-period"], "INPUT"),
            (RADAR_BLOCKED, None, [], "INPUT"),
            (RADAR_CONTENT, "# legacy", [], "COLLISION"),
        ):
            self.source.write_text(content, encoding="utf-8")
            if old:
                self.target.write_text(old, encoding="utf-8")
            before = self.tree_snapshot()
            result = self.run_cli(
                "validate",
                "--source",
                self.source,
                "--target",
                self.target,
                "--allow-target",
                self.target,
                "--skill",
                "hit-industry-radar",
                *flags,
            )
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertEqual("BLOCKED", json.loads(result.stdout)["status"])
            self.assertEqual(code, json.loads(result.stdout)["code"])
            self.assertEqual(before, self.tree_snapshot())

    def test_radar_commit_rejects_custom_period_plan_misuse(self):
        plan = self.plan()
        plan["custom_period"] = True
        before = self.tree_snapshot()
        result = archive.commit(plan, self.target)
        self.assertEqual("BLOCKED", result["status"], result)
        self.assertEqual("INPUT", result["code"])
        self.assertEqual(before, self.tree_snapshot())

    def test_radar_source_target_and_semantic_plan_drift_no_unsafe_write(self):
        for drift in ("source", "target", "identity"):
            with self.subTest(drift=drift):
                self.source.write_text(RADAR_CONTENT, encoding="utf-8")
                self.target.write_text(RADAR_CONTENT, encoding="utf-8")
                plan = self.plan()
                if drift == "identity":
                    plan["identity"]["scope"] = "another scope"
                else:
                    path = self.source if drift == "source" else self.target
                    path.write_text(
                        RADAR_CONTENT + "\n修订：另一写者。\n", encoding="utf-8"
                    )
                before = self.tree_snapshot()
                result = archive.commit(plan, self.target)
                self.assertEqual("BLOCKED", result["status"], result)
                self.assertEqual("COLLISION", result["code"])
                self.assertEqual(before, self.tree_snapshot())

    def test_radar_missing_validator_or_backend_blocks_without_fallback(self):
        with patch.object(
            archive.importlib.util, "spec_from_file_location", return_value=None
        ):
            self.assert_rejected_unchanged("CAPABILITY")
        spec = archive.importlib.util.spec_from_file_location(
            "missing_radar_validator", self.root / "missing.py"
        )
        with patch.object(
            archive.importlib.util, "spec_from_file_location", return_value=spec
        ):
            self.assert_rejected_unchanged("CAPABILITY")
        with patch.object(
            archive,
            "backend",
            side_effect=archive.Blocked("CAPABILITY", "injected missing backend"),
        ):
            self.assert_rejected_unchanged("CAPABILITY")

    def test_radar_missing_target_parent_not_created(self):
        self.target = self.parent / "missing" / self.target.name
        self.assert_rejected_unchanged()

    def test_radar_cannot_overwrite_weekly_or_scout_in_reverse(self):
        self.target = self.parent / "custom.md"
        self.target.write_text(RADAR_CONTENT, encoding="utf-8")
        scout = (
            CONTENT.replace(
                "# 数字健康周报｜2000年1月3日—9日",
                "# 医疗数字化文献侦察报告 - 2000-01-09",
            )
            .replace(
                "报告时区：Asia/Shanghai", "报告时区：Asia/Shanghai\n命名依据：explicit"
            )
            .replace("## 关键事件与来源", "## 本期研究")
            .replace(
                "本周期未发现符合纳入标准的事件",
                "本周期未发现符合纳入标准的研究\n\n## 来源",
            )
        )
        for skill, content in (
            ("hit-weekly-brief", CONTENT),
            ("hit-lectures-scout", scout),
        ):
            with self.subTest(skill=skill):
                self.source.write_text(content, encoding="utf-8")
                before = self.tree_snapshot()
                with self.assertRaises(archive.Blocked) as caught:
                    archive.validate(
                        self.source,
                        self.target,
                        self.target,
                        skill,
                        custom_filename=True,
                    )
                self.assertEqual("COLLISION", caught.exception.code)
                self.assertEqual(before, self.tree_snapshot())


if __name__ == "__main__":
    unittest.main()
