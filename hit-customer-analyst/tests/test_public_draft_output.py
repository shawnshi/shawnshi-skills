from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.common import SCRIPTS, SKILL_ROOT


SCRIPT = SCRIPTS / "validate_public_draft.py"
VALID_DRAFT = """执行档：公开资料内部草稿
ready_for_use：false
external_use：false
release_eligible：false
证据截止时间：2026-08-27T15:30:00+08:00
可用范围：内部讨论和人工复核；不得直接外发或写回业务系统

# 示例医院会前速览

## 公开来源支持、待人工复核
- 官网公开信息显示该院正在推进信息化建设。[机构官网](https://www.example.gov.cn/news/2026/item.html)

## 推断与建议
- 建议现场确认本年度建设优先级。

## 待人工复核
- 采购阶段与会议对象尚待确认。

## 下一步
- 由客户负责人在拜访中确认优先场景。
"""


def _run(candidate: str) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPT)],
        cwd=SKILL_ROOT,
        input=candidate,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    return result, json.loads(result.stdout)


def _insert_trace(trace: str) -> str:
    return VALID_DRAFT.replace(
        "- 官网公开信息显示",
        f"- {trace}\n- 官网公开信息显示",
        1,
    )


class PublicDraftOutputTests(unittest.TestCase):
    def test_valid_public_draft_is_deliverable_but_never_formal_or_ready(self):
        result, payload = _run(VALID_DRAFT)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertTrue(payload["valid"])
        self.assertTrue(payload["delivery_allowed"])
        self.assertEqual(payload["delivery_scope"], "conversation_internal_draft")
        self.assertFalse(payload["formal_authorized"])
        self.assertFalse(payload["ready_for_use"])
        self.assertFalse(payload["external_use"])
        self.assertFalse(payload["release_eligible"])
        self.assertEqual(payload["error_codes"], [])
        self.assertNotIn("示例医院", result.stdout)

    def test_validator_creates_no_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPT)],
                cwd=temporary,
                input=VALID_DRAFT,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_watermark_state_and_timezone_fail_closed(self):
        cases = {
            "moved_watermark": "说明\n" + VALID_DRAFT,
            "ready_true": VALID_DRAFT.replace("ready_for_use：false", "ready_for_use：true"),
            "external_true": VALID_DRAFT.replace("external_use：false", "external_use：true"),
            "release_true": VALID_DRAFT.replace(
                "release_eligible：false", "release_eligible：true"
            ),
            "duplicate_ready": VALID_DRAFT + "\nready_for_use：false\n",
            "inline_ready_override": VALID_DRAFT.replace(
                "- 建议现场确认本年度建设优先级。",
                "- 建议现场确认本年度建设优先级；ready_for_use=true。",
            ),
            "timezone_missing": VALID_DRAFT.replace(
                "2026-08-27T15:30:00+08:00", "2026-08-27T15:30:00"
            ),
            "non_rfc3339_separator": VALID_DRAFT.replace(
                "2026-08-27T15:30:00+08:00", "2026-08-27 15:30:00+08:00"
            ),
        }
        for name, candidate in cases.items():
            with self.subTest(name=name):
                result, payload = _run(candidate)
                self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
                self.assertFalse(payload["valid"])
                self.assertFalse(payload["delivery_allowed"])

    def test_old_verified_facts_heading_is_rejected(self):
        candidate = VALID_DRAFT.replace(
            "## 公开来源支持、待人工复核",
            "## 已核实事实",
        )
        result, payload = _run(candidate)
        self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
        self.assertIn("obsolete_verified_facts_heading_forbidden", payload["error_codes"])
        self.assertIn(
            "required_section_public_sources_pending_review_must_appear_once",
            payload["error_codes"],
        )

    def test_formal_identifiers_and_artifacts_are_rejected(self):
        traces = (
            "正式主张 CLM-I-001",
            "正式来源 SRC-I-001",
            "证据等级 F/F2",
            "context_id：ctx-001",
            "candidate-seal-request.json",
            "全角标识 ＣＬＭ－Ｉ－001",
        )
        for trace in traces:
            with self.subTest(trace=trace):
                result, payload = _run(_insert_trace(trace))
                self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
                self.assertIn(
                    "formal_identifier_or_artifact_trace_forbidden",
                    payload["error_codes"],
                )

    def test_filesystem_and_runtime_paths_are_rejected_but_public_urls_are_allowed(self):
        paths = (
            "/srv/customers/example/runtime/manifest.json",
            "路径为/etc/private/input.json",
            r"C:\customers\example\candidate\draft.md",
            "runtime/evidence-manifest.json",
            "证据位于data/public-note.pdf",
        )
        for path in paths:
            with self.subTest(path=path):
                result, payload = _run(_insert_trace(path))
                self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
                self.assertIn("filesystem_or_runtime_path_forbidden", payload["error_codes"])

        result, payload = _run(VALID_DRAFT)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertNotIn("filesystem_or_runtime_path_forbidden", payload["error_codes"])

    def test_intranet_and_nonpublic_locators_are_rejected(self):
        traces = (
            "内网页面 http://10.1.2.3/report",
            "内网页面 https://portal.internal/report",
            "本机页面 http://localhost:8080/report",
            "文件定位 file:///etc/passwd",
            "文件定位 file:/etc/passwd",
            "服务地址 192.168.1.12",
            "服务主机 portal.ops.internal",
        )
        for trace in traces:
            with self.subTest(trace=trace):
                result, payload = _run(_insert_trace(trace))
                self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
                self.assertTrue(
                    {
                        "internal_network_trace_forbidden",
                        "nonpublic_locator_scheme_forbidden",
                    }
                    & set(payload["error_codes"]),
                    payload,
                )

    def test_credentials_and_sensitive_data_traces_are_rejected_without_echo(self):
        traces = (
            "Authorization：Bearer TOPSECRET-DO-NOT-ECHO",
            "患者姓名：张某",
            "手机号：13800138000",
            "全角手机号：１３８００１３８０００",
            "身份证号：11010519491231002X",
            "邮箱：person@example.org",
            "CRM数据显示该项目已签约",
        )
        for trace in traces:
            with self.subTest(trace=trace):
                result, payload = _run(_insert_trace(trace))
                self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
                self.assertTrue(
                    {
                        "credential_or_session_trace_forbidden",
                        "personal_or_sensitive_data_trace_forbidden",
                    }
                    & set(payload["error_codes"]),
                    payload,
                )
                self.assertNotIn(trace, result.stdout)
                self.assertNotIn(trace, result.stderr)

    def test_sensitive_values_inside_public_urls_are_rejected_without_echo(self):
        urls = (
            "https://example.gov.cn/download?sig=SUPERSECRET&x=13800138000",
            "https://example.gov.cn/person/person%40example.org/report",
            "https://example.gov.cn/download?redirect=%252Fpatient%252F13800138000",
            "https://example.gov.cn/report?session_token=TOPSECRET",
        )
        for url in urls:
            with self.subTest(url=url):
                candidate = VALID_DRAFT.replace(
                    "https://www.example.gov.cn/news/2026/item.html",
                    url,
                )
                result, payload = _run(candidate)
                self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
                self.assertTrue(
                    {
                        "sensitive_locator_parameter_forbidden",
                        "sensitive_locator_value_forbidden",
                    }
                    & set(payload["error_codes"]),
                    payload,
                )
                self.assertNotIn(url, result.stdout)
                self.assertNotIn(url, result.stderr)

    def test_public_sources_section_requires_a_public_url_and_visible_content(self):
        no_url = VALID_DRAFT.replace(
            "[机构官网](https://www.example.gov.cn/news/2026/item.html)",
            "（来源未提供）",
        )
        result, payload = _run(no_url)
        self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
        self.assertIn("public_sources_section_requires_public_url", payload["error_codes"])

        empty = VALID_DRAFT.replace(
            "- 官网公开信息显示该院正在推进信息化建设。[机构官网](https://www.example.gov.cn/news/2026/item.html)\n",
            "",
        )
        result, payload = _run(empty)
        self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
        self.assertIn(
            "required_section_public_sources_pending_review_must_contain_visible_content",
            payload["error_codes"],
        )

    def test_public_draft_documentation_names_the_runtime_gate_and_review_status(self):
        contract = (SKILL_ROOT / "references" / "public-draft-runtime.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("validate_public_draft.py", contract)
        self.assertIn("`公开来源支持、待人工复核`", contract)
        self.assertNotIn("- `已核实事实`", contract)


if __name__ == "__main__":
    unittest.main()
