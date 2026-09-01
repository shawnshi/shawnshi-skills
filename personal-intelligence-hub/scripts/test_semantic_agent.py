# pyright: reportMissingImports=false
from __future__ import annotations

import unittest

from run_contract import RunContractError  # pyright: ignore[reportMissingImports]
from semantic_agent import _date_failure_disqualifies  # pyright: ignore[reportMissingImports]


class SemanticAgentDateFailureTests(unittest.TestCase):
    def test_date_conflict_failure_kind_variants_disqualify(self) -> None:
        for failure_kind in (
            "published_at_conflict",
            "publication_date_conflict",
        ):
            with self.subTest(failure_kind=failure_kind):
                self.assertTrue(
                    _date_failure_disqualifies({"failure_kind": failure_kind})
                )

    def test_unknown_failure_kind_is_rejected_without_reason_inference(self) -> None:
        with self.assertRaisesRegex(RunContractError, "failure_kind is invalid"):
            _date_failure_disqualifies(
                {
                    "failure_kind": "source_metadata_mismatch",
                    "failure_reason": (
                        "The authoritative published date is outside the requested window."
                    ),
                }
            )

    def test_non_date_failure_does_not_disqualify(self) -> None:
        self.assertFalse(
            _date_failure_disqualifies(
                {
                    "failure_kind": "infrastructure",
                    "failure_reason": "The upstream source returned HTTP 503.",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
