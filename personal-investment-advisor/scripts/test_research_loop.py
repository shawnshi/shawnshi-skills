"""Synthetic offline research-loop unit and real CLI lifecycle oracles."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pia_research_loop as loop


def fixture(root):
    evidence = root/'evidence'; evidence.mkdir()
    hashes = {}
    for name, text in [('event.txt','Synthetic revenue 110'), ('counter.txt','Synthetic counterevidence'), ('condition.txt','Synthetic confirmed target 100')]:
        raw = text.encode(); (evidence/name).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    def event(eid, name):
        return {'event_id':eid,'symbol':'SYNTH','published_at':'2026-10-01T00:00:00Z',
                'retrieved_at':'2026-10-02T00:00:00Z','source_locator':'https://example.test/'+name,
                'artifact':name,'content_sha256':hashes[name],'body_retrieved':True,
                'health':'ok','source_error':None,'coverage_complete':True,'coverage_limits':[]}
    condition = {'condition_id':'c1','symbol':'SYNTH','version':1,'confirmed_at':'2026-01-01T00:00:00Z',
                 'effective_from':'2026-01-01T00:00:00Z','metric':'revenue','operator':'gte','threshold':100,
                 'unit':'CNY','period':{'start':'2026-01-01','end':'2026-09-30'},'due':'2026-09-30',
                 'channel':'synthetic filing','source_locator':'https://example.test/condition',
                 'artifact':'condition.txt','content_sha256':hashes['condition.txt']}
    link = {'link_id':'l1','event_ids':['e1','e2'],'condition_id':'c1','condition_version':1,
            'reason':'Human supplied relation','locator':'page 1 table 1 line 1','actual':110,
            'actual_period':{'start':'2026-01-01','end':'2026-09-30','complete':True},'unit':'CNY',
            'counterevidence':[{'event_id':'e2','locator':'page 1 line 2'}]}
    bundle = {'schema_version':'pia_research_loop_v1','record_id':'proposal1','as_of':'2026-10-10T05:00:00Z',
              'scope':'listed_events_only','events':[event('e1','event.txt'),event('e2','counter.txt')],
              'conditions':[condition],'links':[link]}
    source = root/'bundle.json'; source.write_text(json.dumps(bundle),encoding='utf-8')
    return bundle, source, evidence, root/'task'


def decision(proposal, action='accept'):
    return {'schema_version':'pia_research_decisions_v1','record_id':'receipt_'+action,
            'proposal_sha256':proposal['proposal_sha256'],
            'decisions':[{'link_id':'l1','action':action,'reviewer':'Synthetic reviewer',
                          'reviewed_at':'2026-10-09T00:00:00Z','reason':'Explicit synthetic review',
                          'event_ids':['e1','e2'],'condition_version':1}]}


class ResearchLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.bundle,self.source,self.evidence,self.task=fixture(self.root)
    def tearDown(self): self.tmp.cleanup()
    def run_loop(self, decisions=None):
        self.source.write_text(json.dumps(self.bundle),encoding='utf-8')
        dfile=None
        if decisions is not None:
            dfile=self.root/'decisions.json'; dfile.write_text(json.dumps(decisions),encoding='utf-8')
        return loop.run(self.source,self.evidence,self.task,dfile)
    def test_proposal_and_accept_receipt_with_read_only_inputs(self):
        before={p:p.read_bytes() for p in [self.source,self.evidence/'event.txt',self.evidence/'counter.txt',self.evidence/'condition.txt']}
        proposal=self.run_loop(); self.assertEqual(proposal['status'],'incomplete')
        result=self.run_loop(decision(proposal)); self.assertEqual(result['status'],'complete')
        self.assertEqual(result['assessments'][0]['assessment'],'met')
        self.assertFalse(result['investment_authorized']); self.assertFalse(result['formal_use_allowed'])
        self.assertFalse(result['human_identity_authenticated'])
        self.assertEqual(before,{p:p.read_bytes() for p in before})
    def test_return_and_reject(self):
        p=self.run_loop()
        self.assertEqual(self.run_loop(decision(p,'return'))['status'],'insufficient_evidence')
        r=self.run_loop(decision(p,'reject')); self.assertEqual(r['status'],'complete')
        self.assertEqual(r['assessments'][0]['assessment'],'rejected_association')
        self.assertEqual(r['thesis_safety'],'not_assessed')
    def test_dedup_preserves_aliases_and_all_distinct_events(self):
        duplicate=copy.deepcopy(self.bundle['events'][0]); duplicate['event_id']='e3'
        self.bundle['events'].append(duplicate); self.bundle['links'][0]['event_ids'].append('e3')
        p=self.run_loop(); self.assertEqual(len(p['events']),2)
        self.assertEqual(p['events'][0]['event_aliases'],['e1','e3'])
        self.assertEqual(len(p['events'][0]['source_receipts']),2)
    def test_empty_vs_broken_sources(self):
        self.bundle['events'][0].update(health='broken',source_error='Synthetic TimeoutError',body_retrieved=False)
        p=self.run_loop(); self.assertEqual(p['status'],'insufficient_evidence')
        self.assertIn('Synthetic TimeoutError',str(p['evidence_tasks']))
        self.bundle['record_id']='empty'; self.bundle['events']=[];self.bundle['links']=[]
        p=self.run_loop(); self.assertEqual(p['status'],'insufficient_evidence')
        self.assertEqual(p['evidence_tasks'][0]['kind'],'empty_scope')
    def test_missing_business_evidence_tasks_stable(self):
        self.bundle['links'][0].update(counterevidence=None,actual_period=None,unit='USD')
        self.bundle['events'][0].update(coverage_complete=False,coverage_limits=['page 1 only'])
        p=self.run_loop(); again=self.run_loop()
        self.assertEqual(p['evidence_tasks'],again['evidence_tasks'])
        self.assertEqual(p['status'],'insufficient_evidence')
    def test_no_implicit_association_or_review(self):
        self.bundle['links']=[]
        p=self.run_loop(); self.assertEqual(p['status'],'incomplete')
        self.assertEqual(p['unlinked_event_ids'],['e1','e2'])
    def test_not_due_and_no_early_missed(self):
        self.bundle['conditions'][0]['due']='2026-12-31'
        self.bundle['links'][0]['actual']=80
        p=self.run_loop(); self.assertEqual(p['assessments'][0]['assessment'],'not_due')
        self.assertIsNone(p['assessments'][0]['comparison_result'])
    def test_version_selection_and_stale_link(self):
        newer=copy.deepcopy(self.bundle['conditions'][0]);newer['version']=2;newer['effective_from']='2026-12-01T00:00:00Z'
        self.bundle['conditions'].append(newer)
        p=self.run_loop();self.assertEqual(p['selected_conditions'][0]['version'],1)
        self.bundle['record_id']='newversion';newer['effective_from']='2026-02-01T00:00:00Z'
        with self.assertRaisesRegex(loop.LoopError,'stale'):self.run_loop()
    def test_decision_binding_and_review_identity(self):
        p=self.run_loop()
        for field,value in [('condition_version',2),('reviewer',''),('reviewed_at','2026-12-01T00:00:00Z'),('event_ids',['e1'])]:
            d=decision(p);d['decisions'][0][field]=value
            with self.subTest(field=field),self.assertRaises(loop.LoopError):self.run_loop(d)
        d=decision(p);d['proposal_sha256']='0'*64
        with self.assertRaisesRegex(loop.LoopError,'hash'):self.run_loop(d)
    def test_number_validation_extremes(self):
        for value in (True,float('inf'),float('nan'),10**400,-10**400):
            self.bundle['links'][0]['actual']=value
            with self.subTest(value=str(value)[:8]),self.assertRaises(loop.LoopError):self.run_loop()
    def test_future_times_and_bad_hash(self):
        self.bundle['events'][0]['retrieved_at']='2026-12-01T00:00:00Z'
        with self.assertRaisesRegex(loop.LoopError,'future'):self.run_loop()
        self.bundle['events'][0]['retrieved_at']='2026-10-02T00:00:00Z'
        (self.evidence/'event.txt').write_bytes(b'changed')
        with self.assertRaisesRegex(loop.LoopError,'hash'):self.run_loop()
    def test_path_escape_and_output_protection(self):
        for name in ('../secret','/absolute','C:\\private\\secret','..\\secret'):
            self.bundle['events'][0]['artifact']=name
            with self.subTest(path=name),self.assertRaises(loop.LoopError):self.run_loop()
        self.bundle['events'][0]['artifact']='event.txt';self.task=self.evidence/'out'
        with self.assertRaisesRegex(loop.LoopError,'disjoint'):self.run_loop()
    def test_symlink_escape_rejected_when_supported(self):
        link=self.evidence/'escape.txt';outside=self.root/'outside.txt';outside.write_bytes(b'outside')
        try:link.symlink_to(outside)
        except OSError:self.skipTest('OS symlink privilege unavailable')
        self.bundle['events'][0]['artifact']='escape.txt'
        with self.assertRaisesRegex(loop.LoopError,'symlink'):self.run_loop()
    def test_idempotency_conflict_and_interrupted_commit(self):
        p=self.run_loop();path=Path(p['record_file']);raw=path.read_bytes();mtime=path.stat().st_mtime_ns
        self.assertEqual(self.run_loop()['generated_at'],p['generated_at'])
        self.assertEqual(path.stat().st_mtime_ns,mtime)
        self.bundle['links'][0]['reason']='Changed input'
        with self.assertRaisesRegex(loop.LoopError,'conflict'):self.run_loop()
        self.assertEqual(path.read_bytes(),raw)
        self.bundle['links'][0]['reason']='Human supplied relation'
        d=decision(p);receipt=self.run_loop(d);rpath=Path(receipt['record_file']);old=rpath.read_bytes()
        d['record_id']='newreceipt'
        with mock.patch('artifact_io.os.replace',side_effect=OSError('synthetic interrupted')):
            with self.assertRaises(OSError):self.run_loop(d)
        self.assertEqual(rpath.read_bytes(),old)
    def test_limits_extra_fields_and_missing_version(self):
        self.bundle['extra']='not allowed'
        with self.assertRaises(loop.LoopError):self.run_loop()
        del self.bundle['extra']; self.bundle['conditions']=[]
        self.assertEqual(self.run_loop()['status'],'insufficient_evidence')
        self.bundle['record_id']='overlimit';self.bundle['events']*=51
        with self.assertRaises(loop.LoopError):self.run_loop()
    def test_cli_help_and_router_proposal_decision_receipt(self):
        script=Path(__file__).with_name('pia.py')
        env=dict(os.environ)
        guard=Path(__file__).parent.parent/'audits/staged-20261010/offline_guard'
        env['PYTHONPATH']=str(guard)
        help_result=subprocess.run([sys.executable,'-B',str(script),'research-loop','--help'],capture_output=True,text=True,timeout=15,env=env)
        self.assertEqual(help_result.returncode,0,help_result.stderr)
        argv=[sys.executable,'-B',str(script),'research-loop','--input-file',str(self.source),'--evidence-root',str(self.evidence),'--task-dir',str(self.task)]
        first=subprocess.run(argv,capture_output=True,text=True,timeout=15,env=env)
        self.assertEqual(first.returncode,1,first.stdout+first.stderr)
        p=json.loads(first.stdout)['result'];d=self.root/'decisions.json';d.write_text(json.dumps(decision(p)))
        second=subprocess.run(argv+['--decisions-file',str(d)],capture_output=True,text=True,timeout=15,env=env)
        self.assertEqual(second.returncode,0,second.stdout+second.stderr)
        result=json.loads(second.stdout);self.assertEqual(result['status'],'complete')
        self.assertFalse(result['route']['shell']);self.assertFalse(result['result']['orders_executed'])
        self.assertEqual(result['result']['decision_scope'],'research_only')
        # These are real CLI return values, not a mock of the router or stage.
        self.assertTrue(Path(result['result']['record_file']).is_file())


class ReviewBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bundle, self.source, self.evidence, self.task = fixture(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def run_loop(self, decisions=None):
        self.source.write_text(json.dumps(self.bundle), encoding='utf-8')
        dfile = None
        if decisions is not None:
            dfile = self.root/'decisions.json'
            dfile.write_text(json.dumps(decisions), encoding='utf-8')
        return loop.run(self.source, self.evidence, self.task, dfile)

    def test_r01_each_required_proof_gap_suppresses_comparison(self):
        baseline = copy.deepcopy(self.bundle)
        mutations = [
            ('locator', lambda b: b['links'][0].update(locator=None)),
            ('counter', lambda b: b['links'][0].update(counterevidence=None)),
            ('selected_source', lambda b: b['conditions'][0].update(artifact=None, content_sha256=None)),
            ('primary_body', lambda b: b['events'][0].update(body_retrieved=False)),
            ('counter_body', lambda b: b['events'][1].update(body_retrieved=False)),
            ('source', lambda b: b['events'][1].update(health='broken', source_error='Synthetic TimeoutError')),
            ('coverage', lambda b: b['events'][0].update(coverage_complete=False, coverage_limits=['page 1'])),
            ('period', lambda b: b['links'][0]['actual_period'].update(complete=False)),
            ('unit', lambda b: b['links'][0].update(unit='USD')),
            ('number', lambda b: b['links'][0].update(actual=None)),
        ]
        for name, mutate in mutations:
            self.bundle = copy.deepcopy(baseline)
            self.bundle['record_id'] = 'proof_' + name
            mutate(self.bundle)
            with self.subTest(proof=name):
                result = self.run_loop()
                self.assertEqual(result['assessments'][0]['assessment'], 'insufficient_evidence')
                self.assertIsNone(result['assessments'][0]['comparison_result'])
        self.bundle['record_id'] = 'not_due_missing'
        self.bundle['conditions'][0]['due'] = '2026-12-31'
        self.assertEqual(self.run_loop()['assessments'][0]['assessment'], 'not_due')

    def test_r02_late_counter_requires_link_specific_review_time(self):
        self.bundle['events'][1]['retrieved_at'] = '2026-10-09T00:00:00Z'
        first = self.bundle['links'][0]
        first['event_ids'] = ['e1']
        second = copy.deepcopy(first)
        second.update(link_id='l2', event_ids=['e2'], counterevidence=[{'event_id':'e1','locator':'page 1'}])
        self.bundle['links'].append(second)
        p = self.run_loop()
        d = decision(p)
        d['decisions'][0].update(event_ids=['e1'], reviewed_at='2026-10-03T00:00:00Z')
        other = copy.deepcopy(d['decisions'][0])
        other.update(link_id='l2', event_ids=['e2'], reviewed_at='2026-10-09T00:00:00Z')
        d['decisions'].append(other)
        with self.assertRaisesRegex(loop.LoopError, 'premature'):
            self.run_loop(d)
        d['decisions'][0]['reviewed_at'] = '2026-10-09T00:00:00Z'
        self.assertEqual(self.run_loop(d)['status'], 'complete')

    def test_r03_future_missing_source_not_current_gap(self):
        future = copy.deepcopy(self.bundle['conditions'][0])
        future.update(version=2, effective_from='2026-12-01T00:00:00Z', artifact=None, content_sha256=None)
        self.bundle['conditions'].append(future)
        p = self.run_loop()
        self.assertEqual(p['evidence_tasks'], [])
        self.assertEqual(self.run_loop(decision(p))['status'], 'complete')
        future.update(artifact='condition.txt', content_sha256='0'*64)
        with self.assertRaisesRegex(loop.LoopError, 'hash mismatch'):
            self.run_loop()

    def test_r03_selected_other_missing_source_does_not_poison_valid_link(self):
        other = copy.deepcopy(self.bundle['conditions'][0])
        other.update(condition_id='c2', artifact=None, content_sha256=None)
        self.bundle['conditions'].append(other)
        p = self.run_loop()
        self.assertEqual(p['assessments'][0]['assessment'], 'met')
        gaps = [x for x in p['evidence_tasks'] if x['kind'] == 'missing_condition_source']
        self.assertEqual(len(gaps), 1)
        self.assertIn('c2', gaps[0]['identity'])
        self.bundle['record_id'] = 'both_missing'
        self.bundle['conditions'][0].update(artifact=None, content_sha256=None)
        p = self.run_loop()
        self.assertEqual(len([x for x in p['evidence_tasks'] if x['kind'] == 'missing_condition_source']), 2)
        self.assertIsNone(p['assessments'][0]['comparison_result'])

    def test_r04_whitespace_declarations_rejected(self):
        baseline = copy.deepcopy(self.bundle)
        for field in ('reason', 'locator'):
            for blank in (' ', '\u2003\u00a0'):
                self.bundle = copy.deepcopy(baseline)
                self.bundle['record_id'] = 'blank_' + field + '_' + str(ord(blank[0]))
                self.bundle['links'][0][field] = blank
                with self.subTest(link_field=field, blank=repr(blank)), self.assertRaises(loop.LoopError):
                    self.run_loop()
        for field in ('metric', 'channel', 'symbol'):
            self.bundle = copy.deepcopy(baseline)
            self.bundle['conditions'][0][field] = '\u2003'
            with self.subTest(condition_field=field), self.assertRaises(loop.LoopError):
                self.run_loop()
        self.bundle = copy.deepcopy(baseline)
        self.bundle['links'][0]['counterevidence'][0]['locator'] = '\u00a0'
        with self.assertRaises(loop.LoopError):
            self.run_loop()
        self.bundle = baseline
        p = self.run_loop()
        for field in ('reviewer', 'reason'):
            for blank in (' ', '\u2003\u00a0'):
                d = decision(p)
                d['decisions'][0][field] = blank
                with self.subTest(decision_field=field, blank=repr(blank)), self.assertRaises(loop.LoopError):
                    self.run_loop(d)
        self.assertEqual(self.run_loop(decision(p))['status'], 'complete')

    def test_legacy_receipt_key_rejected_without_overwrite(self):
        p = self.run_loop()
        d = decision(p)
        r = self.run_loop(d)
        path = Path(r['record_file'])
        stored = json.loads(path.read_text(encoding='utf-8'))
        legacy_proposal_key = loop.digest([p['input_sha256'], str(self.evidence.resolve()), self.bundle])
        stored['record_key'] = loop.digest([legacy_proposal_key, r['decisions_sha256']])
        stored['record_sha256'] = loop.digest({k:v for k,v in stored.items() if k != 'record_sha256'})
        path.write_text(json.dumps(stored), encoding='utf-8')
        before = path.read_bytes()
        with self.assertRaisesRegex(loop.LoopError, 'conflict'):
            self.run_loop(d)
        self.assertEqual(path.read_bytes(), before)
        d['record_id'] = 'new_rules_receipt'
        new = self.run_loop(d)
        new_path = Path(new['record_file'])
        mtime = new_path.stat().st_mtime_ns
        self.assertEqual(self.run_loop(d)['generated_at'], new['generated_at'])
        self.assertEqual(new_path.stat().st_mtime_ns, mtime)


if __name__=='__main__':unittest.main()
