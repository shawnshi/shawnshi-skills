import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).parent))
import report_pair
from report_pair import (
    ReportPairError,
    parse_html_recommendations,
    parse_markdown_recommendations,
    render_report_pair,
    validate_manifest,
    validate_pair,
    write_report_pair,
)


def make_recommendation(index):
    return {
        "id": f"R-{index:02d}",
        "finding_ids": [f"F-{index:02d}"],
        "action": f"Action {index}",
        "implementation_layer": "audit-skill",
        "owner": "skill-maintainer",
        "status": "not_started",
        "authorization": "required",
        "validation": {
            "criterion": f"Criterion {index}",
            "result": "not_run",
            "evidence": [],
        },
    }


def make_manifest(report_id="report-v1"):
    return {
        "report_id": report_id,
        "title": "Collaboration audit",
        "recommendations": [make_recommendation(index) for index in range(1, 7)],
    }


def make_successor(previous):
    current = copy.deepcopy(previous)
    current["report_id"] = "report-v2"
    current["previous_report_id"] = previous["report_id"]
    return current


class ReportPairTests(unittest.TestCase):
    def test_default_templates_lead_with_six_result_questions(self):
        rendered = render_report_pair(make_manifest())
        questions = (
            "哪些任务已完成，哪些仍未解决？",
            "哪项有证据的可避免摩擦代价最高？",
            "AI 把哪些工作转交给了用户？",
            "哪些必要的人类决策必须保留？",
            "上次整改得到了什么后续检验？",
            "下一项唯一实验是什么，什么结果会推翻它？",
        )
        for kind in ("markdown", "html"):
            text = rendered[kind]
            positions = [text.index(question) for question in questions]
            self.assertEqual(positions, sorted(positions))
            self.assertLess(positions[-1], text.index("支撑证据：运行指标与口径"))
            self.assertNotRegex(text, report_pair.UNRESOLVED_PLACEHOLDER_PATTERN)
            for lens in ("任务收敛", "用户介入", "返工", "自主性校准", "维护价值",
                         "委派收益", "上下文与规则负担", "改进实验"):
                self.assertIn(lens, text)
            for boundary in ("来源声明", "已核验出处", "分子／分母", "替代解释",
                             "不可用", "不可计算", "未知", "cohort", "不认证"):
                self.assertIn(boundary, text)

    def test_legacy_manifest_without_analysis_defaults_unknown_not_green(self):
        manifest = make_manifest()
        self.assertNotIn("collaboration_analysis", manifest)
        rendered = render_report_pair(manifest)
        self.assertEqual(rendered["validation"]["status"], "pass")
        self.assertNotIn("<p>—</p>", rendered["html"])
        self.assertIn("结论不可用", rendered["html"])
        self.assertIn("任务分母", rendered["markdown"])
        self.assertIn("暴露／可比后续／实际观察分母", rendered["markdown"])
        for kind in ("markdown", "html"):
            body = rendered[kind].split("<body>")[-1]
            self.assertNotRegex(body, r"(?<![0-9])0%")
            self.assertIn("不认证", rendered[kind])
        self.assertTrue(all(row["validation"]["result"] == "not_run"
                            for row in parse_html_recommendations(rendered["html"])))

    def test_recommendation_markup_is_escaped_with_exact_pair_parity(self):
        manifest = make_manifest()
        payload = '<script>alert("synthetic")</script> & | <img src=x onerror=alert(1)>'
        item = manifest["recommendations"][0]
        for key in ("action", "owner", "implementation_layer"):
            item[key] = payload
        item["validation"] = {"criterion": payload, "result": "pass", "evidence": [payload]}
        manifest["title"] = payload
        rendered = render_report_pair(manifest)
        self.assertEqual(parse_markdown_recommendations(rendered["markdown"]),
                         parse_html_recommendations(rendered["html"]))
        for kind in ("markdown", "html"):
            self.assertNotIn("<script>", rendered[kind])
            self.assertNotIn("<img", rendered[kind])
            self.assertIn("&lt;script&gt;", rendered[kind])
        self.assertEqual(parse_html_recommendations(rendered["html"])[0]["action"], payload)
        report_pair._assert_self_contained_template(rendered["html"])

    def test_custom_filled_templates_keep_existing_placeholder_contract(self):
        manifest = make_manifest()
        rendered = render_report_pair(
            manifest,
            markdown_template_text="# Explicit synthetic evidence\n{{RECOMMENDATIONS}}",
            html_template_text="<!doctype html><html><body><h1>{{TITLE}}</h1>"
                               "<p>Explicit synthetic evidence</p>{{RECOMMENDATIONS}}</body></html>",
        )
        self.assertEqual(rendered["validation"]["status"], "pass")
        self.assertIn("Explicit synthetic evidence", rendered["html"])
        self.assertNotIn("{{", rendered["html"])
        with self.assertRaisesRegex(ReportPairError, "network resources"):
            render_report_pair(manifest, html_template_text=
                               '<script src="https://example.invalid/x.js"></script>{{RECOMMENDATIONS}}')

    def test_six_item_round_trip(self):
        manifest = make_manifest()

        rendered = render_report_pair(manifest)
        markdown_rows = parse_markdown_recommendations(rendered["markdown"])
        html_rows = parse_html_recommendations(rendered["html"])

        expected_ids = [f"R-{index:02d}" for index in range(1, 7)]
        self.assertEqual([row["id"] for row in markdown_rows], expected_ids)
        self.assertEqual([row["id"] for row in html_rows], expected_ids)
        self.assertEqual(rendered["validation"]["recommendation_count"], 6)
        self.assertIn('data-recommendation-id="R-06"', rendered["html"])
        self.assertNotIn("http://", rendered["html"])
        self.assertNotIn("https://", rendered["html"])

    def test_missing_old_id_is_fatal(self):
        previous = make_manifest()
        current = make_successor(previous)
        current["recommendations"] = [
            item for item in current["recommendations"] if item["id"] != "R-05"
        ]

        with self.assertRaisesRegex(
            ReportPairError, "previous recommendation IDs disappeared: R-05"
        ):
            validate_manifest(current, previous)

    def test_renumbering_or_semantic_drift_is_fatal(self):
        previous = make_manifest()
        current = make_successor(previous)
        old_r06 = previous["recommendations"][5]
        current_r05 = current["recommendations"][4]
        for field in ("finding_ids", "action", "implementation_layer", "owner"):
            current_r05[field] = copy.deepcopy(old_r06[field])

        with self.assertRaisesRegex(
            ReportPairError, "semantic drift for stable recommendation ID R-05"
        ):
            validate_manifest(current, previous)

    def test_missing_html_section_is_fatal(self):
        manifest = make_manifest()
        rendered = render_report_pair(manifest)
        broken_html = rendered["html"].replace(
            'id="recommendations"', 'id="missing-recommendations"', 1
        )

        with self.assertRaisesRegex(
            ReportPairError, "HTML recommendation section is missing"
        ):
            validate_pair(manifest, rendered["markdown"], broken_html)

    def test_status_mismatch_is_fatal(self):
        manifest = make_manifest()
        rendered = render_report_pair(manifest)
        broken_html = rendered["html"].replace(
            'data-status="not_started"', 'data-status="implemented"', 1
        )

        with self.assertRaisesRegex(ReportPairError, "data-status"):
            validate_pair(manifest, rendered["markdown"], broken_html)

    def test_validation_evidence_mismatch_is_fatal(self):
        manifest = make_manifest()
        manifest["recommendations"][0]["validation"] = {
            "criterion": "Replay fixture",
            "result": "pass",
            "evidence": ["fixture.jsonl:1"],
        }
        rendered = render_report_pair(manifest)
        broken_html = rendered["html"].replace("fixture.jsonl:1", "fixture.jsonl:2", 1)

        with self.assertRaisesRegex(
            ReportPairError, "HTML status or validation projection mismatch"
        ):
            validate_pair(manifest, rendered["markdown"], broken_html)

    def test_false_validation_green_is_fatal(self):
        manifest = make_manifest()
        manifest["recommendations"][0]["validation"]["result"] = "pass"

        with self.assertRaisesRegex(
            ReportPairError, "validation.evidence is required when result is pass"
        ):
            validate_manifest(manifest)

    def test_explicit_supersession_passes(self):
        previous = make_manifest()
        current = make_successor(previous)
        current_r05 = current["recommendations"][4]
        current_r05["status"] = "superseded"
        current_r05["closure_reason"] = "Replaced by an approved environment probe"
        current_r05["closure_evidence"] = ["decision.json:12"]

        rendered = render_report_pair(current, previous_manifest=previous)
        result = validate_pair(
            current,
            rendered["markdown"],
            rendered["html"],
            previous_manifest=previous,
        )

        self.assertEqual(result["status"], "pass")
        self.assertIn("R-05", result["recommendation_ids"])
        self.assertIn("superseded", rendered["markdown"])
        self.assertIn("decision.json:12", rendered["html"])

    def test_write_is_exclusive_and_receipt_hashes_the_pair(self):
        manifest = make_manifest()
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            manifest_path = root / "manifest.json"
            markdown_path = root / "report.md"
            html_path = root / "report.html"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )

            result = write_report_pair(
                manifest_path=manifest_path,
                markdown_path=markdown_path,
                html_path=html_path,
            )
            receipt = json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))

            self.assertEqual(receipt["recommendation_count"], 6)
            self.assertEqual(
                receipt["recommendation_ids"],
                [f"R-{index:02d}" for index in range(1, 7)],
            )
            for key in (
                "manifest_sha256",
                "markdown_sha256",
                "html_sha256",
                "validator_sha256",
            ):
                self.assertRegex(receipt[key], r"^[0-9A-F]{64}$")

            with self.assertRaisesRegex(ReportPairError, "refusing to overwrite"):
                write_report_pair(
                    manifest_path=manifest_path,
                    markdown_path=markdown_path,
                    html_path=html_path,
                )

    def test_publish_failure_leaves_no_visible_partial_batch(self):
        manifest = make_manifest()
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            manifest_path = root / "manifest.json"
            markdown_path = root / "report.md"
            html_path = root / "report.html"
            receipt_path = root / "report.receipt.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            real_link = report_pair.os.link
            call_count = 0

            def fail_receipt_publish(source, target):
                nonlocal call_count
                call_count += 1
                if call_count == 3:
                    raise OSError("injected receipt publish failure")
                return real_link(source, target)

            with mock.patch.object(report_pair.os, "link", side_effect=fail_receipt_publish):
                with self.assertRaises(OSError):
                    write_report_pair(
                        manifest_path=manifest_path,
                        markdown_path=markdown_path,
                        html_path=html_path,
                        receipt_path=receipt_path,
                    )

            self.assertFalse(markdown_path.exists())
            self.assertFalse(html_path.exists())
            self.assertFalse(receipt_path.exists())
            self.assertEqual(list(root.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
