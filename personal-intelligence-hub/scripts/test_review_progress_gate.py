import unittest

from review_progress_gate import evaluate_progress


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


if __name__ == "__main__":
    unittest.main()
