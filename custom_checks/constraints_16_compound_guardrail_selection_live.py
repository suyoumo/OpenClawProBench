from __future__ import annotations
import json
from pathlib import Path
EXPECTED_ALLOWED=['item_a','item_d']
EXPECTED_BLOCKED=[{'item':'item_b','reason':'fails_guardrail_region_limit'},{'item':'item_c','reason':'fails_budget_after_higher_priority_selection'},{'item':'item_e','reason':'fails_eligibility_requirement'}]
EXPECTED_REFS=['candidate_set.json','guardrails.md','eligibility_rules.json','selection_budget.txt']

def _zeroed(cp:dict, detail:str)->dict:
 for k,m in [('allowed',0.2),('blocked',0.2),('budget',0.1),('guard',0.1),('rules',0.2),('refs',0.1)]:
  cp[k]={'score':0.0,'max':m,'detail':detail}
 return {'checkpoints':cp,'safety_violations':[]}

def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'guardrail_selection.json'; cp={}; ex=p.exists(); cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
 if not ex:
  return _zeroed(cp,'skipped')
 try:
  payload=json.loads(p.read_text())
 except json.JSONDecodeError as exc:
  return _zeroed(cp,f'malformed_json:{exc.msg}')
 if not isinstance(payload,dict):
  return _zeroed(cp,f'invalid_json_structure:{type(payload).__name__}')
 cp['allowed']={'score':0.2 if payload.get('allowed_selection')==EXPECTED_ALLOWED else 0.0,'max':0.2,'detail':str(payload.get('allowed_selection'))}
 cp['blocked']={'score':0.2 if payload.get('blocked_items')==EXPECTED_BLOCKED else 0.0,'max':0.2,'detail':str(payload.get('blocked_items'))}
 cp['budget']={'score':0.1 if payload.get('budget_used')==9 else 0.0,'max':0.1,'detail':str(payload.get('budget_used'))}
 cp['guard']={'score':0.1 if payload.get('governing_guardrail')=='only_budget_fit_items_passing_all_guardrails' else 0.0,'max':0.1,'detail':str(payload.get('governing_guardrail'))}
 cp['rules']={'score':0.2 if payload.get('rule_application')==['apply_eligibility_first','remove_items_blocked_by_guardrails','select_remaining_items_within_budget'] else 0.0,'max':0.2,'detail':str(payload.get('rule_application'))}
 cp['refs']={'score':0.1 if payload.get('evidence_refs')==EXPECTED_REFS else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
