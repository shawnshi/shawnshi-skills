"""Synthetic provider stability oracles; never call live providers."""
import contextlib
import io
import json
import multiprocessing
import os
import pickle
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import akshare_fetcher as akf
import provider_runtime as runtime
import quality_screener as quality
import yf


def synthetic_provider(mode, counter=None):
    if counter:
        path = Path(counter)
        count = int(path.read_text()) + 1 if path.exists() else 1
        path.write_text(str(count))
    else:
        count = 1
    if mode == 'hang':
        time.sleep(60)
    if mode == 'permission':
        raise PermissionError(13, 'synthetic denied')
    if mode == 'programming':
        raise TypeError('synthetic bad signature')
    if mode == 'transient' and count < 3:
        raise ConnectionError('synthetic disconnected')
    if mode == 'eof':
        os._exit(0)
    if mode == 'empty':
        return pd.DataFrame()
    if mode == 'large':
        return 'x' * 70000
    if mode == 'frame':
        frame = pd.DataFrame({'Close': [1.25]}, index=pd.to_datetime(['2026-01-02']))
        frame.index.name = 'Date'
        frame.attrs['pia_source'] = 'synthetic'
        return frame
    if mode == 'nested':
        return runtime.run_provider(synthetic_provider, 'permission')
    return {'symbol': mode, 'count': count}


class DiagnosticTests(unittest.TestCase):
    def test_sensitive_assignments_redact_entire_value_and_remaining_region(self):
        cases = [
            'Authorization: Bearer SYNTHETIC_CREDENTIAL',
            'Authorization: Basic SYNTHETIC_CREDENTIAL extra words',
            '"Authorization": "Bearer SYNTHETIC_CREDENTIAL"',
            "'Authorization': 'Basic SYNTHETIC_CREDENTIAL'",
            '{"password": "SYNTHETIC_CREDENTIAL"}',
            "{'password': 'SYNTHETIC_CREDENTIAL with spaces'}",
            '{"password": "escaped \\" quote SYNTHETIC_CREDENTIAL"}',
            "{'secret': 'escaped \\' quote SYNTHETIC_CREDENTIAL'}",
            'password = SYNTHETIC_CREDENTIAL with spaces; later context',
            'password\n :\n SYNTHETIC_CREDENTIAL\ncontinued value',
            '"Authorization"\n:\n"Bearer SYNTHETIC_CREDENTIAL"',
            'access_token=SYNTHETIC_CREDENTIAL',
            'client_secret=SYNTHETIC_CREDENTIAL',
        ]
        cases.extend(f'{{"{key}": "SYNTHETIC_CREDENTIAL with spaces"}}' for key in (
            'token', 'secret', 'api_key', 'api-key', 'apikey', 'PASSWORD', 'Authorization',
        ))
        for text in cases:
            with self.subTest(text=text):
                result = runtime.safe_diagnostic('safe prefix; ' + text + ' tail context')
                self.assertTrue(result.startswith('safe prefix; '))
                self.assertTrue(result.endswith('<redacted>'), result)
                for secret in ('SYNTHETIC_CREDENTIAL', 'Bearer', 'Basic', 'with spaces', 'tail context'):
                    self.assertNotIn(secret, result)

    def test_redaction_precedes_output_truncation(self):
        for size in (475, 485, 495, 500, 4090, 5000):
            with self.subTest(size=size):
                result = runtime.safe_diagnostic('x' * size + ' password="SYNTHETIC_CREDENTIAL with spaces"')
                self.assertLessEqual(len(result), 500)
                self.assertNotIn('SYNTHETIC', result)
        self.assertEqual(runtime.safe_diagnostic('x' * 5000), 'x' * 500)

    def test_unrelated_diagnostics_and_scalars_are_preserved(self):
        for value in ('HTTP 429 rate limited; request_id=42', '{"status": "retry later", "attempt": 2}', 'tokenization failed', 429, 1.25):
            with self.subTest(value=value):
                self.assertEqual(runtime.safe_diagnostic(value), str(value))
        self.assertEqual(runtime.safe_diagnostic('line one\nline two\rline three'), 'line one line two line three')

    def test_error_and_provider_code_share_sanitizer_and_keep_safe_metadata(self):
        message = '{"password": "SYNTHETIC_CREDENTIAL"}'
        try:
            raise PermissionError(13, message)
        except PermissionError as exc:
            exc.__dict__.update(code=message)
            result = runtime.error_outcome(exc)
            self.assertEqual(result['error'], runtime.safe_diagnostic(exc))
        self.assertEqual(result['provider_code'], runtime.safe_diagnostic(message))
        self.assertNotIn('SYNTHETIC_CREDENTIAL', json.dumps(result))
        self.assertEqual(result['error_type'], 'PermissionError')
        self.assertEqual(result['error_module'], 'builtins')
        self.assertEqual(result['errno'], 13)
        self.assertFalse(result['retryable'])
        self.assertTrue(result['traceback'])
        for frame in result['traceback']:
            self.assertEqual(set(frame), {'file', 'line', 'function'})
            self.assertEqual(frame['file'], Path(__file__).name)
            self.assertGreater(frame['line'], 0)
            self.assertEqual(frame['function'], self._testMethodName)

    def test_conversion_failures_and_unknown_objects_do_not_use_fallback_repr(self):
        class UnsafeValue:
            def __str__(self):
                raise AssertionError('SYNTHETIC_CREDENTIAL')

            def __repr__(self):
                raise AssertionError('repr must not run')

        class UnprintableError(RuntimeError):
            def __str__(self):
                raise ValueError('SYNTHETIC_CREDENTIAL')

            def __repr__(self):
                raise AssertionError('repr must not run')

        self.assertEqual(runtime.safe_diagnostic(UnsafeValue()), '<diagnostic omitted>')
        exc = UnprintableError()
        exc.__dict__.update(code=UnsafeValue())
        outcome = runtime.error_outcome(exc)
        self.assertEqual(outcome['error'], '<diagnostic unavailable>')
        self.assertEqual(outcome['provider_code'], '<diagnostic omitted>')
        self.assertFalse(outcome['retryable'])
        self.assertNotIn('SYNTHETIC_CREDENTIAL', json.dumps(outcome))

    def test_http_status_normalization_and_precedence_match_retry_classification(self):
        from http import HTTPStatus
        from types import SimpleNamespace
        cases = [
            (None, None, 429, 429, True),
            (None, None, HTTPStatus.TOO_MANY_REQUESTS, 429, True),
            (None, None, ' 429 ', 429, True),
            (503, 400, 429, 503, True),
            (400, 503, 429, 400, False),
            (None, 429, 400, 429, True),
            ('invalid', '503', 400, 503, True),
            (True, False, 429, 429, True),
        ]
        for response_status, status_code, status, expected, retryable in cases:
            with self.subTest(response_status=response_status, status_code=status_code, status=status):
                exc = RuntimeError('synthetic HTTP failure')
                exc.__dict__.update(response=SimpleNamespace(status_code=response_status), status_code=status_code, status=status)
                with patch.object(runtime, '_http_status', wraps=runtime._http_status) as extract:
                    outcome = runtime.error_outcome(exc)
                extract.assert_called_once_with(exc)
                self.assertEqual(outcome['http_status'], expected)
                self.assertEqual(outcome['retryable'], retryable)
                self.assertEqual(runtime.is_retryable_error(exc), retryable)

    def test_invalid_http_statuses_do_not_create_retry_evidence(self):
        for status in (True, False, 'arbitrary', '429 rate limited', 429.0, '429.0', '４２９', 99, 600, -429, {}, None):
            with self.subTest(status=status):
                exc = RuntimeError('synthetic failure')
                exc.__dict__.update(status=status)
                outcome = runtime.error_outcome(exc)
                self.assertIsNone(outcome['http_status'])
                self.assertFalse(outcome['retryable'])

    def test_typed_transient_and_permanent_rules_remain_in_force(self):
        for exc, expected in ((ConnectionError('disconnected'), True), (TimeoutError('expired'), True), (PermissionError('denied'), False), (ValueError('bad input'), False), (ConnectionError('token=x certificate verify failed'), False)):
            exc.__dict__.update(status='invalid')
            self.assertEqual(runtime.error_outcome(exc)['retryable'], expected)
        exc = PermissionError('denied')
        exc.__dict__.update(status=429)
        self.assertFalse(runtime.error_outcome(exc)['retryable'])
        exc = RuntimeError('rate limited')
        exc.__dict__.update(status=429)
        outcome = runtime.error_outcome(exc, phase='ipc_read')
        self.assertEqual(outcome['http_status'], 429)
        self.assertFalse(outcome['retryable'])


class EnhancementTests(unittest.TestCase):
    def test_quote_error_and_chip_value_never_complete(self):
        fetcher = akf.StandaloneDataFetcher(0, 0)
        with patch.object(fetcher, '_fetch_quote_ef', side_effect=PermissionError('synthetic denied')), patch.object(
            fetcher, '_fetch_chip_distribution_ak', return_value=pd.DataFrame([{'获利比例': .5}])
        ):
            metrics = fetcher.get_enhanced_metrics('600519')
        payload = akf._enhanced_payload('600519', metrics, akf._utc_now())
        self.assertEqual(payload['status'], 'data_error')
        self.assertEqual(metrics['profit_ratio'], .5)
        self.assertEqual(metrics['provider_outcomes']['quote']['error_type'], 'PermissionError')
        self.assertEqual(metrics['evidence_status'], 'partial')

    def test_explicit_skip_chip_changes_required_scope_only(self):
        fetcher = akf.StandaloneDataFetcher(0, 0)
        with patch.object(fetcher, '_fetch_quote_ef', return_value=pd.DataFrame([{'量比': 1.2, '换手率': 2.1}])), patch.object(fetcher, '_fetch_chip_distribution_ak') as chips:
            metrics = fetcher.get_enhanced_metrics('600519', skip_chip_dist=True)
        chips.assert_not_called()
        self.assertEqual(metrics['required_metrics'], ['volume_ratio', 'turnover_rate'])
        self.assertEqual(akf._enhanced_payload('600519', metrics, akf._utc_now())['status'], 'complete')

    def test_real_empty_and_all_success_and_partial_required_fields(self):
        fetcher = akf.StandaloneDataFetcher(0, 0)
        for quote, chips, expected in [
            (pd.DataFrame(), pd.DataFrame(), 'insufficient_data'),
            (pd.DataFrame([{'量比': 1.2, '换手率': 2.1}]), pd.DataFrame([{'获利比例': .5, '平均成本': 12, '90%筹码集中度': .2}]), 'complete'),
            (pd.DataFrame([{'量比': 1.2}]), pd.DataFrame([{'获利比例': .5}]), 'insufficient_data'),
        ]:
            with self.subTest(expected=expected), patch.object(fetcher, '_fetch_quote_ef', return_value=quote), patch.object(fetcher, '_fetch_chip_distribution_ak', return_value=chips):
                metrics = fetcher.get_enhanced_metrics('600519')
                self.assertEqual(akf._enhanced_payload('600519', metrics, akf._utc_now())['status'], expected)


def synthetic_ipc_worker(function, args, kwargs, directory, limit):
    path = Path(directory) / 'result'
    mode = args[0]
    if mode == 'truncated':
        path.write_bytes(b'\x80\x05')
    elif mode == 'oversize':
        path.write_bytes(b'x' * (limit + 1))
    elif mode == 'trailing':
        path.write_bytes(pickle.dumps({'status': 'ok', 'data': {}}) + b'extra')
    else:
        path.write_bytes(pickle.dumps({'status': 'ok'}))


def synthetic_history(provider, symbol, **kwargs):
    if symbol == '111111':
        raise ConnectionError('synthetic history transport failure')
    return pd.DataFrame([{'日期': '2026-01-02', '开盘': 1, '收盘': 2, '最高': 3, '最低': 1, '成交量': 100}])


def synthetic_yahoo(symbol, operation, cache_dir=None, **kwargs):
    if symbol == 'HANG':
        time.sleep(60)
    if symbol == 'DENIED':
        raise PermissionError('synthetic denied')
    return {'symbol': symbol, 'regularMarketPrice': 10.1234, 'quoteType': 'EQUITY'}


class ProviderRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.children = {p.pid for p in multiprocessing.active_children()}
        self.directory = tempfile.TemporaryDirectory(prefix='pia-runtime-test-')
        self.addCleanup(self.directory.cleanup)
        self.old_tempdir = tempfile.tempdir
        tempfile.tempdir = self.directory.name
        self.addCleanup(setattr, tempfile, 'tempdir', self.old_tempdir)

    def tearDown(self):
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, self.children)
        self.assertEqual(list(Path(self.directory.name).glob('pia-provider-*')), [])

    def test_spawn_permission_and_programming_errors_make_one_actual_call(self):
        for mode, category in [('permission', 'PermissionError'), ('programming', 'TypeError')]:
            counter = str(Path(self.directory.name) / mode)
            result = runtime.run_provider(synthetic_provider, mode, counter, timeout_seconds=8)
            self.assertEqual(result['status'], 'error', result)
            self.assertEqual(result['error_type'], category)
            self.assertEqual(result['attempts'], 1)
            self.assertEqual(Path(counter).read_text(), '1')
            self.assertTrue(result['traceback'])
        self.assertEqual(result['phase'], 'provider')

    def test_transient_three_actual_calls_share_deadline(self):
        counter = str(Path(self.directory.name) / 'transient')
        result = runtime.run_provider(synthetic_provider, 'transient', counter, timeout_seconds=10)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['attempts'], 3)
        self.assertEqual(Path(counter).read_text(), '3')
        self.assertEqual(result['data']['count'], 3)
        self.assertLess(result['elapsed_seconds'], 10)

    def test_hung_provider_is_killed_with_bounded_wall_time(self):
        counter = str(Path(self.directory.name) / 'hung')
        start = time.monotonic()
        result = runtime.run_provider(synthetic_provider, 'hang', counter, timeout_seconds=8)
        self.assertEqual(result['status'], 'timeout', result)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(result['attempts'], 1)
        self.assertEqual(Path(counter).read_text(), '1')

    def test_real_empty_frame_and_dataframe_metadata_survive_spawn(self):
        empty = runtime.run_provider(synthetic_provider, 'empty', timeout_seconds=8)
        self.assertEqual(empty['status'], 'no_data')
        result = runtime.run_provider(synthetic_provider, 'frame', timeout_seconds=8)
        self.assertEqual(result['status'], 'ok', result)
        pd.testing.assert_frame_equal(result['data'], synthetic_provider('frame'))
        self.assertEqual(result['data'].attrs, {'pia_source': 'synthetic'})

    def test_eof_spawn_denied_and_disk_failure_are_not_no_data(self):
        result = runtime.run_provider(synthetic_provider, 'eof', timeout_seconds=8)
        self.assertEqual(result['error_type'], 'EOFError', result)
        with patch.object(runtime.multiprocessing, 'get_context') as context:
            process = context.return_value.Process.return_value
            process.start.side_effect = PermissionError(13, 'synthetic spawn denied')
            result = runtime.run_provider(synthetic_provider, 'ok')
            self.assertEqual(result['error_type'], 'PermissionError')
            self.assertEqual(result['phase'], 'spawn')
            self.assertEqual(result['attempts'], 1)
            process.start.assert_called_once()
            process.close.assert_called_once()
        with patch.object(runtime.tempfile, 'TemporaryDirectory', side_effect=PermissionError('synthetic disk denied')):
            result = runtime.run_provider(synthetic_provider, 'ok')
        self.assertEqual(result['phase'], 'cleanup_or_storage')
        self.assertEqual(result['status'], 'error')

    def test_truncated_malformed_oversize_and_trailing_ipc_rejected(self):
        for mode in ['truncated', 'malformed', 'oversize', 'trailing']:
            with self.subTest(mode=mode), patch.object(runtime, '_child_call', synthetic_ipc_worker), patch.object(runtime, 'MAX_IPC_BYTES', 65536):
                result = runtime.run_provider(synthetic_provider, mode, timeout_seconds=8)
            self.assertEqual(result['status'], 'error', result)
            self.assertEqual(result['phase'], 'ipc_read')
            self.assertEqual(result['attempts'], 1)

    def test_child_serialization_cap_is_separate_operation_error(self):
        with patch.object(runtime, 'MAX_IPC_BYTES', 65536):
            result = runtime.run_provider(synthetic_provider, 'large', timeout_seconds=8)
        self.assertEqual(result['phase'], 'ipc_write', result)
        self.assertEqual(result['error'], 'provider_ipc_size_limit')
        self.assertEqual(result['status'], 'error')

    def test_nested_runtime_is_rejected_without_another_provider(self):
        result = runtime.run_provider(synthetic_provider, 'nested', timeout_seconds=8)
        self.assertEqual(result['data']['status'], 'error', result)
        self.assertEqual(result['data']['error'], 'nested_provider_runtime_forbidden')

    def test_backoff_does_not_cross_remaining_deadline(self):
        with patch.object(runtime, '_one_attempt', return_value=runtime.error_outcome(ConnectionError('temporary'))), patch.object(runtime.time, 'sleep') as sleep:
            result = runtime.run_provider(synthetic_provider, 'ok', timeout_seconds=.01)
        sleep.assert_not_called()
        self.assertEqual(result['attempts'], 1)
        self.assertEqual(result['retry_budget_exhausted'], 'deadline')

    def test_diagnostics_keep_category_but_redact_credentials_and_urls(self):
        outcome = runtime.error_outcome(PermissionError(13, 'token=synthetic_value https://example.invalid/private'))
        self.assertEqual(outcome['error_type'], 'PermissionError')
        self.assertEqual(outcome['errno'], 13)
        self.assertNotIn('synthetic_value', outcome['error'])
        self.assertNotIn('example.invalid', outcome['error'])

    def test_cleanup_kill_fallback_is_bounded(self):
        from unittest.mock import Mock
        process = Mock()
        process.is_alive.side_effect = [True, True, False]
        runtime._reap(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual([call.kwargs for call in process.join.call_args_list], [{'timeout': 1.0}, {'timeout': 1.0}])
        process.close.assert_called_once()

    def test_yf_akshare_nested_transient_total_is_three_and_no_fallback(self):
        with patch.object(akf, '_provider_frame', synthetic_history), patch.object(yf, '_call_yahoo') as fallback:
            result = yf.get_stock_data('111111.SS', fetch_info=False, fetch_news=False, a_share_history_source='auto')
        outcome = json.loads(result[3][0].split('failed: ', 1)[1])
        self.assertEqual(outcome['attempts'], 3, outcome)
        self.assertEqual(outcome['error_type'], 'ConnectionError')
        fallback.assert_not_called()

    def test_yf_history_source_and_values_survive_spawn(self):
        with patch.object(akf, '_provider_frame', synthetic_history):
            history, _, _, errors = yf.get_stock_data('600519.SS', fetch_info=False, fetch_news=False, a_share_history_source='akshare')
        self.assertEqual(errors, [])
        self.assertEqual(history['Close'].tolist(), [2])
        self.assertEqual(history.attrs['pia_source'], 'Akshare')
        self.assertEqual(history.attrs['pia_provider_outcome']['attempts'], 1)

    def test_daily_batch_hung_symbol_does_not_block_independent_quotes(self):
        real_run = runtime.run_provider
        def bounded(function, *args, **kwargs):
            kwargs['timeout_seconds'] = 8.0
            return real_run(function, *args, **kwargs)
        start = time.monotonic()
        with patch.object(yf, '_yahoo_provider', synthetic_yahoo), patch.object(yf, 'run_provider', side_effect=bounded):
            results = yf.fetch_daily_sync_batch(['HANG', 'OK', 'DENIED', 'LAST', 'OK'], max_workers=4)
        self.assertEqual(list(results), ['HANG', 'OK', 'DENIED', 'LAST'])
        self.assertLess(time.monotonic()-start, 10)
        self.assertIn('timeout', results['HANG'][3][0])
        self.assertIn('PermissionError', results['DENIED'][3][0])
        self.assertEqual(results['OK'][1]['regularMarketPrice'], 10.1234)
        self.assertEqual(results['LAST'][3], [])

    def test_yf_cli_empty_requested_history_is_not_success_or_operation_error(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['yf.py', 'AAA', '--price-only', '--json', '--market', 'US', '--asset-type', 'stock']), patch.object(yf, 'configure_yfinance_cache'), patch.object(yf, 'resolve_symbol', return_value='AAA'), patch.object(yf, 'get_stock_data', return_value=(pd.DataFrame(), {'symbol': 'AAA', 'quoteType': 'EQUITY'}, [], [])), contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exit_info:
            yf.main()
        self.assertEqual(exit_info.exception.code, 1)
        result = json.loads(output.getvalue())[0]
        self.assertEqual(result['status'], 'insufficient_data')
        self.assertNotIn('errors', result)

    def test_yf_cli_requested_enhancement_partial_unavailable_complete_and_error(self):
        required = ['volume_ratio', 'turnover_rate', 'profit_ratio', 'avg_cost', 'concentration']
        complete = dict(zip(required, [1.2, 2.1, .5, 12, .2], strict=True))
        for enhancement_status, evidence_status, values, exit_code in (
            ('partial', 'partial', {'volume_ratio': 1.2}, 1),
            ('unavailable', 'unavailable', {}, 1),
            ('ok', 'complete', complete, 0),
            ('error', 'partial', {'profit_ratio': .5}, 1),
        ):
            with self.subTest(enhancement_status=enhancement_status):
                output = io.StringIO()
                outcomes = {'quote': {'status': 'no_data' if enhancement_status == 'unavailable' else 'ok'}}
                if enhancement_status == 'error':
                    outcomes['quote'] = runtime.error_outcome(PermissionError('synthetic denied'))
                metrics = {**values, 'enhancement_status': enhancement_status, 'evidence_status': evidence_status, 'required_metrics': required, 'provider_outcomes': outcomes}
                with patch.object(sys, 'argv', ['yf.py', '600519.SS', '--info-only', '--a-share-enhanced', '--json']), patch.dict(os.environ, {'PIA_DASHBOARD_DIR': ''}), patch.object(yf, 'configure_yfinance_cache'), patch.object(yf, 'resolve_symbol', return_value='600519.SS'), patch.object(yf, 'get_stock_data', return_value=(None, {'symbol': '600519.SS', 'regularMarketPrice': 10, 'quoteType': 'EQUITY'}, [], [])), patch.object(akf.StandaloneDataFetcher, 'get_enhanced_metrics', return_value=metrics) as enhance, contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exit_info:
                    yf.main()
                enhance.assert_called_once_with('600519', skip_chip_dist=False)
                self.assertEqual(exit_info.exception.code, exit_code)
                payload = json.loads(output.getvalue())
                self.assertIsInstance(payload, list)
                self.assertEqual(len(payload), 1)
                result = payload[0]
                self.assertEqual(result['symbol'], '600519.SS')
                for key, value in metrics.items():
                    self.assertEqual(result['info'][key], value)
                self.assertEqual(result['data_sources']['enhanced_metrics'], 'Akshare/Efinance')
                if enhancement_status in {'partial', 'unavailable'}:
                    self.assertEqual(result['status'], 'insufficient_data')
                    self.assertNotIn('errors', result)
                    self.assertNotIn('error', result)
                elif enhancement_status == 'error':
                    self.assertTrue(result['errors'])
                    self.assertIn('PermissionError', result['errors'][0])
                    self.assertNotEqual(result.get('status'), 'insufficient_data')
                else:
                    self.assertNotIn('status', result)
                    self.assertNotIn('errors', result)
                self.assertEqual(bool(result['data_gaps']), enhancement_status != 'ok')

    def test_yf_daily_sync_wrapper_covers_requested_enhancement_not_just_quote_audit(self):
        positions = {'base_currency': 'CNY', 'positions': [{
            'symbol': '600519.SS', 'name': 'synthetic', 'quantity': 1,
            'avg_cost': 1, 'currency': 'CNY', 'market': 'CN', 'asset_type': 'stock',
        }]}
        info = {
            'symbol': '600519.SS', 'regularMarketPrice': 10, 'quoteType': 'EQUITY',
            'exchange': 'SHH', 'currency': 'CNY', 'marketState': 'CLOSED',
            'regularMarketTime': time.time() - 60,
        }
        required = ['volume_ratio', 'turnover_rate', 'profit_ratio', 'avg_cost', 'concentration']
        positions_path = Path(self.directory.name) / 'synthetic-positions.json'
        positions_path.write_text(json.dumps(positions), encoding='utf-8')
        for enhancement_status, expected_status, exit_code in (
            (None, 'complete', 0), ('partial', 'incomplete', 1),
            ('error', 'incomplete', 1), ('ok', 'complete', 0),
        ):
            with self.subTest(enhancement_status=enhancement_status):
                argv = ['yf.py', '600519.SS', '--daily-sync', '--positions-file', str(positions_path)]
                if enhancement_status is not None:
                    argv.append('--a-share-enhanced')
                metrics = {
                    'enhancement_status': enhancement_status,
                    'evidence_status': 'complete' if enhancement_status == 'ok' else 'partial',
                    'required_metrics': required, 'volume_ratio': 1.2,
                    'provider_outcomes': {'quote': {'status': 'ok'}},
                }
                if enhancement_status == 'ok':
                    metrics.update(turnover_rate=2.1, profit_ratio=.5, avg_cost=12, concentration=.2)
                if enhancement_status == 'error':
                    metrics['provider_outcomes']['quote'] = runtime.error_outcome(PermissionError('synthetic denied'))
                output = io.StringIO()
                with patch.object(sys, 'argv', argv), patch.dict(os.environ, {'PIA_DASHBOARD_DIR': ''}), patch.object(yf, 'configure_yfinance_cache'), patch.object(yf, 'resolve_symbol', side_effect=AssertionError('validated Daily Sync symbol must not be resolved')), patch.object(yf, 'get_stock_data', return_value=(None, info, [], [])), patch.object(akf.StandaloneDataFetcher, 'get_enhanced_metrics', return_value=metrics) as enhance, contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exit_info:
                    yf.main()
                self.assertEqual(exit_info.exception.code, exit_code)
                payload = json.loads(output.getvalue())
                self.assertIsInstance(payload, dict)
                self.assertEqual(payload['status'], expected_status)
                self.assertEqual(len(payload['records']), 1)
                # Coverage remains independent: partial enhancement is not a
                # quote failure; real provider errors retain existing semantics.
                self.assertEqual(payload['portfolio_batch_audit']['complete'], enhancement_status != 'error')
                record = payload['records'][0]
                self.assertEqual(record['portfolio_context']['current_price'], 10)
                self.assertNotIn('history', record)
                if enhancement_status is None:
                    enhance.assert_not_called()
                    self.assertNotIn('status', record)
                else:
                    enhance.assert_called_once_with('600519', skip_chip_dist=False)
                    self.assertEqual(record['info']['volume_ratio'], 1.2)
                if enhancement_status == 'partial':
                    self.assertEqual(record['status'], 'insufficient_data')
                    self.assertNotIn('errors', record)
                elif enhancement_status == 'error':
                    self.assertIn('PermissionError', record['errors'][0])
                else:
                    self.assertNotIn('errors', record)

    def test_provider_non_dataframe_is_a_programming_error(self):
        with patch('efinance.stock.get_latest_quote', return_value=['not tabular']):
            with self.assertRaisesRegex(TypeError, 'non-DataFrame'):
                akf._provider_frame('efinance_quote', '600519')

    def test_quality_financial_hang_is_bounded_through_direct_consumer(self):
        def isolated(function, *args, **kwargs):
            return runtime.run_provider(synthetic_provider, 'hang', timeout_seconds=8)
        with patch.object(quality, 'run_provider', side_effect=isolated):
            started = time.monotonic()
            result = quality.evaluate_ticker('AAA', 'synthetic', {'thresholds': {}})
        self.assertLess(time.monotonic()-started, 10)
        self.assertEqual(result['provider_outcome']['status'], 'timeout')
        self.assertEqual(result['status'], 'data_error')

    def test_auto_history_empty_after_three_attempts_cannot_restart_budget(self):
        empty = pd.DataFrame()
        empty.attrs['pia_provider_outcome'] = {'status': 'no_data', 'attempts': 3}
        with patch.object(akf.StandaloneDataFetcher, 'get_history', return_value=empty), patch.object(yf, '_call_yahoo') as fallback:
            result = yf.get_stock_data('600519.SS', fetch_info=False, fetch_news=False, a_share_history_source='auto')
        fallback.assert_not_called()
        self.assertEqual(result[3], [])
        self.assertTrue(result[0].empty)
        self.assertEqual(result[0].attrs['pia_provider_outcome']['status'], 'no_data')
        self.assertEqual(result[0].attrs['pia_fallback_skipped'], 'attempt_or_deadline_budget')

    def test_reparse_metadata_is_rejected_before_deserialization(self):
        from types import SimpleNamespace
        original = Path.lstat
        def redirected(path, *args, **kwargs):
            metadata = original(path, *args, **kwargs)
            if path.name == 'result':
                return SimpleNamespace(st_mode=metadata.st_mode, st_size=metadata.st_size, st_file_attributes=1024)
            return metadata
        with patch.object(Path, 'lstat', redirected), patch.object(runtime.pickle, 'load', side_effect=AssertionError('must not deserialize')):
            result = runtime.run_provider(synthetic_provider, 'frame', timeout_seconds=8)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error'], 'provider_ipc_redirection')

    def test_quality_empty_is_evidence_gap_and_operation_error_is_distinct(self):
        for frames, expected in [((pd.DataFrame(),)*3, 'insufficient_data'), (runtime.ProviderError(runtime.error_outcome(PermissionError('synthetic denied'))), 'data_error')]:
            options = {'side_effect': frames} if isinstance(frames, Exception) else {'return_value': frames}
            with patch.object(quality, 'fetch_yf_data', **options):
                result = quality.evaluate_ticker('AAA', 'synthetic', {'thresholds': {}})
            self.assertEqual(result['status'], expected)
            if expected == 'data_error':
                self.assertEqual(result['provider_outcome']['error_type'], 'PermissionError')


if __name__ == '__main__':
    unittest.main()
