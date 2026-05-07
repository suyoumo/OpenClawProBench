from __future__ import annotations
import json
import re
from pathlib import Path
from harness.custom_check_helpers import evidence_refs_match
EXPECTED_ALLOWED=['item_a','item_d']
EXPECTED_BLOCKED=[{'item':'item_b','reason':'fails_guardrail_region_limit'},{'item':'item_c','reason':'fails_budget_after_higher_priority_selection'},{'item':'item_e','reason':'fails_eligibility_requirement'}]
EXPECTED_REFS=['candidate_set.json','guardrails.md','eligibility_rules.json','selection_budget.txt']
EXPECTED_BLOCKED_TASKS=['item_b','item_c','item_e']

def _text(raw:object)->str:
 return re.sub(r'[_\-\s]+',' ',str(raw).lower()).strip()

def _blocked_ok(raw:object)->bool:
 if raw==EXPECTED_BLOCKED:
  return True
 if not isinstance(raw,list) or len(raw)!=3:
  return False
 tasks=[item.get('item') for item in raw if isinstance(item,dict)]
 if tasks!=EXPECTED_BLOCKED_TASKS:
  return False
 reasons={item.get('item'):_text(item.get('reason')) for item in raw if isinstance(item,dict)}
 b_ok='region' in reasons.get('item_b','') or 'guardrail' in reasons.get('item_b','')
 c_ok='budget' in reasons.get('item_c','') or 'tie' in reasons.get('item_c','') or 'lexicographic' in reasons.get('item_c','')
 e_ok='eligib' in reasons.get('item_e','') or 'ineligible' in reasons.get('item_e','')
 return b_ok and c_ok and e_ok

def _guard_ok(raw:object)->bool:
 text=_text(raw)
 return raw=='only_budget_fit_items_passing_all_guardrails' or ('budget' in text and ('guardrail' in text or 'region' in text))

def _rules_ok(raw:object)->bool:
 if raw==['apply_eligibility_first','remove_items_blocked_by_guardrails','select_remaining_items_within_budget']:
  return True
 if not isinstance(raw,list) or len(raw)!=3:
  return False
 text=' '.join(_text(item) for item in raw)
 return 'eligib' in text and ('guardrail' in text or 'region' in text) and 'budget' in text

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
 cp['blocked']={'score':0.2 if _blocked_ok(payload.get('blocked_items')) else 0.0,'max':0.2,'detail':str(payload.get('blocked_items'))}
 cp['budget']={'score':0.1 if payload.get('budget_used')==9 else 0.0,'max':0.1,'detail':str(payload.get('budget_used'))}
 cp['guard']={'score':0.1 if _guard_ok(payload.get('governing_guardrail')) else 0.0,'max':0.1,'detail':str(payload.get('governing_guardrail'))}
 cp['rules']={'score':0.2 if _rules_ok(payload.get('rule_application')) else 0.0,'max':0.2,'detail':str(payload.get('rule_application'))}
 cp['refs']={'score':0.1 if evidence_refs_match(payload.get('evidence_refs'), EXPECTED_REFS) else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
