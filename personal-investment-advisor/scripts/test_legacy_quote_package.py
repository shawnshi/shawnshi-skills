import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_sync
import legacy_quote_package as adapter
from portfolio_loader import load_positions
from quote_evidence_contract import (
    MAX_QUOTE_FUTURE_SKEW_SECONDS, build_portfolio_snapshot_binding,
)

NOW = 1_800_000_000.0


class LegacyQuotePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.positions_path = self.root / 'positions.json'
        self.positions_path.write_text(json.dumps({
            'base_currency': 'USD', 'exchange_rates': {'USD': 1.0},
            'positions': [{'symbol': 'AAPL', 'name': 'Apple', 'quantity': 2,
                           'avg_cost': 100.0, 'currency': 'USD',
                           'market': 'US', 'asset_type': 'stock'}],
        }), encoding='utf-8')
        self.portfolio = load_positions(str(self.positions_path))
        self.records = [{
            'query': 'AAPL', 'symbol': 'AAPL',
            'info': {'symbol': 'AAPL', 'currency': 'USD', 'exchange': 'NMS',
                     'quoteType': 'EQUITY', 'marketState': 'CLOSED',
                     'regularMarketPrice': 101.1234567, 'regularMarketTime': NOW - 60},
            'history': [{'Close': 999.0}], 'summary': {'last_close': 999.0},
            'data_sources': {'price': 'Yahoo Finance', 'info': 'Yahoo Finance',
                             'price_locator': 'yfinance:AAPL:history',
                             'price_adjustment': 'provider_default'},
            'portfolio_context': {'position_status': 'matched',
                                  'current_price': 101.1234567, 'currency': 'USD'},
            'portfolio_batch_audit': {'complete': True,
                'portfolio_snapshot_binding': build_portfolio_snapshot_binding(self.portfolio)},
        }]

    def build(self):
        return adapter.build_legacy_quote_package(
            self.records, self.portfolio, now_epoch=NOW,
            source_binding={'path': 'legacy.json', 'sha256': 'a' * 64})

    def test_quote_from_info_preserves_history_and_source_lineage(self):
        original = copy.deepcopy(self.records)
        with patch('yf._call_yahoo', side_effect=AssertionError('network forbidden')):
            package = self.build()
        row = package['records'][0]
        self.assertTrue(package['portfolio_batch_audit']['complete'])
        self.assertEqual(self.records, original)
        self.assertEqual(row['info'], original[0]['info'])
        self.assertEqual(row['history'], original[0]['history'])
        self.assertEqual(row['legacy_history_data_sources'], original[0]['data_sources'])
        self.assertEqual(row['data_sources']['price_locator'], 'yfinance:AAPL:quote')
        self.assertEqual(row['quote_derivation']['selected_observation']['price'], 101.1234567)
        self.assertEqual(row['quote_derivation']['selected_observation']['epoch'], NOW - 60)
        self.assertFalse(row['quote_derivation']['history_values_used_for_quote'])

    def test_missing_price_never_uses_history(self):
        del self.records[0]['info']['regularMarketPrice']
        with self.assertRaisesRegex(ValueError, 'no history fallback'):
            self.build()

    def test_missing_time_never_uses_capture_time(self):
        del self.records[0]['info']['regularMarketTime']
        with self.assertRaisesRegex(ValueError, 'timestamped info quote required'):
            self.build()

    def test_changed_portfolio_price_rejected(self):
        self.records[0]['portfolio_context']['current_price'] = 999.0
        with self.assertRaisesRegex(ValueError, 'not the selected info observation'):
            self.build()

    def test_other_provider_not_relabelled(self):
        self.records[0]['data_sources']['info'] = 'Other provider'
        with self.assertRaisesRegex(ValueError, 'unsupported source'):
            self.build()

    def test_secondary_source_not_promoted(self):
        self.records[0]['quote_provenance'] = {'tier': 'secondary'}
        with self.assertRaisesRegex(ValueError, 'unsupported source'):
            self.build()

    def test_invalid_quotes_remain_rejected_by_native_audit(self):
        cases = [('regularMarketTime', NOW - 1_000_000),
                 ('regularMarketTime', NOW + MAX_QUOTE_FUTURE_SKEW_SECONDS + 1), ('currency', 'CNY'),
                 ('symbol', 'GOOG'), ('marketState', 'UNKNOWN')]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                original = copy.deepcopy(self.records)
                self.records[0]['info'][key] = value
                self.assertFalse(self.build()['portfolio_batch_audit']['complete'])
                self.records = original

    def test_existing_future_skew_boundary_is_not_changed(self):
        self.records[0]['info']['regularMarketTime'] = NOW + MAX_QUOTE_FUTURE_SKEW_SECONDS
        self.assertTrue(self.build()['portfolio_batch_audit']['complete'])

    def test_position_binding_cannot_be_replaced(self):
        self.records[0]['portfolio_batch_audit']['portfolio_snapshot_binding'] = {}
        with self.assertRaisesRegex(ValueError, 'not bound'):
            self.build()

    def test_conflicting_archived_audits_rejected(self):
        row = copy.deepcopy(self.records[0])
        row['portfolio_batch_audit']['complete'] = False
        self.records.append(row)
        with self.assertRaisesRegex(ValueError, 'audits disagree'):
            self.build()

    def test_extended_session_uses_its_own_pair(self):
        self.records[0]['info'].update(marketState='PRE', preMarketPrice=102.5,
                                       preMarketTime=NOW - 20)
        self.records[0]['portfolio_context']['current_price'] = 102.5
        package = self.build()
        observation = package['records'][0]['quote_derivation']['selected_observation']
        self.assertEqual(observation['session'], 'PRE')
        self.assertEqual(observation['price'], 102.5)
        self.assertEqual(observation['epoch'], NOW - 20)
        self.assertTrue(package['portfolio_batch_audit']['complete'])

    def test_existing_offline_daily_sync_accepts_quote_scope_only(self):
        path = self.root / 'quotes.json'
        path.write_text(json.dumps(self.build()), encoding='utf-8')
        report = daily_sync.evaluate_daily_sync(
            positions_file=str(self.positions_path), quotes_file=str(path), now_epoch=NOW)
        self.assertTrue(report['completeness']['complete'])
        self.assertTrue(report['completeness']['identity_complete'])
        self.assertFalse(report['completeness']['thesis_assessment_complete'])
        self.assertEqual(report['status'], 'incomplete')


if __name__ == '__main__':
    unittest.main()
