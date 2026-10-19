"""Synthetic raw-byte -> native -> projection -> P0 reader and hostile boundaries."""
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pia_fact_prepare as facts
import sec_edgar_fundamentals as sec
import thesis_source_binding as binding


class Response:
    def __init__(self, raw):
        self.content = raw

    def raise_for_status(self):
        pass

    def json(self):
        return json.loads(self.content)


def company_bytes():
    tags = {}
    for metric, candidates in sec.TAG_CANDIDATES.items():
        row = {'val': 10 if metric == 'diluted_eps' else 100, 'end': '2023-12-31',
               'filed': '2024-02-01', 'form': '10-K', 'accn': 'synthetic-001'}
        if metric != 'stockholders_equity':
            row['start'] = '2023-01-01'
        tags[candidates[0]] = {'units': {sec.PREFERRED_UNITS[metric][0]: [row]}}
    return json.dumps({'cik': 789019, 'entityName': 'SYNTHETIC', 'facts': {'us-gaap': tags}}, indent=1).encode() + b'\n'


class FactPrepareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('PIA_TEST_TMP'))
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root, self.task = self.base / 'capture', self.base / 'output'
        self.raw = company_bytes()
        self.mapping = b'{ "0" : {"ticker":"MSFT", "cik_str":789019} }\n'
        responses = {sec.TICKER_MAP_URL: self.mapping, sec.COMPANYFACTS_URL.format(cik='0000789019'): self.raw}
        session = mock.Mock(spec=requests.Session)
        session.get.side_effect = lambda url, **kwargs: Response(responses[url])
        # This session cannot access the network.
        with mock.patch('requests.sessions.Session.request', side_effect=AssertionError('network forbidden')):
            self.report = sec.build_report(['MSFT'], as_of=date.today(), user_agent='synthetic',
                                           session=session, decision_scope='research_only', artifact_dir=self.root)
        self.input = Path(self.report['fact_prepare_input'])
        self.spec = facts.load(self.input.read_bytes())['projections'][0]
        self.doc = facts.project(self.spec, self.root)

    def reject(self, doc):
        with self.assertRaises((ValueError, KeyError, TypeError, OSError)):
            facts.verify_fact_projection(doc, self.root)

    def test_native_raw_to_projection_to_p0(self):
        self.assertEqual(self.report['status'], 'complete')
        result = facts.prepare_facts(self.input, self.root, self.root)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['rules_need_confirmation'], [])
        self.assertEqual(len(result['facts_automatic']), 5)
        prepared = result['projections'][0]
        projection = Path(prepared['file']).relative_to(self.root).as_posix()
        items = [{'evidence_id': 'e', 'local_path': projection, 'content_sha256': prepared['content_sha256'], 'fact_pointer': '/facts/0'}]
        values, provenance = binding._facts(items, self.root.resolve(), evaluation_epoch=datetime.now(timezone.utc).timestamp())
        self.assertEqual(next(iter(next(iter(values.values())))), 10)
        self.assertEqual(provenance[0]['role'], 'derived')
        self.assertEqual(provenance[0]['verification'], 'source_bound_numeric_consistency')
        receipt = self.spec['captures']['companyfacts']
        self.assertEqual((self.root / receipt['raw_artifact']).read_bytes(), self.raw)
        self.assertEqual((self.root / self.spec['captures']['ticker_map']['raw_artifact']).read_bytes(), self.mapping)

    def test_projection_failures_preserve_success_manifest_both_orders(self):
        for bad_first in (False, True):
            with self.subTest(bad_first=bad_first):
                bad = copy.deepcopy(self.spec)
                bad['cik'] = '0000000001'
                specs = [bad, self.spec] if bad_first else [self.spec, bad]
                self.input.write_bytes(facts.render({'projections': specs}))
                result = facts.prepare_facts(self.input, self.root, self.task)
                self.assertEqual(result['status'], 'incomplete')
                self.assertEqual(len(result['projections']), 1)
                self.assertTrue(result['facts_automatic'])
                self.assertEqual(result['errors'][0]['projection_index'], 0 if bad_first else 1)
                self.assertEqual(result['errors'][0]['type'], 'FactError')
                for projection in result['projections']:
                    raw = Path(projection['file']).read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), projection['content_sha256'])
                    facts.verify_fact_projection(projection['document'], self.root)

    def test_global_invalid_json_and_root_still_rejected(self):
        self.input.write_bytes(b'not json')
        with self.assertRaises(ValueError):
            facts.prepare_facts(self.input, self.root, self.task)
        with self.assertRaises(OSError):
            facts.prepare_facts(self.input, self.base / 'absent', self.task)

    def test_unknown_program_exception_is_not_projection_insufficiency(self):
        with mock.patch.object(facts, 'project', side_effect=RuntimeError('program fault')), self.assertRaisesRegex(RuntimeError, 'program fault'):
            facts.prepare_facts(self.input, self.root, self.task)

    def test_all_projected_dimensions_recomputed(self):
        for field, value in [('value', 999), ('unit', 'shares'), ('metric', 'revenue'), ('symbol', 'OTHER'), ('period', '2022'), ('scope', 'segment:one')]:
            with self.subTest(field=field):
                doc = copy.deepcopy(self.doc)
                doc['facts'][0][field] = value
                self.reject(doc)

    def test_raw_hash_and_bytes(self):
        for name in ('ticker_map', 'companyfacts'):
            with self.subTest(name=name):
                doc = copy.deepcopy(self.doc)
                doc['projection']['captures'][name]['content_sha256'] = '0' * 64
                self.reject(doc)
        path = self.root / self.spec['captures']['companyfacts']['raw_artifact']
        path.write_bytes(self.raw + b' ')
        self.reject(self.doc)

    def test_pointer_identity_time_metric_scope_unit(self):
        changes = [('raw_pointer', '/facts/us-gaap/NetIncomeLoss/units/USD/999'),
                   ('metric', 'net_income'), ('scope', 'segment:x'), ('unit', 'EUR'), ('period', '2022')]
        for key, value in changes:
            with self.subTest(key=key):
                doc = copy.deepcopy(self.doc)
                doc['projection']['selections'][0][key] = value
                self.reject(doc)
        for key, value in [('symbol', 'AAPL'), ('cik', '0000000001'), ('as_of', '2020-01-01'), ('transform', 'unknown')]:
            doc = copy.deepcopy(self.doc)
            doc['projection'][key] = value
            self.reject(doc)

    def test_identity_rechecked_not_mapping_claim(self):
        path = self.root / self.spec['captures']['ticker_map']['raw_artifact']
        raw = b'{"0":{"ticker":"MSFT","cik_str":1}}'
        path.write_bytes(raw)
        doc = copy.deepcopy(self.doc)
        r = doc['projection']['captures']['ticker_map']
        r['content_sha256'], r['byte_count'] = hashlib.sha256(raw).hexdigest(), len(raw)
        self.reject(doc)

    def test_path_escapes(self):
        for path in ('../outside.json', '/outside.json', 'C:/outside.json', 'raw/../x.json', 'raw\\x.json'):
            doc = copy.deepcopy(self.doc)
            doc['projection']['captures']['companyfacts']['raw_artifact'] = path
            self.reject(doc)

    def test_link_escape(self):
        target = self.base / 'outside.json'
        target.write_bytes(self.raw)
        link = self.root / 'link.json'
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest('OS symlink capability unavailable')
        doc = copy.deepcopy(self.doc)
        doc['projection']['captures']['companyfacts']['raw_artifact'] = 'link.json'
        self.reject(doc)

    def test_unknown_transform_never_legacy_fallback(self):
        doc = copy.deepcopy(self.doc)
        doc['projection']['transform'] = 'unknown'
        path = self.root / 'projection.json'
        path.write_bytes(facts.render(doc))
        with self.assertRaises(binding.BindingError):
            binding._facts([{'evidence_id': 'e', 'local_path': 'projection.json',
                             'content_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'fact_pointer': '/facts/0'}], self.root.resolve())

    def test_conflict_and_idempotent_store(self):
        path = self.base / 'test.json'
        facts.store(path, b'one')
        facts.store(path, b'one')
        with self.assertRaises(facts.FactError):
            facts.store(path, b'two')
        doc = copy.deepcopy(self.doc)
        doc['projection']['selections'].append(copy.deepcopy(doc['projection']['selections'][0]))
        self.reject(doc)

    def test_exact_numbers(self):
        from decimal import Decimal
        self.assertEqual(facts.exact_number(Decimal('123456789012345678901')), 123456789012345678901)
        self.assertEqual(facts.exact_number(Decimal('0.1')), 0.1)
        with self.assertRaisesRegex(facts.FactError, 'not_lossless'):
            facts.exact_number(Decimal('0.123456789012345678901'))
        with self.assertRaises(facts.FactError):
            facts.exact_number(True)

    def test_noncalendar_period_not_relabelled(self):
        self.assertEqual(facts.period_label({'start': '2022-07-01', 'end': '2023-06-30'}), '2022-07-01/2023-06-30')
        self.assertEqual(facts.period_label({'start': '2023-04-01', 'end': '2023-06-30'}), '2023Q2')

    def test_pdf_corrupt_blank_encrypted_and_candidate(self):
        from pypdf import PdfWriter
        from pypdf.generic import (
            DecodedStreamObject,
            DictionaryObject,
            NameObject,
            NumberObject,
        )

        def run(raw):
            digest = hashlib.sha256(raw).hexdigest()
            path = self.root / (digest + '.pdf')
            path.write_bytes(raw)
            from source_timing_contract import verify_source_capture
            now = datetime.now(timezone.utc).isoformat()
            r = verify_source_capture(path, source_locator='https://www.sec.gov/synthetic.pdf', availability_observed_at=now, retrieved_at=now)
            r['raw_artifact'] = path.name
            return facts.pdf_candidates(self.root, {'capture': r})
        broken = run(b'not a pdf')
        self.assertEqual(broken['status'], 'corrupt')
        self.assertIn('type', broken['error'])
        self.assertFalse(broken['verified'])
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buf = io.BytesIO()
        writer.write(buf)
        self.assertEqual(run(buf.getvalue())['status'], 'blank')
        scan = PdfWriter()
        scan_page = scan.add_blank_page(width=20, height=20)
        image = DecodedStreamObject()
        image.set_data(b'\x00')
        image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                      NameObject('/Width'): NumberObject(1), NameObject('/Height'): NumberObject(1),
                      NameObject('/ColorSpace'): NameObject('/DeviceGray'), NameObject('/BitsPerComponent'): NumberObject(8)})
        scan_page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/Im1'): image})})
        content = DecodedStreamObject()
        content.set_data(b'q 10 0 0 10 0 0 cm /Im1 Do Q')
        scan_page[NameObject('/Contents')] = content
        scanned = io.BytesIO()
        scan.write(scanned)
        self.assertEqual(run(scanned.getvalue())['status'], 'scan_ocr_unavailable')
        # A tiny real PDF content stream supplies a deterministic page-level text oracle.
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page = writer.pages[0]
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 10 100 Td (Revenue 100) Tj ET')
        page[NameObject('/Contents')] = stream
        buf = io.BytesIO()
        writer.write(buf)
        candidate = run(buf.getvalue())
        self.assertEqual(candidate['status'], 'candidates')
        self.assertIn('Revenue 100', candidate['candidates'][0]['text'])
        self.assertFalse(candidate['candidates'][0]['verified'])
        self.assertEqual(candidate['candidates'][0]['page'], 1)
        writer.encrypt('synthetic-password')
        buf = io.BytesIO()
        writer.write(buf)
        self.assertEqual(run(buf.getvalue())['status'], 'encrypted')

    def test_unknown_alias_only_confirmation(self):
        data = facts.load(self.input.read_bytes())
        data['projections'][0]['selections'][0]['metric'] = 'custom_unknown'
        path = self.base / 'unknown.json'
        path.write_bytes(facts.render(data))
        result = facts.prepare_facts(path, self.root, self.task)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(len(result['rules_need_confirmation']), 1)
        self.assertNotIn('custom_unknown', [r['metric'] for r in result['facts_automatic']])

    def test_provenance_and_role_tampering(self):
        for key, value in [('role', 'original'), ('verification', 'publisher_authenticated'), ('schema_version', 'unknown')]:
            doc = copy.deepcopy(self.doc)
            doc[key] = value
            self.reject(doc)
        doc = copy.deepcopy(self.doc)
        doc['provenance'][0]['filed'] = '2000-01-01'
        self.reject(doc)

    def test_fractional_raw_projection_lossless(self):
        raw = self.raw.replace(b'"val": 10,', b'"val": 0.1,', 1)
        path = self.root / self.spec['captures']['companyfacts']['raw_artifact']
        path.write_bytes(raw)
        spec = copy.deepcopy(self.spec)
        receipt = spec['captures']['companyfacts']
        receipt['content_sha256'], receipt['byte_count'] = hashlib.sha256(raw).hexdigest(), len(raw)
        doc = facts.project(spec, self.root)
        self.assertEqual(doc['facts'][0]['value'], 0.1)
        facts.verify_fact_projection(binding._json(facts.render(doc), decimal=True), self.root)

    def test_conflicting_raw_facts_rejected(self):
        payload = json.loads(self.raw)
        tag = sec.TAG_CANDIDATES['diluted_eps'][0]
        rows = payload['facts']['us-gaap'][tag]['units']['USD/shares']
        extra = dict(rows[0], val=999)
        rows.append(extra)
        raw = facts.render(payload)
        path = self.root / self.spec['captures']['companyfacts']['raw_artifact']
        path.write_bytes(raw)
        doc = copy.deepcopy(self.doc)
        receipt = doc['projection']['captures']['companyfacts']
        receipt['content_sha256'], receipt['byte_count'] = hashlib.sha256(raw).hexdigest(), len(raw)
        select = dict(doc['projection']['selections'][0], raw_pointer=f'/facts/us-gaap/{tag}/units/USD~1shares/1')
        doc['projection']['selections'].append(select)
        self.reject(doc)

    def test_pdf_budget_is_explicit_partial(self):
        from pypdf import PdfWriter

        from source_timing_contract import verify_source_capture
        writer = PdfWriter()
        for _ in range(101):
            writer.add_blank_page(width=20, height=20)
        stream = io.BytesIO()
        writer.write(stream)
        path = self.root / 'large.pdf'
        path.write_bytes(stream.getvalue())
        now = datetime.now(timezone.utc).isoformat()
        receipt = verify_source_capture(path, source_locator='https://www.sec.gov/synthetic.pdf', availability_observed_at=now, retrieved_at=now)
        receipt['raw_artifact'] = path.name
        result = facts.pdf_candidates(self.root, {'capture': receipt})
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['coverage_complete'])
        self.assertEqual(len(result['candidates']), 100)

    def test_timestamp_after_evaluation_rejected(self):
        path = self.root / 'projection.json'
        path.write_bytes(facts.render(self.doc))
        with self.assertRaises(binding.BindingError):
            binding._facts([{'evidence_id': 'e', 'local_path': path.name, 'content_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'fact_pointer': '/facts/0'}], self.root.resolve(), evaluation_epoch=0)

    def test_original_six_field_file_metadata_is_not_projection(self):
        original = {'role': 'original', 'provenance': {'note': 'not a projection'},
                    'facts': [dict(self.doc['facts'][0])]}
        path = self.root / 'original.json'
        path.write_bytes(facts.render(original))
        items = [{'evidence_id': 'e', 'local_path': path.name,
                  'content_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'fact_pointer': '/facts/0'}]
        values, provenance = binding._facts(items, self.root.resolve())
        self.assertTrue(values)
        self.assertNotIn('role', provenance[0])


if __name__ == '__main__':
    unittest.main()
