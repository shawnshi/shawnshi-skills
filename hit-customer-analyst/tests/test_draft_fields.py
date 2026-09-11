import json
import tempfile
import unittest
from pathlib import Path

from tests.common import SCRIPTS, load_module, run_python
from tests.fixture_builder import build_pending_strategy_workspace
from tests.test_candidate_revision import b

f = load_module("draft_fields_tests", SCRIPTS / "draft_fields.py")


class DraftFieldsTests(unittest.TestCase):
    def test_render_single_input_preserves_existing_prose(self):
        meta = dict(zip(f.CONTEXT_FIELDS, ["信息中心团队", "验证需求", "记录访谈判断"]))
        text = "---\nartifact_type: visit_strategy\n---\n对象：{{strategy.target_contact_level}}\n目标：{{strategy.visit_objective}}\n动作：{{strategy.minimum_next_step}}\n现有分析：待核验。\n"
        result = f.render_strategy(text, meta)
        for v in meta.values():
            self.assertIn(v, result)
        self.assertIn("现有分析：待核验。", result)
        self.assertEqual(f.render_strategy(result, meta), result)
        with self.assertRaises(ValueError):
            f.render_strategy(text, {**meta, "minimum_next_step": "待确认"})

    def test_candidate_finalize_renders_actual_strategy_and_preserves_formal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ws = build_pending_strategy_workspace(root / "formal")
            candidate = b.prepare(ws, root / "candidate")
            path = next(candidate.glob("*交流策略*"))
            text = path.read_text(encoding="utf-8")
            meta = b.tx.parse_frontmatter(text)
            head, body = text.split("---", 2)[1:]
            for key in f.CONTEXT_FIELDS:
                body = body.replace(meta[key], "{{strategy." + key + "}}")
            path.write_text("---" + head + "---" + body, encoding="utf-8")
            before = {p.name: p.read_bytes() for p in ws.glob("*.md")}
            result = b.finalize(ws, candidate)
            self.assertEqual(result["errors"], [], result)
            self.assertNotIn("{{strategy.", path.read_text(encoding="utf-8"))
            self.assertEqual(before, {p.name: p.read_bytes() for p in ws.glob("*.md")})

    def test_ledger_dates_notes_and_c_source_are_not_silently_fixed(self):
        source = dict.fromkeys(f.SOURCE_FIELDS, "说明")
        source.update(
            source_id="SRC-I-001",
            accessed_date="2026-09-07",
            level="C",
            external_use="false",
            notes="存档读取；含|分隔符",
        )
        claim = dict.fromkeys(f.CLAIM_FIELDS, "说明")
        claim.update(claim_id="CLM-I-001", claim_type="H", support="SRC-I-001")
        data = {"sources": [source], "claims": [claim]}
        original = json.dumps(data, ensure_ascii=False)
        result = f.render_ledger(data)
        self.assertIn("2026-09-07", result)
        self.assertIn("存档读取", result)
        self.assertEqual(original, json.dumps(data, ensure_ascii=False))
        for mutation in ("date", "type"):
            bad = json.loads(original)
            if mutation == "date":
                bad["sources"][0]["accessed_date"] = "2026-09-07（读取）"
            else:
                bad["claims"][0]["claim_type"] = "A"
            with self.assertRaises(ValueError):
                f.render_ledger(bad)
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "ledger.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            r = run_python("draft_fields.py", ["ledger", str(p)])
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_finalize_preserves_required_review_state_for_stale_draft(self):
        for freshness in ("stale", "invalidated"):
            with (
                self.subTest(freshness=freshness),
                tempfile.TemporaryDirectory() as temp,
            ):
                root = Path(temp)
                ws = build_pending_strategy_workspace(root / "formal")
                candidate = b.prepare(ws, root / "candidate")
                path = next(candidate.glob("*交流策略*"))
                text = path.read_text(encoding="utf-8")
                meta = b.tx.parse_frontmatter(text)
                meta.update(
                    freshness_status=freshness, review_status="changes_requested"
                )
                path.write_text(
                    b.init.replace_frontmatter(text, meta), encoding="utf-8"
                )
                b.finalize(ws, candidate)
                updated = b.tx.parse_frontmatter(path.read_text(encoding="utf-8"))
                self.assertEqual(updated["review_status"], "changes_requested")
                self.assertEqual(updated["freshness_status"], freshness)
                self.assertEqual(updated["reviewed_body_sha256"], "")
                self.assertEqual(
                    b.tx.parse_frontmatter(
                        next(ws.glob("*交流策略*")).read_text(encoding="utf-8")
                    )["freshness_status"],
                    "current",
                )

    def test_defined_verification_action_does_not_confirm_identity(self):
        for key in ("visit_objective", "minimum_next_step"):
            self.assertTrue(
                f.val.resolved_strategy_context(
                    key, "形成推进或观察结论，并列明下一轮访谈对象与待确认事项"
                )
            )
            for value in ("待确认", "目标待确认", "{{minimum_next_step}}"):
                self.assertFalse(f.val.resolved_strategy_context(key, value))
        self.assertFalse(
            f.val.resolved_strategy_context("target_contact_level", "院长身份待确认")
        )
        self.assertFalse(f.val.valid_actor("李明（待确认）"))
