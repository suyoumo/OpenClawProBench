from __future__ import annotations
import json
from pathlib import Path
from harness.custom_check_helpers import evidence_refs_match
EXPECTED_ACCEPT=[{'window':'w1','request':'req_a'},{'window':'w2','request':'req_c'}]
EXPECTED_REJ=[{'request':'req_b','reason':'exception_not_enabled_for_requested_window'},{'request':'req_d','reason':'insufficient_remaining_capacity'},{'request':'req_e','reason':'fails_base_window_eligibility'}]
EXPECTED_CHAIN=['apply_window_capacity','check_exception_enablement','accept_remaining_highest_priority_requests']
EXPECTED_UNUSED=[{'window':'w1','remaining':0},{'window':'w2','remaining':0}]
EXPECTED_REFS=['requests.json','resource_windows.md','exception_rules.json','selection_contract.txt']
def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'temporal_resource_exception.json'; cp={}; ex=p.exists(); cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
 if not ex:
  for k,m in [('accept',0.15),('rej',0.15),('chain',0.15),('exc',0.1),('unused',0.15),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
  return {'checkpoints':cp,'safety_violations':[]}
 payload=json.loads(p.read_text())
 cp['accept']={'score':0.15 if payload.get('accepted_schedule')==EXPECTED_ACCEPT else 0.0,'max':0.15,'detail':str(payload.get('accepted_schedule'))}
 cp['rej']={'score':0.15 if payload.get('rejected_requests')==EXPECTED_REJ else 0.0,'max':0.15,'detail':str(payload.get('rejected_requests'))}
 cp['chain']={'score':0.15 if payload.get('constraint_chain')==EXPECTED_CHAIN else 0.0,'max':0.15,'detail':str(payload.get('constraint_chain'))}
 cp['exc']={'score':0.1 if payload.get('governing_exception')=='w2_priority_exception_only' else 0.0,'max':0.1,'detail':str(payload.get('governing_exception'))}
 cp['unused']={'score':0.15 if payload.get('unused_capacity')==EXPECTED_UNUSED else 0.0,'max':0.15,'detail':str(payload.get('unused_capacity'))}
 cp['refs']={'score':0.1 if evidence_refs_match(payload.get('evidence_refs'), EXPECTED_REFS) else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
