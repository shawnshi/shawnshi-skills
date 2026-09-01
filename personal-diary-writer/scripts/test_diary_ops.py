import argparse
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("diary_ops.py")
SPEC = importlib.util.spec_from_file_location("diary_ops", MODULE_PATH)
assert SPEC is not None
diary_ops = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(diary_ops)


class DiaryOpsTests(unittest.TestCase):
    def test_portable_defaults_do_not_embed_a_machine_user(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("C:/Users/", source)
        with patch.dict(os.environ, {"TEST_DIARY_ROOT": "relative/path"}):
            with self.assertRaisesRegex(ValueError, "absolute path"):
                diary_ops._configured_path("TEST_DIARY_ROOT", Path.home())

    def _args(
        self,
        target,
        payload,
        receipt=None,
        approval=None,
        action="replace-date",
        week=None,
        month=None,
        quarter=None,
        day="2026-08-31",
    ):
        values = {
            "file": str(target),
            "date": day,
            "kind": "personal",
            "action": action,
            "week": week,
            "month": month,
            "quarter": quarter,
            "content_file": str(payload),
            "authorization_id": "auth-1",
        }
        if receipt is not None:
            values["scope_file"] = str(receipt)
        if approval is not None:
            values["approval_file"] = str(approval)
        return argparse.Namespace(**values)

    @contextmanager
    def _runtime(self, tmp):
        root = Path(tmp)
        session_root = root / "sessions"
        session_root.mkdir(parents=True)
        session = session_root / "session.jsonl"
        session.write_text("", encoding="utf-8")
        weekly_gate = root / "weekly_gate.py"
        weekly_gate.write_text("raise SystemExit(0)\n", encoding="utf-8")
        with (
            patch.object(diary_ops, "DEFAULT_ROOT", root),
            patch.object(diary_ops, "SESSION_ROOT", session_root),
            patch.object(diary_ops, "WEEKLY_GATE", weekly_gate),
            patch.dict(os.environ, {"PI_SESSION_FILE": str(session)}),
        ):
            yield

    def _personal_payload(self, day="2026-08-31"):
        sections = (
            "今日事项",
            "今日进展与证据",
            "判断与反思",
            "时间背景",
            "能量管理（描述性生理背景）",
            "明日事项",
            "风险与未知",
            "行动闭环",
        )
        return f"# {day} 星期一\n\n" + "\n\n".join(
            f"## {section}\n\n- 已生成内容。" for section in sections
        ) + "\n"

    def _artifacts(
        self,
        root,
        scope,
        source="user_confirmation",
        confirmation_text=None,
        request_text=None,
    ):
        receipt = root / "scope.json"
        receipt.write_text(json.dumps(scope, ensure_ascii=False), encoding="utf-8")
        evidence_id = "session-message-1"
        extra = {}
        if source == "user_confirmation":
            session = diary_ops.SESSION_ROOT / "session.jsonl"
            session.write_text(
                json.dumps(
                    {
                        "id": evidence_id,
                        "type": "message",
                        "timestamp": "2099-01-01T00:00:00Z",
                        "message": {
                            "role": "user",
                            "content": confirmation_text
                            or f"确认写入 {scope['authorization_scope_sha256']}",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        elif source == "personal_diary_request_gate":
            evidence_id = scope["source_sha256"]
            request_text = request_text or "更新个人日志"
            request_event_id = "request-message-1"
            session = diary_ops.SESSION_ROOT / "session.jsonl"
            session.write_text(
                json.dumps(
                    {
                        "id": request_event_id,
                        "type": "message",
                        "timestamp": "2026-08-31T12:00:00+08:00",
                        "message": {"role": "user", "content": request_text},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            extra.update(
                {
                    "request_artifact_schema": "personal-diary-request-v1",
                    "request_event_id": request_event_id,
                    "request_event_sha256": hashlib.sha256(
                        request_text.encode("utf-8")
                    ).hexdigest(),
                    "request_diary_date": scope["date"],
                    "request_kind": "personal",
                    "request_action": scope["action"],
                    "request_target": scope["target"],
                    "request_scope_sha256": scope[
                        "authorization_scope_sha256"
                    ],
                    "request_save_policy": "canonical_autosave",
                    "diary_payload_sha256": scope["source_sha256"],
                }
            )
        elif source in {
            "weekly_audit_gate",
            "monthly_audit_gate",
            "quarterly_audit_gate",
        }:
            evidence_id = scope["source_sha256"]
            extra["audit_payload_sha256"] = scope["source_sha256"]
            label = source.removesuffix("_audit_gate")
            period_id = scope[{"weekly": "week", "monthly": "month", "quarterly": "quarter"}[label]]
            request_text = "AUDIT_AUTOSAVE " + json.dumps(
                {
                    "period_id": period_id,
                    "period_type": label,
                    "save_policy": "canonical_autosave",
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            request_event_id = "request-message-1"
            session = diary_ops.SESSION_ROOT / "session.jsonl"
            session.write_text(
                json.dumps(
                    {
                        "id": request_event_id,
                        "type": "message",
                        "timestamp": "2026-08-31T12:00:00+08:00",
                        "message": {"role": "user", "content": request_text},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            extra.update(
                {
                    "request_artifact_schema": "periodic-audit-request-v1",
                    "request_event_id": request_event_id,
                    "request_event_sha256": hashlib.sha256(request_text.encode("utf-8")).hexdigest(),
                    "request_period_type": label,
                    "request_period_id": period_id,
                    "request_action": scope["action"],
                    "request_target": scope["target"],
                    "request_scope_sha256": scope["authorization_scope_sha256"],
                    "request_save_policy": "canonical_autosave",
                }
            )
        approval = root / "approval.json"
        approval.write_text(
            json.dumps(
                {
                    "schema": "diary-write-approval-v1",
                    "status": "confirmed",
                    "approval_source": source,
                    "approval_evidence_id": evidence_id,
                    "authorization_id": scope["authorization_id"],
                    "authorization_scope_sha256": scope[
                        "authorization_scope_sha256"
                    ],
                    **extra,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return receipt, approval

    def test_exact_personal_diary_request_autosaves_after_generation(self):
        for request_text in ("更新个人日志", "[OVERRIDE]更新个人日志"):
            with self.subTest(request=request_text), tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
                root = Path(tmp)
                target = root / "2026-Q3.md"
                target.write_text("# 2026-08-30\n\n历史内容\n", encoding="utf-8")
                payload = root / "personal.md"
                payload.write_text(self._personal_payload(), encoding="utf-8")
                scope = diary_ops.build_scope(
                    self._args(target, payload, action="replace-personal-diary")
                )
                receipt, approval = self._artifacts(
                    root,
                    scope,
                    "personal_diary_request_gate",
                    request_text=request_text,
                )
                result = diary_ops.replace_operation(
                    self._args(
                        target,
                        payload,
                        receipt,
                        approval,
                        action="replace-personal-diary",
                    )
                )
                self.assertEqual(result["status"], "success")
                self.assertIn("## 行动闭环", target.read_text(encoding="utf-8"))

    def test_modified_or_nonexact_personal_diary_request_is_not_writable(self):
        requests = (
            "[OVERRIDE]修改技能，“更新个人日志”在生成后自动保存",
            " 更新个人日志 ",
            "[OVERRIDE] 更新个人日志",
            "[OVERRIDE][WARROOM]更新个人日志",
            "更新个人日志\n",
        )
        for request_text in requests:
            with self.subTest(request=request_text), tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
                root = Path(tmp)
                target = root / "2026-Q3.md"
                target.write_text("# 2026-08-30\n\n历史内容\n", encoding="utf-8")
                payload = root / "personal.md"
                payload.write_text(self._personal_payload(), encoding="utf-8")
                scope = diary_ops.build_scope(
                    self._args(target, payload, action="replace-personal-diary")
                )
                receipt, approval = self._artifacts(
                    root,
                    scope,
                    "personal_diary_request_gate",
                    request_text=request_text,
                )
                with self.assertRaisesRegex(
                    diary_ops.DiaryError, "exact protected request"
                ):
                    diary_ops.replace_operation(
                        self._args(
                            target,
                            payload,
                            receipt,
                            approval,
                            action="replace-personal-diary",
                        )
                    )

    def test_personal_diary_request_cannot_cross_dates_or_drift_scope(self):
        for mutation in ("event_date", "event_timezone", "request_scope"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
                root = Path(tmp)
                target = root / "2026-Q3.md"
                target.write_text("# 2026-08-30\n\n历史内容\n", encoding="utf-8")
                payload = root / "personal.md"
                payload.write_text(self._personal_payload(), encoding="utf-8")
                scope = diary_ops.build_scope(
                    self._args(target, payload, action="replace-personal-diary")
                )
                receipt, approval = self._artifacts(
                    root, scope, "personal_diary_request_gate"
                )
                if mutation in {"event_date", "event_timezone"}:
                    session = diary_ops.SESSION_ROOT / "session.jsonl"
                    event = json.loads(session.read_text(encoding="utf-8"))
                    event["timestamp"] = (
                        "2026-09-01T12:00:00+08:00"
                        if mutation == "event_date"
                        else "2026-08-31T12:00:00"
                    )
                    session.write_text(
                        json.dumps(event, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
                    expected = "request date" if mutation == "event_date" else "timezone"
                else:
                    value = json.loads(approval.read_text(encoding="utf-8"))
                    value["request_scope_sha256"] = "0" * 64
                    approval.write_text(json.dumps(value), encoding="utf-8")
                    expected = "not bound to the write scope"
                with self.assertRaisesRegex(diary_ops.DiaryError, expected):
                    diary_ops.replace_operation(
                        self._args(
                            target,
                            payload,
                            receipt,
                            approval,
                            action="replace-personal-diary",
                        )
                    )

    def test_personal_diary_autosave_rejects_incomplete_generated_payload(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-30\n\n历史内容\n", encoding="utf-8")
            payload = root / "personal.md"
            payload.write_text(
                "# 2026-08-31 星期一\n\n## 今日事项\n\n- 只有一个章节。\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(diary_ops.DiaryError, "eight required H2"):
                diary_ops.build_scope(
                    self._args(target, payload, action="replace-personal-diary")
                )

    def test_scope_requires_independent_confirmation_before_atomic_insert(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text(
                "# 2026-08-30 星期日\r\n\r\n旧内容\r\n", encoding="utf-8", newline=""
            )
            payload = root / "payload.md"
            payload.write_text(
                "# 2026-08-31 星期一\n\n## 今日工作\n\n- 新内容\n",
                encoding="utf-8",
            )
            scope = diary_ops.build_scope(self._args(target, payload))
            self.assertEqual(scope["status"], "awaiting_confirmation")
            receipt, approval = self._artifacts(root, scope)

            result = diary_ops.replace_operation(
                self._args(target, payload, receipt, approval)
            )
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["approval_source"], "user_confirmation")
            text = target.read_text(encoding="utf-8")
            self.assertIn("# 2026-08-31 星期一", text)
            self.assertIn("# 2026-08-30 星期日", text)
            self.assertLess(text.index("2026-08-31"), text.index("2026-08-30"))
            self.assertFalse(target.with_name(target.name + ".lock").exists())

    def test_existing_date_is_replaced_without_changing_neighbors(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            before = (
                "# 2026-09-01\n\n未来\n\n"
                "# 2026-08-31\n\n旧日记\n\n"
                "# 2026-08-30\n\n历史\n"
            )
            target.write_text(before, encoding="utf-8")
            payload = root / "payload.md"
            payload.write_text("# 2026-08-31\n\n新日记\n", encoding="utf-8")
            scope = diary_ops.build_scope(self._args(target, payload))
            receipt, approval = self._artifacts(root, scope)
            diary_ops.replace_operation(self._args(target, payload, receipt, approval))
            after = target.read_text(encoding="utf-8")
            self.assertIn("# 2026-09-01\n\n未来", after)
            self.assertIn("# 2026-08-30\n\n历史", after)
            self.assertNotIn("旧日记", after)
            self.assertEqual(after.count("# 2026-08-31"), 1)

    def test_changed_payload_is_rejected_after_scope(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-30\n\n旧内容\n", encoding="utf-8")
            payload = root / "payload.md"
            payload.write_text("# 2026-08-31\n\n原内容\n", encoding="utf-8")
            scope = diary_ops.build_scope(self._args(target, payload))
            receipt, approval = self._artifacts(root, scope)
            payload.write_text("# 2026-08-31\n\n已变化\n", encoding="utf-8")
            with self.assertRaisesRegex(diary_ops.DiaryError, "scope receipt"):
                diary_ops.replace_operation(
                    self._args(target, payload, receipt, approval)
                )

    def test_changed_target_is_rejected_after_scope(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-30\n\n旧内容\n", encoding="utf-8")
            payload = root / "payload.md"
            payload.write_text("# 2026-08-31\n\n内容\n", encoding="utf-8")
            scope = diary_ops.build_scope(self._args(target, payload))
            receipt, approval = self._artifacts(root, scope)
            target.write_text("# 2026-08-30\n\n并发变化\n", encoding="utf-8")
            with self.assertRaisesRegex(diary_ops.DiaryError, "scope receipt"):
                diary_ops.replace_operation(
                    self._args(target, payload, receipt, approval)
                )

    def test_unconfirmed_or_mismatched_approval_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-30\n\n旧内容\n", encoding="utf-8")
            payload = root / "payload.md"
            payload.write_text("# 2026-08-31\n\n内容\n", encoding="utf-8")
            scope = diary_ops.build_scope(self._args(target, payload))
            receipt, approval = self._artifacts(root, scope)
            value = json.loads(approval.read_text(encoding="utf-8"))
            value["authorization_scope_sha256"] = "0" * 64
            approval.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(diary_ops.DiaryError, "not bound"):
                diary_ops.replace_operation(
                    self._args(target, payload, receipt, approval)
                )

    def test_noncanonical_target_and_malformed_file_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            payload = root / "payload.md"
            payload.write_text("# 2026-08-31\n\n内容\n", encoding="utf-8")
            with self.assertRaisesRegex(diary_ops.DiaryError, "not canonical"):
                diary_ops.build_scope(self._args(root / "wrong.md", payload))
            target = root / "2026-Q3.md"
            target.write_text("没有日期标题\n", encoding="utf-8")
            with self.assertRaisesRegex(diary_ops.DiaryError, "no recognizable"):
                diary_ops.build_scope(self._args(target, payload))

    def test_duplicate_date_heading_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text(
                "# 2026-08-31\n\n一\n\n# 2026-08-31\n\n二\n", encoding="utf-8"
            )
            payload = root / "payload.md"
            payload.write_text("# 2026-08-31\n\n内容\n", encoding="utf-8")
            with self.assertRaisesRegex(diary_ops.DiaryError, "duplicate"):
                diary_ops.build_scope(self._args(target, payload))

    def test_bom_and_crlf_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_bytes(b"\xef\xbb\xbf" + "# 2026-08-30\r\n\r\n历史\r\n".encode("utf-8"))
            payload = root / "payload.md"
            payload.write_text("# 2026-08-31\n\n内容\n", encoding="utf-8")
            scope = diary_ops.build_scope(self._args(target, payload))
            receipt, approval = self._artifacts(root, scope)
            diary_ops.replace_operation(self._args(target, payload, receipt, approval))
            raw = target.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertIn(b"\r\n", raw)

    def test_existing_lock_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-30\n\n历史\n", encoding="utf-8")
            payload = root / "payload.md"
            payload.write_text("# 2026-08-31\n\n内容\n", encoding="utf-8")
            scope = diary_ops.build_scope(self._args(target, payload))
            receipt, approval = self._artifacts(root, scope)
            target.with_name(target.name + ".lock").write_text("other\n")
            with self.assertRaisesRegex(diary_ops.DiaryError, "locked"):
                diary_ops.replace_operation(
                    self._args(target, payload, receipt, approval)
                )

    def test_weekly_audit_replaces_only_matching_subsection(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text(
                "# 2026-08-30 星期日\n\n## 今日工作\n\n- 保留\n\n"
                "## [2026-W35] Weekly Cognitive Audit｜旧\n\n旧审计\n\n"
                "## 尾部\n\n- 也保留\n\n# 2026-08-29\n\n历史\n",
                encoding="utf-8",
            )
            payload = root / "weekly.md"
            payload.write_text(
                "## [2026-W35] Weekly Cognitive Audit｜新\n\n新审计\n",
                encoding="utf-8",
            )
            args = self._args(
                target,
                payload,
                action="replace-weekly-audit",
                week="2026-W35",
                day="2026-08-30",
            )
            scope = diary_ops.build_scope(args)
            receipt, approval = self._artifacts(root, scope, "weekly_audit_gate")
            result = diary_ops.replace_operation(
                self._args(
                    target,
                    payload,
                    receipt,
                    approval,
                    action="replace-weekly-audit",
                    week="2026-W35",
                    day="2026-08-30",
                )
            )
            text = target.read_text(encoding="utf-8")
            self.assertEqual(result["period_heading_count"], 1)
            self.assertIn("- 保留", text)
            self.assertIn("- 也保留", text)
            self.assertIn("# 2026-08-29\n\n历史", text)
            self.assertIn("新审计", text)
            self.assertNotIn("旧审计", text)

    def test_monthly_and_quarterly_audits_replace_only_matching_subsection(self):
        cases = (
            (
                "replace-monthly-audit",
                "month",
                "2026-08",
                "2026-08-31",
                "## [2026-08] Monthly Cognitive Audit",
                "monthly_audit_gate",
            ),
            (
                "replace-quarterly-audit",
                "quarter",
                "2026-Q3",
                "2026-09-30",
                "## [2026-Q3] Quarterly Cognitive Audit",
                "quarterly_audit_gate",
            ),
        )
        for action, period_field, period_id, day, heading, source in cases:
            with self.subTest(action=action), tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
                root = Path(tmp)
                target = root / "2026-Q3.md"
                target.write_text(
                    f"# {day}\n\n## 今日工作\n\n- 保留\n\n"
                    f"{heading}｜旧\n\n### 旧内容\n\n旧审计\n\n"
                    "## [2026-W35] Weekly Cognitive Audit｜保留\n\n周审计\n\n"
                    "## 尾部\n\n- 也保留\n",
                    encoding="utf-8",
                )
                payload = root / f"{period_field}.md"
                payload.write_text(
                    f"{heading}｜新\n\n### 新内容\n\n新审计\n",
                    encoding="utf-8",
                )
                period_args = {period_field: period_id}
                args = self._args(target, payload, action=action, day=day, **period_args)
                scope = diary_ops.build_scope(args)
                receipt, approval = self._artifacts(root, scope, source)
                result = diary_ops.replace_operation(
                    self._args(
                        target,
                        payload,
                        receipt,
                        approval,
                        action=action,
                        day=day,
                        **period_args,
                    )
                )
                text = target.read_text(encoding="utf-8")
                self.assertEqual(result["period_heading_count"], 1)
                self.assertEqual(result["approval_source"], source)
                self.assertIn("- 保留", text)
                self.assertIn("- 也保留", text)
                self.assertIn("周审计", text)
                self.assertIn("新审计", text)
                self.assertNotIn("旧审计", text)

    def test_periodic_audit_creates_missing_period_end_date_without_changing_history(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            history = "# 2026-08-30\n\n历史内容\n"
            target.write_text(history, encoding="utf-8")
            payload = root / "monthly.md"
            payload.write_text(
                "## [2026-08] Monthly Cognitive Audit\n\n### 关键事实\n\n月度审计\n",
                encoding="utf-8",
            )
            args = self._args(
                target,
                payload,
                action="replace-monthly-audit",
                month="2026-08",
                day="2026-08-31",
            )
            scope = diary_ops.build_scope(args)
            receipt, approval = self._artifacts(root, scope, "monthly_audit_gate")
            result = diary_ops.replace_operation(
                self._args(
                    target,
                    payload,
                    receipt,
                    approval,
                    action="replace-monthly-audit",
                    month="2026-08",
                    day="2026-08-31",
                )
            )
            text = target.read_text(encoding="utf-8")
            self.assertEqual(result["date_heading_count"], 1)
            self.assertEqual(result["period_heading_count"], 1)
            self.assertIn("# 2026-08-31\n\n## [2026-08]", text)
            self.assertIn(history.rstrip(), text)

    def test_periodic_payload_rejects_all_extra_h2_forms_when_date_is_missing(self):
        payloads = (
            "## [2026-08] Monthly Cognitive Audit\n\n## 非目标区块\n\n不得写入\n",
            "## [2026-08] Monthly Cognitive Audit\n\n   ## 缩进非目标区块\n\n不得写入\n",
            "## [2026-08] Monthly Cognitive Audit\n\nSetext 非目标区块\n---\n",
            "## [2026-08] Monthly Cognitive Audit\n\nSetext 一级区块\n===\n",
        )
        for payload_text in payloads:
            with self.subTest(payload=payload_text), tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
                root = Path(tmp)
                target = root / "2026-Q3.md"
                target.write_text("# 2026-08-30\n\n历史内容\n", encoding="utf-8")
                payload = root / "monthly.md"
                payload.write_text(payload_text, encoding="utf-8")
                with self.assertRaisesRegex(diary_ops.DiaryError, "topology gate"):
                    diary_ops.build_scope(
                        self._args(
                            target,
                            payload,
                            action="replace-monthly-audit",
                            month="2026-08",
                            day="2026-08-31",
                        )
                    )

    def test_exact_current_period_alias_is_accepted_from_protected_user_event(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-30\n\n历史内容\n", encoding="utf-8")
            payload = root / "monthly.md"
            payload.write_text(
                "## [2026-08] Monthly Cognitive Audit\n\n### 关键事实\n\n月度审计\n",
                encoding="utf-8",
            )
            args = self._args(
                target,
                payload,
                action="replace-monthly-audit",
                month="2026-08",
                day="2026-08-31",
            )
            scope = diary_ops.build_scope(args)
            receipt, approval = self._artifacts(root, scope, "monthly_audit_gate")
            request_text = "[OVERRIDE]本月个人日志审计"
            session = diary_ops.SESSION_ROOT / "session.jsonl"
            session.write_text(
                json.dumps(
                    {
                        "id": "request-message-1",
                        "type": "message",
                        "timestamp": "2026-08-31T12:00:00+08:00",
                        "message": {"role": "user", "content": request_text},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            approval_value = json.loads(approval.read_text(encoding="utf-8"))
            approval_value["request_event_sha256"] = hashlib.sha256(
                request_text.encode("utf-8")
            ).hexdigest()
            approval.write_text(json.dumps(approval_value), encoding="utf-8")

            result = diary_ops.replace_operation(
                self._args(
                    target,
                    payload,
                    receipt,
                    approval,
                    action="replace-monthly-audit",
                    month="2026-08",
                    day="2026-08-31",
                )
            )
            self.assertEqual(result["status"], "success")

    def test_current_period_alias_cannot_authorize_a_different_period(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-30\n\n历史内容\n", encoding="utf-8")
            payload = root / "monthly.md"
            payload.write_text(
                "## [2026-08] Monthly Cognitive Audit\n\n### 关键事实\n\n月度审计\n",
                encoding="utf-8",
            )
            args = self._args(
                target,
                payload,
                action="replace-monthly-audit",
                month="2026-08",
                day="2026-08-31",
            )
            scope = diary_ops.build_scope(args)
            receipt, approval = self._artifacts(root, scope, "monthly_audit_gate")
            request_text = "本月个人日志审计"
            session = diary_ops.SESSION_ROOT / "session.jsonl"
            session.write_text(
                json.dumps(
                    {
                        "id": "request-message-1",
                        "type": "message",
                        "timestamp": "2026-09-01T12:00:00+08:00",
                        "message": {"role": "user", "content": request_text},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            approval_value = json.loads(approval.read_text(encoding="utf-8"))
            approval_value["request_event_sha256"] = hashlib.sha256(
                request_text.encode("utf-8")
            ).hexdigest()
            approval.write_text(json.dumps(approval_value), encoding="utf-8")
            with self.assertRaisesRegex(diary_ops.DiaryError, "not writable"):
                diary_ops.replace_operation(
                    self._args(
                        target,
                        payload,
                        receipt,
                        approval,
                        action="replace-monthly-audit",
                        month="2026-08",
                        day="2026-08-31",
                    )
                )

    def test_periodic_preview_request_is_rejected_even_with_matching_event_hash(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            original = "# 2026-08-30\n\n历史内容\n"
            target.write_text(original, encoding="utf-8")
            payload = root / "monthly.md"
            payload.write_text(
                "## [2026-08] Monthly Cognitive Audit\n\n### 关键事实\n\n月度审计\n",
                encoding="utf-8",
            )
            args = self._args(
                target,
                payload,
                action="replace-monthly-audit",
                month="2026-08",
                day="2026-08-31",
            )
            scope = diary_ops.build_scope(args)
            receipt, approval = self._artifacts(root, scope, "monthly_audit_gate")
            preview_text = "只预览本月个人日志审计"
            session = diary_ops.SESSION_ROOT / "session.jsonl"
            session.write_text(
                json.dumps(
                    {
                        "id": "request-message-1",
                        "type": "message",
                        "timestamp": "2026-08-31T12:00:00+08:00",
                        "message": {"role": "user", "content": preview_text},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            approval_value = json.loads(approval.read_text(encoding="utf-8"))
            approval_value["request_event_sha256"] = hashlib.sha256(
                preview_text.encode("utf-8")
            ).hexdigest()
            approval.write_text(json.dumps(approval_value), encoding="utf-8")
            with self.assertRaisesRegex(diary_ops.DiaryError, "not writable"):
                diary_ops.replace_operation(
                    self._args(
                        target,
                        payload,
                        receipt,
                        approval,
                        action="replace-monthly-audit",
                        month="2026-08",
                        day="2026-08-31",
                    )
                )
            self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_periodic_request_artifact_must_bind_target_action_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-30\n\n历史内容\n", encoding="utf-8")
            payload = root / "monthly.md"
            payload.write_text(
                "## [2026-08] Monthly Cognitive Audit\n\n### 关键事实\n\n月度审计\n",
                encoding="utf-8",
            )
            args = self._args(
                target,
                payload,
                action="replace-monthly-audit",
                month="2026-08",
                day="2026-08-31",
            )
            scope = diary_ops.build_scope(args)
            receipt, approval = self._artifacts(root, scope, "monthly_audit_gate")
            for key, bad_value in (
                ("request_target", "c:/wrong.md"),
                ("request_action", "replace-date"),
                ("request_scope_sha256", "0" * 64),
                ("request_save_policy", "preview"),
            ):
                with self.subTest(key=key):
                    value = json.loads(approval.read_text(encoding="utf-8"))
                    original = value[key]
                    value[key] = bad_value
                    approval.write_text(json.dumps(value), encoding="utf-8")
                    with self.assertRaisesRegex(diary_ops.DiaryError, "not bound"):
                        diary_ops.replace_operation(
                            self._args(
                                target,
                                payload,
                                receipt,
                                approval,
                                action="replace-monthly-audit",
                                month="2026-08",
                                day="2026-08-31",
                            )
                        )
                    value[key] = original
                    approval.write_text(json.dumps(value), encoding="utf-8")

    def test_atomic_replace_failure_removes_private_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            original = "# 2026-08-30\n\n历史内容\n"
            target.write_text(original, encoding="utf-8")
            payload = root / "payload.md"
            payload.write_text("# 2026-08-31\n\n新内容\n", encoding="utf-8")
            scope = diary_ops.build_scope(self._args(target, payload))
            receipt, approval = self._artifacts(root, scope)
            with patch.object(diary_ops.os, "replace", side_effect=OSError("blocked")):
                with self.assertRaisesRegex(OSError, "blocked"):
                    diary_ops.replace_operation(
                        self._args(target, payload, receipt, approval)
                    )
            self.assertEqual(target.read_text(encoding="utf-8"), original)
            self.assertEqual(list(root.glob(target.name + ".*.tmp")), [])
            self.assertFalse(target.with_name(target.name + ".lock").exists())

    def test_gate_runs_on_snapshot_and_source_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-30\n\n日记\n", encoding="utf-8")
            payload = root / "weekly.md"
            original = "## [2026-W35] Weekly Cognitive Audit\n\n原审计\n"
            payload.write_text(original, encoding="utf-8")
            args = self._args(
                target,
                payload,
                action="replace-weekly-audit",
                week="2026-W35",
                day="2026-08-30",
            )
            scope = diary_ops.build_scope(args)
            receipt, approval = self._artifacts(root, scope, "weekly_audit_gate")
            observed = root / "observed.txt"
            gate = root / "mutating_gate.py"
            gate.write_text(
                "import hashlib, pathlib, sys\n"
                f"original=pathlib.Path({str(payload)!r})\n"
                f"observed=pathlib.Path({str(observed)!r})\n"
                "snapshot=pathlib.Path(sys.argv[1])\n"
                "data=snapshot.read_bytes()\n"
                "observed.write_text(str(snapshot)+'\\n'+hashlib.sha256(data).hexdigest(), encoding='utf-8')\n"
                "original.write_text('## [2026-W35] Weekly Cognitive Audit\\n\\n并发变化\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            with patch.object(diary_ops, "WEEKLY_GATE", gate):
                with self.assertRaisesRegex(diary_ops.DiaryError, "scope receipt"):
                    diary_ops.replace_operation(
                        self._args(
                            target,
                            payload,
                            receipt,
                            approval,
                            action="replace-weekly-audit",
                            week="2026-W35",
                            day="2026-08-30",
                        )
                    )
            snapshot_path, snapshot_sha = observed.read_text(encoding="utf-8").splitlines()
            self.assertNotEqual(Path(snapshot_path), payload)
            self.assertEqual(snapshot_sha, scope["source_sha256"])
            self.assertNotIn("并发变化", target.read_text(encoding="utf-8"))

    def test_generic_or_replayed_confirmation_cannot_approve_new_scope(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-30\n\n历史\n", encoding="utf-8")
            payload = root / "payload.md"
            payload.write_text("# 2026-08-31\n\n内容\n", encoding="utf-8")
            first_scope = diary_ops.build_scope(self._args(target, payload))
            second_scope = diary_ops.build_scope(self._args(target, payload))
            self.assertNotEqual(
                first_scope["authorization_scope_sha256"],
                second_scope["authorization_scope_sha256"],
            )
            receipt, approval = self._artifacts(
                root,
                second_scope,
                confirmation_text=f"确认写入 {first_scope['authorization_scope_sha256']}",
            )
            with self.assertRaisesRegex(diary_ops.DiaryError, "not bound"):
                diary_ops.replace_operation(
                    self._args(target, payload, receipt, approval)
                )
            receipt, approval = self._artifacts(
                root, second_scope, confirmation_text="确认写入"
            )
            with self.assertRaisesRegex(diary_ops.DiaryError, "not bound"):
                diary_ops.replace_operation(
                    self._args(target, payload, receipt, approval)
                )

    def test_approval_source_matrix_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-30\n\n历史\n", encoding="utf-8")
            payload = root / "payload.md"
            payload.write_text("# 2026-08-31\n\n内容\n", encoding="utf-8")
            scope = diary_ops.build_scope(self._args(target, payload))
            receipt, approval = self._artifacts(root, scope)
            value = json.loads(approval.read_text(encoding="utf-8"))
            value["approval_source"] = "mentat_evidence_gate"
            approval.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(diary_ops.DiaryError, "operation matrix"):
                diary_ops.replace_operation(
                    self._args(target, payload, receipt, approval)
                )

    def test_weekly_audit_requires_period_end_and_personal_kind(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-31\n\n日记\n", encoding="utf-8")
            payload = root / "weekly.md"
            payload.write_text(
                "## [2026-W35] Weekly Cognitive Audit\n\n审计\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(diary_ops.DiaryError, "period end"):
                diary_ops.build_scope(
                    self._args(
                        target,
                        payload,
                        action="replace-weekly-audit",
                        week="2026-W35",
                    )
                )
            with self.assertRaisesRegex(diary_ops.DiaryError, "unauthorized"):
                diary_ops._validate_matrix(
                    date.fromisoformat("2026-08-30"),
                    "mentat",
                    "replace-weekly-audit",
                    "2026-W35",
                    None,
                    None,
                )

    def test_monthly_and_quarterly_audits_require_exact_period_end(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-30\n\n日记\n", encoding="utf-8")
            monthly = root / "monthly.md"
            monthly.write_text(
                "## [2026-08] Monthly Cognitive Audit\n\n### 事实\n\n审计\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(diary_ops.DiaryError, "period end"):
                diary_ops.build_scope(
                    self._args(
                        target,
                        monthly,
                        action="replace-monthly-audit",
                        month="2026-08",
                        day="2026-08-30",
                    )
                )
            quarterly = root / "quarterly.md"
            quarterly.write_text(
                "## [2026-Q3] Quarterly Cognitive Audit\n\n### 事实\n\n审计\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(diary_ops.DiaryError, "period end"):
                diary_ops.build_scope(
                    self._args(
                        target,
                        quarterly,
                        action="replace-quarterly-audit",
                        quarter="2026-Q3",
                        day="2026-09-29",
                    )
                )

    def test_noncanonical_path_creates_no_parent_or_lock(self):
        with tempfile.TemporaryDirectory() as tmp, self._runtime(tmp):
            root = Path(tmp)
            target = root / "2026-Q3.md"
            target.write_text("# 2026-08-30\n\n历史\n", encoding="utf-8")
            payload = root / "payload.md"
            payload.write_text("# 2026-08-31\n\n内容\n", encoding="utf-8")
            scope = diary_ops.build_scope(self._args(target, payload))
            receipt, approval = self._artifacts(root, scope)
            wrong = root / "outside" / "wrong.md"
            with self.assertRaisesRegex(diary_ops.DiaryError, "not canonical"):
                diary_ops.replace_operation(
                    self._args(wrong, payload, receipt, approval)
                )
            self.assertFalse(wrong.parent.exists())


if __name__ == "__main__":
    unittest.main()
