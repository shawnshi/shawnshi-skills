"""手工档覆盖审计的合约测试（合成临时目录，不读真实组合或 Dashboard）。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import manual_boundary_audit as mba  # noqa: E402


def _boundary(boundary_id, role, operator, value):
    return {
        "boundary_id": boundary_id,
        "role": role,
        "operator": operator,
        "value": value,
        "currency": "CNY",
        "quote_basis": "regular_market_price",
        "authority_status": "user_confirmed",
        "source_tier": "user_authorized",
        "source_locator": "dataset://pia/user-policy/601899.ss/20260805",
        "as_of_date": "2026-08-05",
    }


def build_fixture(tmp):
    root = Path(tmp) / "stocks"
    root.mkdir(parents=True)
    (root / "dashboard_index.json").write_text(
        json.dumps({"dashboards": {"601899.SS": {"generation_id": "g1"}}}), encoding="utf-8"
    )
    pinned = root / "601899.SS" / "generations" / "g1"
    pinned.mkdir(parents=True)
    (pinned / "dashboard.json").write_text(
        json.dumps({"monitoring_boundaries": {"boundaries": [_boundary("b-down", "downside_boundary", "lte", 30.5)]}}),
        encoding="utf-8",
    )
    archived = root / "601899.SS" / "generations" / "g0"
    archived.mkdir(parents=True)
    (archived / "dashboard.json").write_text(
        json.dumps({"monitoring_boundaries": {"boundaries": [_boundary("b-old", "upside_boundary", "gte", 40.3)]}}),
        encoding="utf-8",
    )
    run = Path(tmp) / "run"
    out = run / "out"
    out.mkdir(parents=True)
    (out / "daily_sync.json").write_text(
        json.dumps({"quote_snapshot": [{"symbol": "601899.SS", "current_price": 29.79,
                                        "as_of": "2026-09-30T07:00:00+00:00", "source": "Yahoo Finance"}]}),
        encoding="utf-8",
    )
    (out / "position_limits.json").write_text(
        json.dumps({"proximity_policy": {"value": 0.02}}), encoding="utf-8"
    )
    return root, run


class ManualBoundaryAuditTest(unittest.TestCase):
    def test_reports_crossing_and_archived_only_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, run = build_fixture(tmp)
            payload = mba.audit(root, run)
            self.assertEqual([r["boundary_id"] for r in payload["crossed"]], ["b-down"])
            self.assertEqual(payload["manual_boundary_count"], 2)
            self.assertEqual(sorted(payload["missed_by_run"]), ["b-down", "b-old"])
            self.assertEqual(payload["proximity_value"], 0.02)
            self.assertEqual([g["code"] for g in payload["gaps"]], ["manual_boundary_coverage_gap"])
            self.assertEqual(payload["gaps"][0]["boundaries"], ["601899.SS:b-old"])

    def test_near_status_uses_explicit_proximity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, run = build_fixture(tmp)
            (run / "out" / "daily_sync.json").write_text(
                json.dumps({"quote_snapshot": [{"symbol": "601899.SS", "current_price": 31.0,
                                                "as_of": "x", "source": "y"}]}),
                encoding="utf-8",
            )
            payload = mba.audit(root, run)
            self.assertEqual([r["boundary_id"] for r in payload["near"]], ["b-down"])
            self.assertEqual(payload["crossed"], [])

    def test_missing_near_rule_is_reported_as_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, run = build_fixture(tmp)
            (run / "out" / "position_limits.json").unlink()
            payload = mba.audit(root, run)
            self.assertIsNone(payload["proximity_value"])
            self.assertIn("near_rule_undefined", [g["code"] for g in payload["gaps"]])

    def test_fails_closed_without_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, run = build_fixture(tmp)
            (root / "dashboard_index.json").unlink()
            with self.assertRaises(mba.AuditError):
                mba.audit(root, run)


if __name__ == "__main__":
    unittest.main()
