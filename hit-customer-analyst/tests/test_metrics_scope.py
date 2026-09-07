"""Observed measurement boundaries and request-count semantics (R04)."""
import json
import tempfile
import unittest
from pathlib import Path
from tests.common import SCRIPTS, run_python

class MetricsScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session = self.root / 'session.json'
        self.call('start')

    def call(self, op, *args, success=True):
        result = run_python('run_metrics.py', [op, str(self.session), *args])
        self.assertEqual(result.returncode, 0 if success else 2, result.stderr)
        return json.loads(result.stdout) if success else result

    def candidate(self):
        candidate = self.root / 'candidate'
        runtime = candidate / 'runtime'
        runtime.mkdir(parents=True)
        (runtime / 'candidate-base.json').write_text(json.dumps({'workspace': str(self.root / 'formal')}))
        (runtime / 'manifest.json').write_text(json.dumps({'context_id': 'context-test', 'latest_run_id': 'run-test', 'business_mode': 'briefing'}))
        return candidate

    def test_start_scope_and_unknown_tokens(self):
        data = json.loads(self.session.read_text())
        self.assertEqual(data['measurement_scope'], 'post_skill_read_to_validation_or_safe_stop')
        self.assertIn('Business original-source', data['counter_semantics']['sources_opened'])
        self.assertIn('before_start_including_skill_read', data['coverage_exclusions'])
        self.assertIn('final_response', data['coverage_exclusions'])
        self.assertIsNone(data['counters']['input_tokens'])
        self.assertIsNone(data['counters']['output_tokens'])
        self.call('start', success=False)

    def test_only_business_reads_increment_sources_opened(self):
        data = self.call('record', '--event', 'hash_bytes_read=8', '--event', 'rule_read=3')
        self.assertEqual(data['counters']['sources_opened'], 0)
        self.assertNotIn('sources_opened', data['observed_counters'])
        data = self.call('record', '--event', 'business_source_open=2', '--count', 'queries_executed=3')
        self.assertEqual(data['counters']['sources_opened'], 2)
        self.assertEqual(data['event_counts'], {'hash_bytes_read': 8, 'rule_read': 3, 'business_source_open': 2})
        self.assertIsNone(data['counters']['input_tokens'])
        before = self.session.read_bytes()
        self.call('record', '--count', 'sources_opened=1', '--event', 'business_source_open=1', success=False)
        self.call('record', '--event', 'rule_read=-1', success=False)
        self.assertEqual(before, self.session.read_bytes())

    def test_finish_means_validation_or_safe_stop_and_is_idempotent(self):
        data = self.call('finish', '--reason', 'safe_stop')
        self.assertEqual(data['finish_reason'], 'safe_stop')
        self.assertGreaterEqual(data['elapsed_ms'], 0)
        self.assertEqual(data, self.call('finish'))
        self.call('record', '--count', 'queries_executed=1', success=False)
        self.call('attach', '--candidate', str(self.candidate()), success=False)

    def test_snapshot_scope_schema_and_legacy_compatibility(self):
        schema = json.loads((SCRIPTS.parent / 'schemas/run-metrics.schema.json').read_text())
        def validate_contract(value):
            # Exercise the compatibility boundary without third-party dependencies.
            self.assertFalse(schema['additionalProperties'])
            self.assertLessEqual(set(value), set(schema['properties']))
            self.assertLessEqual(set(schema['required']), set(value))
            self.assertLessEqual(set(schema['properties']['counters']['required']), set(value['counters']))
            if 'measurement_scope' in value:
                self.assertIn(value['measurement_scope'], schema['properties']['measurement_scope']['enum'])
        candidate = self.candidate()
        self.call('record', '--event', 'business_source_open=2')
        before = self.session.read_bytes()
        self.call('attach', '--candidate', str(candidate))
        self.assertEqual(before, self.session.read_bytes())
        snapshot = json.loads((candidate / 'runtime/run-metrics.json').read_text())
        validate_contract(snapshot)
        self.assertEqual(snapshot['measurement_scope'], 'post_skill_read_to_precommit_snapshot')
        self.assertIn('commit_and_post_snapshot_work', snapshot['coverage_exclusions'])
        self.assertIn('input_tokens', snapshot['unmeasured_counters'])
        self.assertNotIn('sources_opened', snapshot['unmeasured_counters'])
        legacy = {k: v for k, v in snapshot.items() if k not in ('measurement_scope', 'coverage_exclusions', 'counter_semantics', 'event_counts')}
        validate_contract(legacy)
        session = json.loads(self.session.read_text())
        for key in ('measurement_scope', 'coverage_exclusions', 'counter_semantics', 'event_counts'):
            session.pop(key)
        session['counters']['input_tokens'] = 0  # Unobserved compatibility zero is unknown.
        self.session.write_text(json.dumps(session))
        self.call('attach', '--candidate', str(candidate))
        migrated = json.loads((candidate / 'runtime/run-metrics.json').read_text())
        self.assertEqual(migrated['measurement_scope'], 'legacy_recorded_start_to_precommit_snapshot')
        self.assertIsNone(migrated['counters']['input_tokens'])
        validate_contract(migrated)

    def test_known_tokens_require_explicit_observation(self):
        data = self.call('record', '--count', 'input_tokens=12', '--count', 'output_tokens=0')
        self.assertEqual(data['counters']['input_tokens'], 12)
        self.assertEqual(data['counters']['output_tokens'], 0)
        self.assertIn('output_tokens', data['observed_counters'])
        data = self.call('finish')
        self.assertEqual(data['finish_reason'], 'validation_complete')

    def test_legacy_attach_preserves_counts_without_inventing_semantics(self):
        # Actual pre-scope v1 session shape, with a historical mixed read count.
        counters = json.loads(self.session.read_text())['counters']
        counters['sources_opened'] = 13
        legacy = {
            'schema': 'discovery-call-session-timing/v1',
            'started_at': '2026-09-07T00:00:00+00:00',
            'ended_at': None,
            'observed_counters': ['sources_opened'],
            'counters': counters,
        }
        self.session.write_text(json.dumps(legacy))
        before = self.session.read_bytes()
        candidate = self.candidate()
        self.call('attach', '--candidate', str(candidate))
        snapshot = json.loads((candidate / 'runtime/run-metrics.json').read_text())
        self.assertEqual(before, self.session.read_bytes())
        self.assertEqual(snapshot['counters']['sources_opened'], 13)
        self.assertIn('Unknown legacy', snapshot['counter_semantics']['sources_opened'])
        self.assertNotIn('Business original-source', snapshot['counter_semantics']['sources_opened'])
        self.assertIn('Default event zeros are unmeasured', snapshot['counter_semantics']['events'])
        self.assertEqual(snapshot['coverage_exclusions'], ['before_recorded_start', 'commit_and_post_snapshot_work'])
        # New increments cannot retroactively certify the historical aggregate.
        self.call('record', '--event', 'business_source_open=2')
        self.call('attach', '--candidate', str(candidate))
        updated = json.loads((candidate / 'runtime/run-metrics.json').read_text())
        self.assertEqual(updated['counters']['sources_opened'], 15)
        self.assertIn('Unknown legacy', updated['counter_semantics']['sources_opened'])
