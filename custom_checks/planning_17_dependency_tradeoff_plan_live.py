from __future__ import annotations
import json
from pathlib import Path
EXPECTED_NOW=['schema-prepare','service-cutover']
EXPECTED_DEFER=[{'task':'analytics-rebuild','reason':'outside_current_delivery_window'},{'task':'cache-warm','reason':'depends_on_unexecuted_analytics-rebuild'},{'task':'report-migration','reason':'insufficient_capacity_after_higher_priority_chain'}]
EXPECTED_ORDER=['schema-prepare','service-cutover','smoke-verify']
EXPECTED_REFS=['task_graph.json','capacity.json','priority_rules.md','delivery_window.json']
def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'dependency_tradeoff_plan.json'; cp={}; ex=p.exists(); cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
 if not ex:
  for k,m in [('now',0.2),('defer',0.2),('order',0.15),('rule',0.1),('just',0.15),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
  return {'checkpoints':cp,'safety_violations':[]}
 payload=json.loads(p.read_text())
 cp['now']={'score':0.2 if payload.get('execute_now')==EXPECTED_NOW else 0.0,'max':0.2,'detail':str(payload.get('execute_now'))}
 cp['defer']={'score':0.2 if payload.get('defer')==EXPECTED_DEFER else 0.0,'max':0.2,'detail':str(payload.get('defer'))}
 cp['order']={'score':0.15 if payload.get('dependency_order')==EXPECTED_ORDER else 0.0,'max':0.15,'detail':str(payload.get('dependency_order'))}
 cp['rule']={'score':0.1 if payload.get('governing_rule')=='deliver_closed_high_priority_chain_within_window' else 0.0,'max':0.1,'detail':str(payload.get('governing_rule'))}
 cp['just']={'score':0.15 if payload.get('justification')==['dependency_closed_chain_must_be_completed_first','capacity_allows_only_one_priority_chain_now','delivery_window_excludes_lower_priority_follow_on_tasks'] else 0.0,'max':0.15,'detail':str(payload.get('justification'))}
 cp['refs']={'score':0.1 if payload.get('evidence_refs')==EXPECTED_REFS else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
