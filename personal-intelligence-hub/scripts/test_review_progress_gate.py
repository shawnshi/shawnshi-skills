import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from review_progress_gate import (
    derive_watch_fingerprint,
    evaluate_progress,
)


class ReviewProgressGateTests(unittest.TestCase):
    def setUp(self):
        self.first = {
            "event_ordinal": 100,
            "last_event_at": "2026-08-24T06:00:00+08:00",
            "tool_call_count": 12,
        }

    def test_growth_resets_wait_budget(self):
        state, _ = evaluate_progress(None, self.first, "running")
        grown = {
            "event_ordinal": 107,
            "last_event_at": "2026-08-24T06:02:20+08:00",
            "tool_call_count": 19,
        }

        next_state, decision = evaluate_progress(state, grown, "running")

        self.assertEqual(decision, "continue_wait")
        self.assertFalse(next_state["reminder_sent"])
        self.assertEqual(next_state["unchanged_after_reminder"], 0)

    def test_three_identical_post_reminder_checks_declare_lost(self):
        state, _ = evaluate_progress(None, self.first, "running")
        state, decision = evaluate_progress(state, self.first, "running")
        self.assertEqual(decision, "send_reminder")
        for _ in range(2):
            state, decision = evaluate_progress(state, self.first, "running")
            self.assertEqual(decision, "continue_wait")
        state, decision = evaluate_progress(state, self.first, "running")
        self.assertEqual(decision, "declare_lost")

    def test_terminal_exit_declares_lost_and_artifact_ready_requires_gate(self):
        _, lost = evaluate_progress(None, self.first, "failed")
        _, ready = evaluate_progress(None, self.first, "artifact_ready")

        self.assertEqual(lost, "declare_lost")
        self.assertEqual(ready, "verify_artifact")

    def test_completed_with_all_valid_watch_json_verifies_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            core = Path(directory) / "refined_core.json"
            receipt = Path(directory) / "semantic_receipt.json"
            core.write_text("{}", encoding="utf-8")
            receipt.write_text("[]", encoding="utf-8")
            fingerprint = derive_watch_fingerprint(
                None,
                [core, receipt],
                2,
                observed_at=datetime(
                    2026, 8, 25, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")
                ),
                review_kind="semantic",
            )

            _, decision = evaluate_progress(
                None,
                fingerprint,
                "completed",
                review_kind="semantic",
            )

            self.assertEqual(decision, "verify_artifact")

    def test_completed_without_all_valid_watch_json_declares_lost(self):
        invalid_contents = {
            "missing": None,
            "empty": "",
            "invalid": "not-json",
        }
        for label, content in invalid_contents.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                core = Path(directory) / "refined_core.json"
                receipt = Path(directory) / "semantic_receipt.json"
                core.write_text("{}", encoding="utf-8")
                if content is not None:
                    receipt.write_text(content, encoding="utf-8")
                fingerprint = derive_watch_fingerprint(
                    None,
                    [core, receipt],
                    2,
                    observed_at=datetime(
                        2026, 8, 25, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")
                    ),
                    review_kind="semantic",
                )

                _, decision = evaluate_progress(
                    None,
                    fingerprint,
                    "completed",
                    review_kind="semantic",
                )

                self.assertEqual(decision, "declare_lost")

    def test_completed_without_watch_paths_remains_lost(self):
        _, decision = evaluate_progress(None, self.first, "completed")

        self.assertEqual(decision, "declare_lost")

    def test_milestone_above_global_limit_is_rejected(self):
        fingerprint = dict(self.first, milestone_seq=3)

        with self.assertRaisesRegex(ValueError, "milestone_seq.*at most 2"):
            evaluate_progress(None, fingerprint, "running")

    def test_review_kind_applies_phase_specific_milestone_limit(self):
        semantic = dict(self.first, milestone_seq=2)
        red_team = dict(self.first, milestone_seq=1)

        _, semantic_decision = evaluate_progress(
            None,
            semantic,
            "running",
            review_kind="semantic",
        )
        _, red_team_decision = evaluate_progress(
            None,
            red_team,
            "running",
            review_kind="red_team",
        )

        self.assertEqual(semantic_decision, "continue_wait")
        self.assertEqual(red_team_decision, "continue_wait")
        with self.assertRaisesRegex(ValueError, "red_team.*at most 1"):
            evaluate_progress(
                None,
                dict(self.first, milestone_seq=2),
                "running",
                review_kind="red_team",
            )

    def test_regressing_fingerprint_is_rejected(self):
        state, _ = evaluate_progress(None, self.first, "running")
        regressed = dict(self.first, event_ordinal=99)

        with self.assertRaisesRegex(ValueError, "cannot regress"):
            evaluate_progress(state, regressed, "running")

    def test_repeated_growth_without_milestone_is_bounded(self):
        state, _ = evaluate_progress(None, self.first, "running")
        decision = "continue_wait"
        for index in range(1, 19):
            current = {
                "event_ordinal": 100 + index,
                "last_event_at": f"2026-08-24T06:{index:02d}:00+08:00",
                "tool_call_count": 12 + index,
                "milestone_seq": 0,
            }
            state, decision = evaluate_progress(state, current, "running")

        self.assertEqual(decision, "declare_lost")

    def test_milestone_growth_resets_nonsemantic_growth_budget(self):
        state, _ = evaluate_progress(None, self.first, "running")
        state["growth_checks_without_milestone"] = 14
        milestone = dict(
            self.first,
            event_ordinal=101,
            last_event_at="2026-08-24T06:01:00+08:00",
            milestone_seq=1,
        )

        state, decision = evaluate_progress(state, milestone, "running")

        self.assertEqual(decision, "continue_wait")
        self.assertEqual(state["growth_checks_without_milestone"], 0)

    def test_watch_paths_supply_progress_when_session_telemetry_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            draft = Path(directory) / "refined.draft.json"
            observed = datetime(2026, 8, 25, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
            first = derive_watch_fingerprint(None, [draft], 1, observed_at=observed)
            state, decision = evaluate_progress(None, first, "running")
            self.assertEqual(decision, "continue_wait")

            draft.write_text("{}", encoding="utf-8")
            second = derive_watch_fingerprint(
                state,
                [draft],
                1,
                observed_at=observed.replace(minute=1),
            )
            state, decision = evaluate_progress(state, second, "running")

            self.assertEqual(decision, "continue_wait")
            self.assertGreater(second["event_ordinal"], first["event_ordinal"])

    def test_watch_paths_declare_lost_after_reminder_and_three_static_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            draft = Path(directory) / "refined.draft.json"
            observed = datetime(2026, 8, 25, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
            fingerprint = derive_watch_fingerprint(None, [draft], 1, observed_at=observed)
            state, _ = evaluate_progress(None, fingerprint, "running")
            fingerprint = derive_watch_fingerprint(state, [draft], 1, observed_at=observed)
            state, decision = evaluate_progress(state, fingerprint, "running")
            self.assertEqual(decision, "send_reminder")
            for expected in ("continue_wait", "continue_wait", "declare_lost"):
                fingerprint = derive_watch_fingerprint(
                    state,
                    [draft],
                    1,
                    observed_at=observed,
                )
                state, decision = evaluate_progress(state, fingerprint, "running")
                self.assertEqual(decision, expected)

    def test_watch_path_progress_after_stalled_reminder_resets_static_counter(self):
        with tempfile.TemporaryDirectory() as directory:
            draft = Path(directory) / "refined.draft.json"
            observed = datetime(2026, 8, 25, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
            fingerprint = derive_watch_fingerprint(None, [draft], 1, observed_at=observed)
            state, _ = evaluate_progress(None, fingerprint, "running")
            fingerprint = derive_watch_fingerprint(state, [draft], 1, observed_at=observed)
            state, decision = evaluate_progress(state, fingerprint, "running")
            self.assertEqual(decision, "send_reminder")

            draft.write_text("{}", encoding="utf-8")
            fingerprint = derive_watch_fingerprint(
                state,
                [draft],
                1,
                observed_at=observed + timedelta(minutes=1),
            )
            state, decision = evaluate_progress(state, fingerprint, "running")

            self.assertEqual(decision, "continue_wait")
            self.assertFalse(state["reminder_sent"])
            self.assertEqual(state["unchanged_after_reminder"], 0)
            self.assertEqual(state["growth_checks_without_milestone"], 1)

if __name__ == "__main__":
    unittest.main()
