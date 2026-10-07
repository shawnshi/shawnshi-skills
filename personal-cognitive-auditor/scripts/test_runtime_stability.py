"""Synthetic regressions for deterministic audit failures and local scope checks."""
import subprocess
import sys
import tempfile
import unittest
from itertools import permutations
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import audit_gate as gate

VALID_ACQUISITION = (
    'sync_eligible=false; sync_attempted=not_attempted; task_status=not_checked; '
    'local_reread=accepted; local_status=partial; live_fallback=not_used; reason=readonly_request'
)


class RuntimeStabilityTests(unittest.TestCase):
    def test_duplicate_acquisition_keys_cannot_override_an_earlier_value(self):
        for prefix in ('sync_eligible=true; ', 'sync_eligible=false; '):
            with self.subTest(prefix=prefix):
                errors = gate.acquisition_semantic_errors(prefix + VALID_ACQUISITION)
                self.assertTrue(any('duplicate' in error for error in errors), errors)

    def test_unhashable_period_types_return_validation_errors(self):
        for value in ([], {}, ['weekly']):
            with self.subTest(value=value):
                errors = gate.validate_handoff_payload({'period_type': value})
                self.assertTrue(any('period_type' in error for error in errors))

    def test_shared_upstream_warning_keeps_order_independent_semantics(self):
        terms = ('Body Battery', '睡眠评分', '独立证据')
        for ordering in permutations(terms):
            with self.subTest(ordering=ordering):
                self.assertIsNotNone(gate.SHARED_UPSTREAM_OVERCLAIM.search('\n'.join(ordering)))
        for omitted in terms:
            with self.subTest(omitted=omitted):
                self.assertIsNone(gate.SHARED_UPSTREAM_OVERCLAIM.search(' '.join(t for t in terms if t != omitted)))

    def test_audit_file_size_is_bounded_before_decoding(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'audit.md'
            path.write_bytes(b'x' * 17)
            with patch.object(gate, 'MAX_AUDIT_BYTES', 16, create=True):
                with self.assertRaisesRegex(ValueError, 'limit'):
                    gate.load_text(path)

    def test_invalid_utf8_cli_fails_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'audit.md'
            path.write_bytes(b'\xff')
            result = subprocess.run([sys.executable, str(SCRIPT_DIR / 'audit_gate.py'), str(path)],
                                    capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Traceback', result.stdout + result.stderr)
        self.assertIn('UTF-8', result.stdout + result.stderr)

    def test_partial_scope_preserves_two_clause_radius(self):
        for gap in range(5):
            text = 'local_status=partial。' + '普通内容。' * gap + '云端回退。'
            with self.subTest(gap=gap):
                self.assertEqual(gate.has_partial_cloud_fallback(text), gap <= 1)
        self.assertFalse(gate.has_partial_cloud_fallback(VALID_ACQUISITION))


if __name__ == '__main__':
    unittest.main()
