"""Synthetic residual contracts. Real HTTPS and WSL probes are separate authorized audits."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.request import Request

import evidence_channels as ec
import pia_evidence_check as check
import pia_isolated_loop as isolated
import pia_research_loop as loop
import pia_research_prepare as prepare
import secure_transport as transport
from test_p2_evidence_channels import FakeResponse, FakeSession
from test_research_loop import fixture, decision


class ResidualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle,self.source,self.evidence,self.task = fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, data):
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def test_receipt_missing_proposal_never_creates_task(self):
        d = self.write(self.root/'decision.json', {'schema_version':'pia_research_decisions_v1','record_id':'receipt','proposal_sha256':'0'*64,'decisions':[]})
        with self.assertRaisesRegex(loop.LoopError,'previously committed'):
            loop.run(self.source,self.evidence,self.task,d)
        self.assertFalse(self.task.exists())

    def test_invalid_decision_preserves_every_task_byte_and_mtime(self):
        p = loop.run(self.source,self.evidence,self.task)
        before = {x:(x.read_bytes(),x.stat().st_mtime_ns) for x in self.task.rglob('*') if x.is_file()}
        bad = decision(p); bad['decisions'][0]['reviewer'] = ' '
        d = self.write(self.root/'decision.json',bad)
        with self.assertRaises(loop.LoopError):
            loop.run(self.source,self.evidence,self.task,d)
        self.assertEqual(before,{x:(x.read_bytes(),x.stat().st_mtime_ns) for x in self.task.rglob('*') if x.is_file()})

    def test_corrupt_proposal_fails_receipt_without_writes(self):
        p = loop.run(self.source,self.evidence,self.task)
        path = Path(p['record_file']); stored=json.loads(path.read_text()); stored['record_key']='0'*64
        self.write(path,stored); before=path.read_bytes()
        d=self.write(self.root/'decision.json',decision(p))
        with self.assertRaisesRegex(loop.LoopError,'integrity/key'):
            loop.run(self.source,self.evidence,self.task,d)
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse((self.task/'research_loop/receipt_accept.json').exists())

    def test_strict_never_reuses_weak_receipt(self):
        p=loop.run(self.source,self.evidence,self.task)
        d=self.write(self.root/'decision.json',decision(p))
        r=loop.run(self.source,self.evidence,self.task,d)
        before=Path(r['record_file']).read_bytes()
        with self.assertRaisesRegex(loop.LoopError,'required_capability_unavailable'):
            loop.run(self.source,self.evidence,self.task,d,True)
        self.assertEqual(Path(r['record_file']).read_bytes(),before)

    def collector(self, count=2):
        event=self.bundle['events'][0]
        row={'chosen':{'title':'Synthetic candidate, NOT a business assertion','published_at':event['published_at'],'document_url':event['source_locator']},
             'artifact':str(self.evidence/event['artifact']),'content_sha256':event['content_sha256'],
             'source_locator':event['source_locator'],'retrieved_at':event['retrieved_at'],'health':'ok','body_retrieved':True}
        report={'channel_results':[{'symbol':'SYNTH','health':'ok','records':[copy.deepcopy(row) for _ in range(count)],'coverage_limitations':['page 1 only']}]}
        template=copy.deepcopy(self.bundle); template['events']=[];template['links']=[]
        return self.write(self.root/'report.json',report),self.write(self.root/'template.json',template)

    def test_prepare_all_aliases_no_confirmation_no_title_claim(self):
        report,template=self.collector(3)
        before={p:p.read_bytes() for p in (report,template,self.evidence/'event.txt')}
        result=prepare.prepare(report,template,self.evidence,self.task)
        bundle=json.loads(Path(result['bundle_file']).read_text())
        self.assertEqual(len(bundle['events']),3);self.assertEqual(bundle['links'],[])
        self.assertEqual(bundle['events'][0]['retrieved_at'],self.bundle['events'][0]['retrieved_at'])
        self.assertFalse(bundle['events'][0]['coverage_complete'])
        self.assertNotIn('title',str(bundle))
        self.assertEqual(len(result['candidates'][0]['condition_candidates']),1)
        self.assertFalse(result['candidates'][0]['relation_confirmed'])
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        loop_task=self.root/'loop_task'
        proposal=loop.run(result['bundle_file'],self.evidence,loop_task)
        self.assertEqual(proposal['events'][0]['event_aliases'],['candidate_1','candidate_2','candidate_3'])
        self.assertEqual(proposal['status'],'insufficient_evidence')

    def test_prepare_limit_preserves_all_or_fails_without_output(self):
        report,template=self.collector(101)
        with self.assertRaisesRegex(loop.LoopError,'item limit'):
            prepare.prepare(report,template,self.evidence,self.task)
        self.assertFalse(self.task.exists())

    def test_prepare_bad_hash_and_task_overlap(self):
        report,template=self.collector()
        data=json.loads(report.read_text());data['channel_results'][0]['records'][0]['content_sha256']='0'*64
        self.write(report,data)
        with self.assertRaisesRegex(loop.LoopError,'hash'):
            prepare.prepare(report,template,self.evidence,self.task)
        self.assertFalse(self.task.exists())
        with self.assertRaisesRegex(loop.LoopError,'disjoint'):
            prepare.prepare(report,template,self.evidence,self.evidence/'task')

    def assertions(self):
        document={'value':110,'unit':'CNY','period':{'start':'2026-01-01','end':'2026-09-30'},'observed_at':'2026-10-02T00:00:00Z'}
        raw=json.dumps(document).encode();(self.evidence/'fact.json').write_bytes(raw)
        row={'assertion_id':'a1','artifact':'fact.json','content_sha256':hashlib.sha256(raw).hexdigest(),'kind':'json_pointer','pointer':'/value','expected':110,
             'bindings':{k:{'pointer':'/'+k,'expected':document[k]} for k in ('unit','period','observed_at')}}
        data={'schema_version':'pia_artifact_assertions_v1','as_of':'2026-10-10T05:00:00Z','assertions':[row]}
        source=self.write(self.root/'assertions.json',data)
        return source,data

    def test_artifact_claim_match_is_not_fact_or_identity_authentication(self):
        source,_=self.assertions();result=check.check(source,self.evidence,self.root/'result.json')
        self.assertEqual(result['detail_status'],'artifact_claim_match_verified')
        self.assertFalse(result['business_facts_authenticated']);self.assertFalse(result['human_identity_authenticated'])

    def test_claim_negative_contracts(self):
        mutations=[lambda r:r.update(expected=111), lambda r:r.update(expected=True),lambda r:r.update(expected=float('inf')),
                   lambda r:r.update(content_sha256='0'*64),lambda r:r.update(pointer='/missing'),lambda r:r.update(pointer='/~2bad'),
                   lambda r:r.update(artifact='../fact.json'), lambda r:r['bindings']['unit'].update(expected='USD'),
                   lambda r:r['bindings']['period'].update(expected={'start':'2026-01-01','end':'2026-10-01'}),
                   lambda r:r['bindings']['observed_at'].update(expected='2027-01-01T00:00:00Z'), lambda r:r.update(expected='  ')]
        for mutate in mutations:
            source,data=self.assertions();mutate(data['assertions'][0]);self.write(source,data)
            out=self.root/'negative.json'
            with self.subTest(mutation=mutate),self.assertRaises((ValueError,TypeError)):
                check.check(source,self.evidence,out)
            self.assertFalse(out.exists())

    def test_text_exact_lines_nonblank_and_line_bounds(self):
        source,data=self.assertions();event=self.bundle['events'][0]
        row={'assertion_id':'text','artifact':'event.txt','content_sha256':event['content_sha256'],'kind':'text_lines','start_line':1,'end_line':1,'expected':'Synthetic revenue 110'}
        data['assertions']=[row];self.write(source,data)
        self.assertEqual(check.check(source,self.evidence,self.root/'text_result.json')['status'],'complete')
        for start,end,expected in ((0,1,'x'),(True,1,'x'),(1,2,'x'),(1,1,'wrong'),(1,1,' ')):
            row.update(start_line=start,end_line=end,expected=expected);self.write(source,data)
            with self.assertRaises(ValueError):
                check.check(source,self.evidence,self.root/'text_negative.json')

    def test_pointer_escaped_tokens_and_array_index(self):
        self.assertEqual(check.pointer({'a/b':{'~':[4]}},'/a~1b/~0/0'),4)
        for loc in ('','/x/01','/x/-1','/x/1','/x/~3'):
            with self.subTest(pointer=loc),self.assertRaises(ValueError):check.pointer({'x':[1]},loc)

    def test_https_only_no_redirect_no_fake_contact(self):
        session=FakeSession([FakeResponse(302,b'redirect')])
        with self.assertRaisesRegex(ValueError,'redirect'):
            transport.request(session,'GET','https://example.test/source')
        self.assertEqual(len(session.calls),1)
        session=FakeSession([])
        with self.assertRaises(ValueError):transport.request(session,'GET','http://example.test/source')
        self.assertEqual(session.calls,[])
        self.assertNotIn('@',ec.DEFAULT_USER_AGENT)

    def test_urllib_https_checks_and_rejects_before_next_request(self):
        with self.assertRaises(ValueError):transport.open_https(Request('http://example.test'),1)
        with self.assertRaises(ValueError):transport.NoRedirect().redirect_request(None,None,302,'',{},'http://example.test')
        with mock.patch.object(transport,'build_opener') as build:
            transport.open_https(Request('https://example.test'),1)
            context=build.call_args.args[1]._context
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode,2)

    def test_https_failures_classify_broken_not_empty(self):
        f=ec.ChannelFetcher(session=FakeSession([FakeResponse(302,b'')]),cache_dir=self.root/'cache')
        result=ec.cninfo_fulltext(f,code='000001',date_from='2026-09-01',date_to='2026-10-10')
        self.assertEqual(result['health'],'broken');self.assertIn('redirect',result['error'])
        self.assertEqual(ec.classify_cninfo_fulltext({'announcements':None,'totalAnnouncement':0})[0],'broken')

    def test_isolation_paths_refuse_shell_unc_and_other_drive(self):
        self.assertEqual(isolated.linux_path(r'C:\safe dir\bundle.json'),'/mnt/c/safe dir/bundle.json')
        for path in (r'\\host\share\bundle.json',r'C:\safe;whoami',r'C:\..\x',r'D:\x','C:\\x\\',r'C:\x:stream'):
            with self.subTest(path=path),self.assertRaises(ValueError):isolated.linux_path(path)


if __name__ == '__main__':
    unittest.main()
