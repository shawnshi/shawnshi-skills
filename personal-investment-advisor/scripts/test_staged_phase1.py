"""Synthetic staged audit oracles. Never fetch public or private data."""
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import evidence_channels as ec
import management_claim_tracker as mct
import pia
import pia_evidence as pe
from test_p2_evidence_channels import FakeSession, FakeResponse


def claim_payload():
    return {'test_mode': True, 'as_of_date': '2026-10-10', 'source_documents': [
        {'document_id': 'd', 'source_tier': 'company_primary', 'source_locator': 'https://example.test/d',
         'published_at': '2026-01-01', 'retrieved_at': '2026-10-10', 'text': 'synthetic'}],
        'claims': [{'claim_id': 'c', 'statement': 'annual target', 'metric': 'sales', 'operator': '>=',
                    'target': 100, 'actual': 80, 'deadline': '2026-12-31', 'period_start': '2026-01-01',
                    'period_end': '2026-12-31', 'actual_period_start': '2026-01-01',
                    'actual_period_end': '2026-09-30', 'actual_period_complete': False,
                    'source_document_id': 'd', 'source_locator': 'p1',
                    'actual_source_document_id': 'd', 'actual_source_locator': 'p2'}]}


class ClaimsTests(unittest.TestCase):
    def test_not_due_does_not_close_annual_target(self):
        r = mct.evaluate_claims(claim_payload())
        self.assertTrue(r['valid'], r)
        self.assertEqual(r['management_claim_tracking']['claims'][0]['status'], 'not_due')
        self.assertIsNone(r['management_claim_tracking']['claims'][0]['comparison_result'])

    def test_finite_non_boolean_numbers_only(self):
        for field in ('actual', 'target'):
            for value in (True, float('inf'), float('-inf'), float('nan'), '100', [], {}):
                p = claim_payload(); p['claims'][0][field] = value
                with self.subTest(field=field, value=value):
                    self.assertFalse(mct.evaluate_claims(p)['valid'])

    def test_malformed_root_and_ids_are_structured(self):
        for p in ([], None, {'source_documents': [{'document_id': []}], 'claims': [None]}):
            with self.subTest(p=p):
                self.assertFalse(mct.evaluate_claims(p)['valid'])

    def test_due_requires_matched_complete_period(self):
        p = claim_payload(); p['as_of_date'] = '2027-01-01'
        r = mct.evaluate_claims(p)
        self.assertEqual(r['management_claim_tracking']['claims'][0]['status'], 'insufficient_evidence')
        p['claims'][0].update(actual_period_end='2026-12-31', actual_period_complete=True)
        r = mct.evaluate_claims(p)
        self.assertEqual(r['management_claim_tracking']['claims'][0]['status'], 'missed')
        p['claims'][0]['actual'] = 101
        self.assertEqual(mct.evaluate_claims(p)['management_claim_tracking']['claims'][0]['status'], 'met')


class CacheTests(unittest.TestCase):
    def test_invalid_clock_and_request_mismatch_refetch(self):
        for second_clock, method, url, body in (
            (99, 'GET', 'https://example.test/a', None),
            (float('nan'), 'GET', 'https://example.test/a', None),
            (float('inf'), 'GET', 'https://example.test/a', None),
            (100, 'POST', 'https://example.test/a', 'x=1'),
            (100, 'GET', 'https://example.test/b', None),
            (100, 'GET', 'https://example.test/a', 'different')):
            with self.subTest(clock=second_clock, method=method, url=url, body=body), tempfile.TemporaryDirectory() as d:
                session = FakeSession([FakeResponse(200, b'old'), FakeResponse(200, b'fresh')])
                clock: list[float] = [100.0]
                f = ec.ChannelFetcher(session=session, cache_dir=Path(d), clock=lambda clock=clock: clock[0])
                f.request('GET', 'https://example.test/a', key='k')
                clock[0] = second_clock
                r = f.request(method, url, key='k', json_body=body)
                self.assertFalse(r['reused']); self.assertEqual(r['body'], b'fresh')

    def test_integrity_and_atomic_interrupt(self):
        with tempfile.TemporaryDirectory() as d:
            session = FakeSession([FakeResponse(200, b'old'), FakeResponse(200, b'fresh')])
            f = ec.ChannelFetcher(session=session, cache_dir=Path(d), clock=lambda: 100)
            f.request('GET', 'https://example.test/a', key='k')
            paths = list(Path(d).iterdir()); before = {p.name: p.read_bytes() for p in paths}
            f.bypass_cache = True
            with mock.patch('os.replace', side_effect=OSError('synthetic commit interrupted')):
                with self.assertRaises(OSError):
                    f.request('GET', 'https://example.test/a', key='k')
            self.assertEqual({p.name: p.read_bytes() for p in Path(d).iterdir()}, before)
            f.bypass_cache = False
            self.assertEqual(f.request('GET', 'https://example.test/a', key='k')['body'], b'old')
            for p in paths:
                p.write_bytes(p.read_bytes().replace(b'b2xk', b'YmFk').replace(b'old', b'bad'))
            f.session = FakeSession([FakeResponse(200, b'refetched')])
            self.assertFalse(f.request('GET', 'https://example.test/a', key='k')['reused'])


    def test_timestamp_meta_corruption_and_legacy_format_refetch(self):
        for stamp in (101, float('nan'), float('inf'), float('-inf'), True):
            with self.subTest(stamp=stamp), tempfile.TemporaryDirectory() as d:
                f = ec.ChannelFetcher(session=FakeSession([FakeResponse(200, b'old')]), cache_dir=Path(d), clock=lambda: 100)
                f.request('GET', 'https://example.test/a', key='k')
                path = next(Path(d).glob('*.cache.json'))
                stored = json.loads(path.read_text())
                stored['meta']['fetched_at'] = stamp
                stored['meta_sha256'] = hashlib.sha256(json.dumps(stored['meta'], sort_keys=True,
                    separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
                path.write_text(json.dumps(stored))
                f.session = FakeSession([FakeResponse(200, b'fresh')])
                self.assertFalse(f.request('GET', 'https://example.test/a', key='k')['reused'])
                path.write_text('{bad')
                self.assertFalse(f.request('GET', 'https://example.test/a', key='k')['reused'])
                path.unlink()
                (Path(d)/'k.body').write_bytes(b'legacy')
                (Path(d)/'k.meta.json').write_text(json.dumps({'url': 'https://example.test/a', 'fetched_at': 100}))
                self.assertFalse(f.request('GET', 'https://example.test/a', key='k')['reused'])

    def test_post_body_identity_and_original_time_reuse(self):
        with tempfile.TemporaryDirectory() as d:
            clock = [100.0]
            f = ec.ChannelFetcher(session=FakeSession([FakeResponse(200, b'old'), FakeResponse(200, b'new')]),
                                  cache_dir=Path(d), clock=lambda: clock[0])
            f.request('POST', 'https://example.test/a', key='k', json_body='x=1')
            clock[0] = 101
            reused = f.request('POST', 'https://example.test/a', key='k', json_body='x=1')
            self.assertTrue(reused['reused'])
            self.assertEqual(reused['fetched_at'], 100)
            self.assertEqual(reused['cache_age_seconds'], 1)
            self.assertFalse(f.request('POST', 'https://example.test/a', key='k', json_body='x=2')['reused'])


class WindowTests(unittest.TestCase):
    def test_all_window_candidates_deduplicated_partial_body_failure(self):
        with tempfile.TemporaryDirectory() as d:
            f = ec.ChannelFetcher(session=FakeSession([]), cache_dir=Path(d)/'cache', clock=lambda: 100)
            row = {'title': 'older', 'published_at': '2026-10-01T00:00:00Z', 'document_url': 'https://example.test/old'}
            newer = dict(row, title='newer', published_at='2026-10-09T00:00:00Z', document_url='https://example.test/new')
            listing = {'channel': 'cninfo_fulltext', 'health': ec.HEALTH_OK, 'records': [row, row, newer],
                       'meta': {'body': b'synthetic listing', 'fetched_at': 1791590400, 'url': 'https://example.test/list'}}
            good = {'health': ec.HEALTH_OK, 'content_sha256': ec.sha256_bytes(b'doc'), 'meta': {'body': b'doc', 'fetched_at': 1791590400}}
            bad = {'health': ec.HEALTH_BROKEN, 'meta': {'http_status': 503}}
            with mock.patch.object(ec, 'cninfo_fulltext', return_value=listing), mock.patch.object(ec, 'fetch_document', side_effect=[bad, bad, good]) as fetch:
                r = pe.collect_symbol(f, symbol='600001.SS', window_start=1790812800, window_end=1791676800, evidence_dir=Path(d))
            self.assertEqual(fetch.call_count, 3)
            self.assertEqual(len(r['records']), 3)
            self.assertEqual(r['chosen']['title'], 'newer')
            self.assertFalse(r['event_coverage_complete'])
            items, gaps = pe.build_items([r], window_start=1790812800, window_end=1791676800, scope_entries=[])
            self.assertEqual(len(items), 3)
            self.assertTrue(any(not x['body_retrieved'] for x in r['records']))
            schema = json.loads((Path(__file__).parent.parent/'references/thesis_red_team_schema.json').read_text(encoding='utf-8'))
            allowed = set(schema['$defs']['evidence']['properties']) | {'artifact'}
            self.assertTrue(all(set(item) <= allowed for item in items), items)
            self.assertTrue(all('未评估' in item['claim'] for item in items))
            self.assertEqual(len({x['evidence_id'] for x in items}), 3)


class ProcessTreeTests(unittest.TestCase):
    def test_owned_parent_and_grandchild_timeout_no_residual(self):
        with tempfile.TemporaryDirectory() as d:
            pids = Path(d)/'pids.json'
            k = ctypes.WinDLL('kernel32', use_last_error=True) if os.name == 'nt' else None
            if k is not None:
                k.OpenProcess.restype = ctypes.c_void_p
            source = ('import os,subprocess,sys,time,json; from pathlib import Path; '
                      'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                      f'Path({str(pids)!r}).write_text(json.dumps([os.getpid(),p.pid])); time.sleep(60)')
            try:
                with mock.patch.object(pia, 'CHILD_TIMEOUT_SECONDS', 1.5):
                    with self.assertRaises(subprocess.TimeoutExpired):
                        pia._execute_child([sys.executable, '-B', '-c', source])
                ids = json.loads(pids.read_text())
                if k is not None:
                    for pid in ids:
                        handle = k.OpenProcess(0x100000, False, pid)
                        if handle:
                            try: self.assertEqual(k.WaitForSingleObject(ctypes.c_void_p(handle), 3000), 0, f'PID {pid} remains')
                            finally: k.CloseHandle(ctypes.c_void_p(handle))
                else:
                    for pid in ids:
                        try: os.kill(pid, 0)
                        except ProcessLookupError: continue
                        stat = Path(f'/proc/{pid}/stat')
                        self.assertTrue(stat.exists() and stat.read_text().split()[2] == 'Z')
            finally:
                # Only synthetic, exact PIDs, never process-name matching.
                if pids.exists():
                    for pid in json.loads(pids.read_text()):
                        if k is not None:
                            handle = k.OpenProcess(1, False, pid)
                            if handle:
                                k.TerminateProcess(ctypes.c_void_p(handle), 3)
                                k.CloseHandle(ctypes.c_void_p(handle))
                        else:
                            try: os.kill(pid, 9)
                            except ProcessLookupError: pass


if __name__ == '__main__':
    unittest.main()
