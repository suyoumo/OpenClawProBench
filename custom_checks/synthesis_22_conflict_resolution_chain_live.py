from __future__ import annotations
import json
from pathlib import Path
EXPECTED_INV=[{'claim':'claim_b','reason':'contradicted_by_observation_o2'},{'claim':'claim_c','reason':'fails_resolution_priority_rule'}]
EXPECTED_CHAIN=['apply_observation_consistency','remove_contradicted_claims','select_highest_priority_remaining_claim']
EXPECTED_REFS=['claims.json','observations.md','resolution_policy.md','output_spec.json']
def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'conflict_resolution_chain.json'; cp={}; ex=p.exists(); cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
 if not ex:
  for k,m in [('win',0.2),('invalid',0.2),('chain',0.2),('rule',0.1),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
  return {'checkpoints':cp,'safety_violations':[]}
 payload=json.loads(p.read_text())
 cp['win']={'score':0.2 if payload.get('winning_claim')=='claim_a' else 0.0,'max':0.2,'detail':str(payload.get('winning_claim'))}
 cp['invalid']={'score':0.2 if payload.get('invalidated_claims')==EXPECTED_INV else 0.0,'max':0.2,'detail':str(payload.get('invalidated_claims'))}
 cp['chain']={'score':0.2 if payload.get('conflict_chain')==EXPECTED_CHAIN else 0.0,'max':0.2,'detail':str(payload.get('conflict_chain'))}
 cp['rule']={'score':0.1 if payload.get('governing_resolution_rule')=='consistency_then_priority' else 0.0,'max':0.1,'detail':str(payload.get('governing_resolution_rule'))}
 cp['refs']={'score':0.1 if payload.get('evidence_refs')==EXPECTED_REFS else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
