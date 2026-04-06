from __future__ import annotations
import json
from pathlib import Path
EXPECTED_DENIED=[{'request':'req_b','reason':'exception_missing_required_security_approval'},{'request':'req_c','reason':'exception_does_not_override_higher_base_priority'}]
EXPECTED_CHAIN=['apply_base_priority_matrix','validate_exception_eligibility','confirm_req_a_remains_winner']
EXPECTED_REFS=['request_queue.json','exception_policy.md','priority_matrix.json','resolution_contract.json']
def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'priority_exception_resolution.json'; cp={}; ex=p.exists(); cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
 if not ex:
  for k,m in [('winner',0.2),('denied',0.2),('chain',0.2),('exception',0.1),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
  return {'checkpoints':cp,'safety_violations':[]}
 payload=json.loads(p.read_text())
 cp['winner']={'score':0.2 if payload.get('winning_request')=='req_a' else 0.0,'max':0.2,'detail':str(payload.get('winning_request'))}
 cp['denied']={'score':0.2 if payload.get('denied_exceptions')==EXPECTED_DENIED else 0.0,'max':0.2,'detail':str(payload.get('denied_exceptions'))}
 cp['chain']={'score':0.2 if payload.get('rule_chain')==EXPECTED_CHAIN else 0.0,'max':0.2,'detail':str(payload.get('rule_chain'))}
 cp['exception']={'score':0.1 if payload.get('governing_exception')=='no_valid_exception_applies' else 0.0,'max':0.1,'detail':str(payload.get('governing_exception'))}
 cp['refs']={'score':0.1 if payload.get('evidence_refs')==EXPECTED_REFS else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
