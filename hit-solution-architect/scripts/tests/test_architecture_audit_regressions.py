"""Synthetic ARCH001..006 regression cases; no customer data or external calls."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import test_quality_gate as original

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))
from logic_checker import (  # noqa: E402
    SolutionLogicChecker,
    classify_review_placeholders,
)

ROOT = SCRIPT_DIR.parent


def check(
    content: str,
    stage: str = "review",
    *,
    required_modules: tuple[str, ...] = (),
    review_complete: bool = False,
) -> dict:
    return SolutionLogicChecker(
        content,
        target_file="synthetic.md",
        profile="brief",
        stage=stage,
        required_modules=required_modules,
        review_complete=review_complete,
    ).run()


def codes(report: dict, collection: str = "errors") -> set[str]:
    return {item["code"] for item in report[collection]}


class LogicCheckerAuditTests(original.ScriptTestCase):
    def test_arch002_fenced_commitments_block_review(self) -> None:
        for fence in ("```", "~~~~"):
            with self.subTest(fence=fence):
                content = (
                    "# 接口契约\n现状已确认，风险已登记。\n"
                    + fence
                    + 'json\n{"patient_id":"{{PATIENT_ID}}"}\n'
                    + fence
                )
                self.assertIn("E_UNRESOLVED_PLACEHOLDER", codes(check(content)))

    def test_arch002_code_inherits_controlled_parent_and_sibling_resets(self) -> None:
        content = (
            "# 信息缺口\n## 接口格式\n```yaml\n# 目标架构\nvalue: {{GAP}}\n```\n"
            "# 目标架构\n现状与风险已登记。\n~~~yaml\n# 信息缺口\nvalue: {{COMMITMENT}}\n~~~\n"
        )
        self.assertEqual(
            classify_review_placeholders(content), (["{{COMMITMENT}}"], ["{{GAP}}"])
        )
        report = check(content)
        self.assertIn("E_UNRESOLVED_PLACEHOLDER", codes(report))
        self.assertIn("W_CONTROLLED_REVIEW_PLACEHOLDER", codes(report, "warnings"))

    def test_arch002_mixed_short_and_unclosed_fences_do_not_open_sections(self) -> None:
        for inner in ("~~~", "``"):
            with self.subTest(inner=inner):
                content = (
                    "# 接口契约\n现状、风险。\n````yaml\n"
                    + inner
                    + "\n# 信息缺口\n{{ID}}"
                )
                self.assertEqual(
                    classify_review_placeholders(content), (["{{ID}}"], [])
                )

    def test_arch002_registered_and_technical_code_tokens(self) -> None:
        content = "# 接口契约\n现状、风险。\n```text\n[HL7_V2] [ISO_27001]\n```\n"
        self.assertNotIn("E_UNRESOLVED_PLACEHOLDER", codes(check(content)))
        self.assertIn(
            "E_UNRESOLVED_PLACEHOLDER",
            codes(check(content.replace("[HL7_V2]", "[OWNER]"))),
        )

    def test_arch002_controlled_code_stage_contract_via_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            draft = self.write_draft(
                Path(temporary), "# 信息缺口\n现状、风险。\n```json\n{{FIELD}}\n```\n"
            )
            for stage, code, finding in (
                ("draft", 0, "W_UNRESOLVED_PLACEHOLDER"),
                ("review", 0, "W_CONTROLLED_REVIEW_PLACEHOLDER"),
                ("release", 1, "E_UNRESOLVED_PLACEHOLDER"),
            ):
                with self.subTest(stage=stage):
                    completed, report = self.run_script(
                        "logic_checker.py",
                        draft,
                        "--profile",
                        "brief",
                        "--stage",
                        stage,
                    )
                    self.assertEqual(completed.returncode, code)
                    self.assertIn(
                        finding, codes(report, "errors" if code else "warnings")
                    )

    def test_arch003_interface_contract_synonyms_and_negations(self) -> None:
        for name in ("接口清单", "接口契约", "接口/事件契约"):
            for negative in (False, True):
                with self.subTest(name=name, negative=negative):
                    content = (
                        "# 范围\n现状和风险已登记。本次不涉及" + name + "。"
                        if negative
                        else "# "
                        + name
                        + "\n现状和风险已登记。发起方 HIS，接收方 LIS；"
                        "数据对象为检验申请；版本 v1，幂等键 request_id，超时 3 秒，失败重试由接口负责人验证。"
                    )
                    report = check(content, required_modules=("interoperability",))
                    self.assertEqual(
                        "E_MISSING_REQUIRED_MODULE" in codes(report), negative
                    )

    def test_arch005_explicit_missing_sources_warn_or_block(self) -> None:
        missing = (
            "无来源",
            "来源缺失",
            "来源待补",
            "来源待补充",
            "来源：无",
            "来源：未知",
            "来源：",
            "来源",
            "来源：{{SOURCE}}",
            "来源：[待核验]",
            "source: none",
            "source: N/A",
            "source:",
        )
        for source in missing:
            for stage in ("draft", "review", "release"):
                with self.subTest(source=source, stage=stage):
                    report = check(
                        "# 测算\n现状与风险已登记。\nTCO 100万元；"
                        + source
                        + "；资料日期：2026-09-01；适用地区：中国。\n",
                        stage,
                        review_complete=stage == "release",
                    )
                    self.assertIn(
                        ("E" if stage == "release" else "W")
                        + "_UNSOURCED_QUANTIFIED_BENEFIT",
                        codes(report, "errors" if stage == "release" else "warnings"),
                    )
                    if stage == "release":
                        self.assertFalse(report["gate"]["release_ready"])

    def test_arch005_neighbor_source_does_not_override_explicit_gap(self) -> None:
        for gap in ("无来源", "来源缺失", "来源待补"):
            with self.subTest(gap=gap):
                report = check(
                    "# 测算\n现状、风险已登记。\n"
                    "TCO 200万元；来源：合成测算表 S-1；资料日期：2026-09-01；适用地区：中国。\n"
                    "TCO 100万元；"
                    + gap
                    + "；资料日期：2026-09-01；适用地区：中国。\n",
                    "release",
                    review_complete=True,
                )
                finding = next(
                    item
                    for item in report["errors"]
                    if item["code"] == "E_UNSOURCED_QUANTIFIED_BENEFIT"
                )
                self.assertEqual(finding["total"], 1)
                self.assertIn("100万元", finding["instances"][0]["text"])

    def test_arch005_separate_missing_metadata_beats_nearby_source(self) -> None:
        for metadata in ("来源：待补；", "来源：\n", "source:\n"):
            with self.subTest(metadata=metadata):
                report = check(
                    "# 测算\n现状、风险。\nTCO 100万元。\n"
                    + metadata
                    + "资料日期：2026-09-01；适用地区：中国。\n参考公开文件 S-1。\n",
                    "release",
                    review_complete=True,
                )
                self.assertIn("E_UNSOURCED_QUANTIFIED_BENEFIT", codes(report))

    def test_arch005_positive_sources_preserve_release_contract(self) -> None:
        for source in (
            "来源：合成测算表 S-1 第2页",
            "source: synthetic-report p2",
            "来源：客户材料",
        ):
            with self.subTest(source=source):
                report = check(
                    "# 测算\n现状、风险。\nTCO 100万元；"
                    + source
                    + "；资料日期：2026-09-01；适用地区：中国。\n",
                    "release",
                    review_complete=True,
                )
                self.assertEqual(report["errors"], [])
                self.assertTrue(report["gate"]["release_ready"])

    def test_arch005_missing_status_requires_complete_boundary(self) -> None:
        for source, missing in (
            ("来源：无锡市医院测算底表", False),
            ("来源：未知地区合成测算底表", False),
            ("来源：无", True),
            ("来源：待补", True),
        ):
            for stage in ("draft", "review", "release"):
                with self.subTest(source=source, stage=stage):
                    report = check(
                        "# 测算\n现状、风险。\nTCO 100万元；"
                        + source
                        + "；资料日期：2026-09-01；适用地区：中国。\n",
                        stage,
                        review_complete=stage == "release",
                    )
                    collection = "errors" if stage == "release" else "warnings"
                    code = (
                        "E" if stage == "release" else "W"
                    ) + "_UNSOURCED_QUANTIFIED_BENEFIT"
                    self.assertEqual(code in codes(report, collection), missing)
                    if stage == "release":
                        self.assertEqual(report["gate"]["release_ready"], not missing)

    def test_arch005_separate_gap_cannot_cross_another_claim(self) -> None:
        for stage in ("draft", "review", "release"):
            with self.subTest(stage=stage):
                report = check(
                    "# 测算\n现状、风险。\n"
                    "TCO 200万元；来源：合成测算底表 S-1；资料日期：2026-09-01；适用地区：中国。\n"
                    "TCO 100万元；资料日期：2026-09-01；适用地区：中国。\n"
                    "来源：待补。\n",
                    stage,
                    review_complete=stage == "release",
                )
                findings = report["errors" if stage == "release" else "warnings"]
                finding = next(
                    item
                    for item in findings
                    if item["code"].endswith("_UNSOURCED_QUANTIFIED_BENEFIT")
                )
                self.assertEqual(finding["total"], 1)
                self.assertEqual(finding["instances"][0]["line"], 4)
                self.assertIn("100万元", finding["instances"][0]["text"])

    def test_arch005_own_explicit_source_precedes_nearby_gap(self) -> None:
        report = check(
            "# 测算\n现状、风险。\n来源：待补。\n"
            "TCO 200万元；来源：合成测算底表 S-1；资料日期：2026-09-01；适用地区：中国。\n",
            "release",
            review_complete=True,
        )
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["gate"]["release_ready"])

    def test_arch005_positive_metadata_cannot_cross_claim_either_direction(
        self,
    ) -> None:
        for lines, unsourced_line in (
            (["TCO 200万元。", "TCO 100万元。", "来源：合成测算底表 S-1。"], 3),
            (["来源：合成测算底表 S-1。", "TCO 100万元。", "TCO 200万元。"], 5),
        ):
            with self.subTest(lines=lines):
                report = check("# 测算\n现状、风险。\n" + "\n".join(lines), "release")
                finding = next(
                    item
                    for item in report["errors"]
                    if item["code"] == "E_UNSOURCED_QUANTIFIED_BENEFIT"
                )
                self.assertEqual(finding["total"], 1)
                self.assertEqual(finding["instances"][0]["line"], unsourced_line)
                self.assertIn("200万元", finding["instances"][0]["text"])

    def test_arch005_boundary_and_attribution_strict_qa_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            for body, exit_code, unsourced_count in (
                (
                    "TCO 200万元；来源：无锡市医院测算底表；资料日期：2026-09-01；适用地区：中国。",
                    0,
                    0,
                ),
                ("TCO 200万元；来源：无；资料日期：2026-09-01；适用地区：中国。", 1, 1),
                (
                    "TCO 200万元；来源：合成测算底表 S-1；资料日期：2026-09-01；适用地区：中国。\n"
                    "TCO 100万元；资料日期：2026-09-01；适用地区：中国。\n来源：待补。",
                    1,
                    1,
                ),
            ):
                with self.subTest(body=body):
                    path = self.write_draft(
                        Path(temporary), "# 测算\n现状、风险。\n" + body
                    )
                    completed, report = self.run_script(
                        "qa_runner.py",
                        path,
                        "--profile",
                        "brief",
                        "--stage",
                        "release",
                        "--require-release-ready",
                        "--review-complete",
                    )
                    self.assertEqual(completed.returncode, exit_code)
                    self.assertEqual(report["gate"]["release_ready"], exit_code == 0)
                    unsourced = [
                        item
                        for item in report["errors"]
                        if item["code"] == "E_UNSOURCED_QUANTIFIED_BENEFIT"
                    ]
                    self.assertEqual(
                        sum(item["total"] for item in unsourced), unsourced_count
                    )
                    if "100万元" in body:
                        self.assertIn("100万元", unsourced[0]["instances"][0]["text"])

    def test_arch005_qa_strict_exit_uses_synthetic_approval_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            for source, exit_code in (("无来源", 1), ("来源：合成报告 S-1", 0)):
                with self.subTest(source=source):
                    path = self.write_draft(
                        Path(temporary),
                        "# 测算\n现状、风险。\nTCO 100万元；"
                        + source
                        + "；资料日期：2026-09-01；适用地区：中国。\n",
                    )
                    completed, report = self.run_script(
                        "qa_runner.py",
                        path,
                        "--profile",
                        "brief",
                        "--stage",
                        "release",
                        "--require-release-ready",
                        "--review-complete",
                    )
                    self.assertEqual(completed.returncode, exit_code)
                    self.assertIs(report["gate"]["release_ready"], exit_code == 0)


class ResourceValidatorAuditTests(original.ScriptTestCase):
    def test_arch006_algorithm_types_emit_json_and_nonzero(self) -> None:
        for algorithm in (None, 256, [], {}, True):
            with (
                self.subTest(algorithm=algorithm),
                tempfile.TemporaryDirectory() as temporary,
            ):
                path = original.ResourceValidatorTests().make_manifest(
                    Path(temporary), "# Synthetic resource\nText.\n"
                )
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest["hash_algorithm"] = algorithm
                path.write_text(json.dumps(manifest), encoding="utf-8")
                completed, report = self.run_script("resource_validator.py", path)
                self.assertEqual(completed.returncode, 1)
                self.assertIn("E_INVALID_HASH_ALGORITHM_TYPE", codes(report))
                self.assertEqual(completed.stderr, "")
                self.assertEqual(report["schema_version"], "2.0")

    def test_arch006_algorithm_strings_and_default_preserved(self) -> None:
        for algorithm, exit_code in (
            ("SHA-256", 0),
            ("sha-256", 0),
            ("MD5", 1),
            ("", 1),
            (None, 0),
        ):
            with (
                self.subTest(algorithm=algorithm),
                tempfile.TemporaryDirectory() as temporary,
            ):
                path = original.ResourceValidatorTests().make_manifest(
                    Path(temporary), "# Synthetic resource\nText.\n"
                )
                manifest = json.loads(path.read_text(encoding="utf-8"))
                if algorithm is None:
                    del manifest["hash_algorithm"]
                else:
                    manifest["hash_algorithm"] = algorithm
                path.write_text(json.dumps(manifest), encoding="utf-8")
                completed, report = self.run_script("resource_validator.py", path)
                self.assertEqual(completed.returncode, exit_code)
                if exit_code:
                    self.assertIn("E_UNSUPPORTED_HASH_ALGORITHM", codes(report))


class ArchitectureDocumentContractTests(unittest.TestCase):
    def test_arch001_four_axes_have_no_patient_free_bypass(self) -> None:
        contract = (ROOT / "templates/input_contract.md").read_text(encoding="utf-8")
        for field in ("患者数据状态", "材料密级", "当前任务使用授权", "外部使用授权"):
            self.assertIn("| " + field + " |", contract)
        self.assertNotIn("PUBLIC/NO_PATIENT_DATA", contract)
        self.assertIn("任何一轴的放行状态不能覆盖另一轴的限制", contract)
        self.assertIn("无患者数据的机密拓扑", contract)
        self.assertIn("不得外部检索或委派", contract)
        self.assertIn("未授权或授权不明时不得发送给外部工具", contract)
        self.assertIn("仅 `AUTHORIZED` 可在批准范围内最小必要处理", contract)

    def test_arch004_evidence_grades_have_one_definition(self) -> None:
        governance = (ROOT / "references/evidence_governance.md").read_text(
            encoding="utf-8"
        )
        xinchuang = (ROOT / "references/xinchuang_ecosystem.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "A：当前正式的官方文件、客户授权原始记录或可重复的项目测试", governance
        )
        self.assertIn("[evidence_governance.md](evidence_governance.md)", xinchuang)
        self.assertIn("可重复的项目测试为 A", xinchuang)
        self.assertIn("条件清晰的厂商技术材料为 B", xinchuang)
        self.assertNotIn("B：项目环境", xinchuang)
        for field in (
            "证据 ID 与来源定位",
            "证据类型",
            "版本适用性与环境匹配",
            "证据强度",
        ):
            self.assertIn(field, xinchuang)

    def test_handoff_six_fields_and_no_approval_inheritance(self) -> None:
        contract = (ROOT / "templates/input_contract.md").read_text(encoding="utf-8")
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        fields = (
            "决策与范围 ID",
            "证据与来源",
            "假设与缺口",
            "数字口径",
            "未决项与责任",
            "成熟度与授权边界",
        )
        for field in fields:
            self.assertIn("| " + field + " |", contract)
            self.assertIn(field, skill)
        self.assertIn("战略批准不继承为架构发布或实施批准", contract)
        self.assertIn("不改变技术事实、数字口径、证据强度或批准状态", contract)
        self.assertIn("不授权发布、外传或实施", contract)

    def test_arch002_and_arch005_docs_match_gate_semantics(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        governance = (ROOT / "references/evidence_governance.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("审阅稿的代码块继承外层章节", skill)
        self.assertIn("代码块内部标题不改变章节归属", skill)
        self.assertIn("在工作稿、审阅稿报告缺来源警告，在可提交稿报错", governance)
        self.assertIn("来源标记检查不证明来源真实或支持该主张", governance)


if __name__ == "__main__":
    unittest.main()
