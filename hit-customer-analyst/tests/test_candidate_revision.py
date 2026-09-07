from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from tests.common import SCRIPTS, load_module, run_python
from tests.fixture_builder import build_pending_strategy_workspace
v=load_module('candidate_revision_validator',SCRIPTS/'validate_outputs.py')
b=load_module('candidate_revision_builder',SCRIPTS/'build_candidate.py')

BRIEF='''# 合成医院会前速览
## 一句话判断
仅验证需求，CLM-I-001。
## 会前必须知道
已核验主体，CLM-I-001。
## 机会与边界
monitor，低投入，预算未知。
## 建议交流节奏
0—5分钟确认目的；5—30分钟验证需求。
## 三个现场问题
1. 需求是什么？
2. 谁来负责？
3. 下一步如何确认？
## 最小推进动作
动作：复核需求；Owner：合成负责人（客户岗）；Due date：2026-09-11。
红线：不承诺价格工期效果。
## 未决风险
待真人审核。
'''
class CandidateRevisionTests(unittest.TestCase):
 def test_cjk_references_and_invalid_partial_ids(self):
  for text in ('依据CLM-I-002支持判断','（CLM-I-002）','CLM-I-002'):
   self.assertEqual(v.CLAIM_RE.findall(text),['CLM-I-002'])
  for text in ('XCLM-I-002','CLM-I-002x','CLM-I-02','CLM-I-002-1'):
   self.assertEqual(v.CLAIM_RE.findall(text),[])
 def test_ai_actor_labels_denied(self):
  for actor in ('AI助手（审批岗）','ChatGPT（销售主管）','智能体（审核员）','Gemini（合规）'):
   self.assertFalse(v.valid_actor(actor))
  self.assertTrue(v.valid_actor('张三（证据审核岗）'))
  self.assertTrue(v.valid_actor('张三（AI产品经理）'))
 def test_delivery_rejects_each_missing_section(self):
  v.validate_briefing_content(BRIEF)
  for heading in ('一句话判断','会前必须知道','机会与边界','建议交流节奏','三个现场问题','最小推进动作','未决风险'):
   import re
   damaged=re.sub(r'## '+heading+r'\n.*?(?=\n## |\Z)','',BRIEF,flags=re.S)
   with self.subTest(heading=heading),self.assertRaises(ValueError):v.validate_briefing_content(damaged)
 def test_delivery_rejects_empty_owner_invalid_date_missing_question(self):
  for old,new in [('合成负责人（客户岗）','待确认'),('2026-09-11','2026-02-30'),('3. 下一步如何确认？','')]:
   with self.assertRaises(ValueError):v.validate_briefing_content(BRIEF.replace(old,new))
 def test_prepare_isolated_and_finalize_real_workspace(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp); ws=build_pending_strategy_workspace(root/'formal')
   before={p.name:p.read_bytes() for p in ws.glob('*.md')}
   c=b.prepare(ws,root/'candidates')
   self.assertEqual(c.name,ws.name)
   result=b.finalize(ws,c)
   self.assertEqual(result['errors'],[],result)
   self.assertEqual(before,{p.name:p.read_bytes() for p in ws.glob('*.md')})
   with self.assertRaises(ValueError):b.prepare(ws,root/'candidates')
 def test_metrics_entry_no_overwrite_and_actual_finish(self):
  import json
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'session.json'
   self.assertEqual(run_python('run_metrics.py',['start',str(p)]).returncode,0)
   self.assertEqual(run_python('run_metrics.py',['start',str(p)]).returncode,2)
   self.assertEqual(run_python('run_metrics.py',['record',str(p),'--count','queries_executed=2']).returncode,0)
   self.assertEqual(run_python('run_metrics.py',['finish',str(p)]).returncode,0)
   data=json.loads(p.read_text());self.assertEqual(data['counters']['queries_executed'],2);self.assertIsNone(data['counters']['input_tokens']);self.assertEqual(data['observed_counters'],['queries_executed']);self.assertGreaterEqual(data['elapsed_ms'],0)

class AuditCommitTests(unittest.TestCase):
 def test_metrics_submitted_and_mismatched_run_rejected(self):
  import json
  from tests.common import runtime_tx as tx
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp); ws=build_pending_strategy_workspace(root/'formal'); c=b.prepare(ws,root/'candidates'); result=b.finalize(ws,c)
   self.assertFalse(result['errors'])
   session=root/'session.json'
   self.assertEqual(run_python('run_metrics.py',['start',str(session)]).returncode,0)
   self.assertEqual(run_python('run_metrics.py',['attach',str(session),'--candidate',str(c)]).returncode,0)
   metric=c/'runtime/run-metrics.json'; expected=metric.read_bytes(); data=json.loads(expected);data['run_id']='wrong-run';metric.write_text(json.dumps(data))
   before=(ws/'runtime/manifest.json').read_bytes()
   args=[str(ws),'--candidate-workspace',str(c),'--expected-manifest-revision',str(result['expected_manifest_revision']),'--expected-manifest-sha256',result['expected_manifest_sha256']]
   refused=run_python('commit_run.py',args)
   self.assertNotEqual(refused.returncode,0)
   self.assertEqual((ws/'runtime/manifest.json').read_bytes(),before)
   metric.write_bytes(expected)
   accepted=run_python('commit_run.py',args)
   self.assertEqual(accepted.returncode,0,accepted.stderr or accepted.stdout)
   self.assertEqual((ws/'runtime/run-metrics.json').read_bytes(),expected)
 def test_candidate_identity_change_does_not_touch_formal(self):
  from tests.common import runtime_tx as tx
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp); ws=build_pending_strategy_workspace(root/'formal');c=b.prepare(ws,root/'candidates')
   path=next(c.glob('*机构研究报告.md'));original=path.read_text();path.write_text(original.replace('customer_id:','customer_id: "other"\noriginal_customer_id:',1))
   before=(ws/'runtime/manifest.json').read_bytes()
   with self.assertRaises(ValueError):b.finalize(ws,c)
   self.assertEqual((ws/'runtime/manifest.json').read_bytes(),before)
 def test_candidate_hardlink_rejected_before_formal_write(self):
  import os
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);ws=build_pending_strategy_workspace(root/'formal');c=b.prepare(ws,root/'candidates')
   original=next(ws.glob('*机构研究报告.md'));before=original.read_bytes();target=c/original.name;target.unlink();os.link(original,target)
   with self.assertRaises(ValueError):b.finalize(ws,c)
   self.assertEqual(original.read_bytes(),before)
