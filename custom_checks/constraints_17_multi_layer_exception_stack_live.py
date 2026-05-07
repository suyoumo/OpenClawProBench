from __future__ import annotations
import json
from pathlib import Path
from harness.custom_check_helpers import evidence_refs_match
EXPECTED_DENIED=[{'path':'path_b','reason':'missing_mid_layer_exception_precondition'},{'path':'path_c','reason':'top_layer_override_not_reached'}]
EXPECTED_STACK=['apply_base_rule','validate_mid_layer_exception','confirm_path_a_survives_top_layer_filter']
EXPECTED_REFS=['base_rules.json','exception_stack.md','request_case.json','resolution_rules.txt']
def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'exception_stack_resolution.json'; cp={}; ex=p.exists(); cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
 if not ex:
  for k,m in [('survive',0.2),('deny',0.2),('stack',0.2),('result',0.1),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
  return {'checkpoints':cp,'safety_violations':[]}
 payload=json.loads(p.read_text())
 cp['survive']={'score':0.2 if payload.get('surviving_path')=='path_a' else 0.0,'max':0.2,'detail':str(payload.get('surviving_path'))}
 cp['deny']={'score':0.2 if payload.get('denied_paths')==EXPECTED_DENIED else 0.0,'max':0.2,'detail':str(payload.get('denied_paths'))}
 cp['stack']={'score':0.2 if payload.get('rule_stack')==EXPECTED_STACK else 0.0,'max':0.2,'detail':str(payload.get('rule_stack'))}
 cp['result']={'score':0.1 if payload.get('governing_result')=='path_a_only' else 0.0,'max':0.1,'detail':str(payload.get('governing_result'))}
 cp['refs']={'score':0.1 if evidence_refs_match(payload.get('evidence_refs'), EXPECTED_REFS) else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
