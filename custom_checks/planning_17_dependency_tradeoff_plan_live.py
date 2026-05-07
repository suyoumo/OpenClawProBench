from __future__ import annotations
import json
import re
from pathlib import Path
from harness.custom_check_helpers import evidence_refs_match
EXPECTED_NOW=['schema-prepare','service-cutover','smoke-verify']
EXPECTED_DEFER=[{'task':'analytics-rebuild','reason':'outside_current_delivery_window'},{'task':'cache-warm','reason':'depends_on_unexecuted_analytics-rebuild'},{'task':'report-migration','reason':'insufficient_capacity_after_higher_priority_chain'}]
EXPECTED_ORDER=['schema-prepare','service-cutover','smoke-verify']
EXPECTED_REFS=['task_graph.json','capacity.json','priority_rules.md','delivery_window.json']
EXPECTED_DEFER_TASKS=['analytics-rebuild','cache-warm','report-migration']

def _text(raw:object)->str:
 return re.sub(r'[_\-\s]+',' ',str(raw).lower()).strip()

def _ordered_chain_ok(raw:object)->bool:
 if raw==EXPECTED_ORDER:
  return True
 if not isinstance(raw,list) or len(raw)!=3:
  return False
 text=' '.join(_text(item) for item in raw)
 first=text.find('schema prepare')
 second=text.find('service cutover')
 third=text.find('smoke verify')
 return first!=-1 and second!=-1 and third!=-1 and first<second<third

def _defer_ok(raw:object)->bool:
 if raw==EXPECTED_DEFER:
  return True
 if not isinstance(raw,list) or len(raw)!=3:
  return False
 tasks=[item.get('task') for item in raw if isinstance(item,dict)]
 if tasks!=EXPECTED_DEFER_TASKS:
  return False
 return all(isinstance(item,dict) and str(item.get('reason','')).strip() for item in raw)

def _rule_ok(raw:object)->bool:
 text=_text(raw)
 return raw=='deliver_closed_high_priority_chain_within_window' or all(term in text for term in ('priority','dependency','chain','window'))

def _justification_ok(raw:object)->bool:
 if raw==['dependency_closed_chain_must_be_completed_first','capacity_allows_only_one_priority_chain_now','delivery_window_excludes_lower_priority_follow_on_tasks']:
  return True
 if not isinstance(raw,list) or len(raw)!=3:
  return False
 text=' '.join(_text(item) for item in raw)
 has_dependency='dependency' in text and 'chain' in text
 has_capacity='capacity' in text or 'slot' in text or '3' in text
 has_delivery=('delivery' in text or 'window' in text or 'today' in text) and ('priority' in text or 'excluded' in text)
 return has_dependency and has_capacity and has_delivery

def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'dependency_tradeoff_plan.json'; cp={}; ex=p.exists(); cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
 if not ex:
  for k,m in [('now',0.2),('defer',0.2),('order',0.15),('rule',0.1),('just',0.15),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
  return {'checkpoints':cp,'safety_violations':[]}
 payload=json.loads(p.read_text())
 cp['now']={'score':0.2 if payload.get('execute_now')==EXPECTED_NOW else 0.0,'max':0.2,'detail':str(payload.get('execute_now'))}
 cp['defer']={'score':0.2 if _defer_ok(payload.get('defer')) else 0.0,'max':0.2,'detail':str(payload.get('defer'))}
 cp['order']={'score':0.15 if _ordered_chain_ok(payload.get('dependency_order')) else 0.0,'max':0.15,'detail':str(payload.get('dependency_order'))}
 cp['rule']={'score':0.1 if _rule_ok(payload.get('governing_rule')) else 0.0,'max':0.1,'detail':str(payload.get('governing_rule'))}
 cp['just']={'score':0.15 if _justification_ok(payload.get('justification')) else 0.0,'max':0.15,'detail':str(payload.get('justification'))}
 cp['refs']={'score':0.1 if evidence_refs_match(payload.get('evidence_refs'), EXPECTED_REFS) else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
