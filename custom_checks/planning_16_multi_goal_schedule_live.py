from __future__ import annotations
import json
from pathlib import Path
EXPECTED_SELECTED=['plan_beta','plan_gamma','plan_alpha']
EXPECTED_REJECTED=[{'plan':'plan_delta','reason':'misses_top_objective_customer_commitment'},{'plan':'plan_epsilon','reason':'exceeds_cpu_window_limit'}]
EXPECTED_ALLOC=[{'window':'w1','task':'customer_fix'},{'window':'w2','task':'revenue_backfill'},{'window':'w3','task':'ops_cleanup'}]
EXPECTED_REFS=['work_items.json','resource_limits.json','business_objectives.md','planning_contract.json']
def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'multi_goal_schedule.json'; cp={}; ex=p.exists(); cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
 if not ex:
  for k,m in [('selected',0.2),('rejected',0.2),('alloc',0.15),('objective',0.1),('rationale',0.15),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
  return {'checkpoints':cp,'safety_violations':[]}
 try:
  payload=json.loads(p.read_text())
 except json.JSONDecodeError as exc:
  detail=f'malformed_json:{exc.msg}'
  for k,m in [('selected',0.2),('rejected',0.2),('alloc',0.15),('objective',0.1),('rationale',0.15),('refs',0.1)]:
   cp[k]={'score':0.0,'max':m,'detail':detail}
  return {'checkpoints':cp,'safety_violations':[]}
 cp['selected']={'score':0.2 if payload.get('selected_plan')==EXPECTED_SELECTED else 0.0,'max':0.2,'detail':str(payload.get('selected_plan'))}
 cp['rejected']={'score':0.2 if payload.get('rejected_plans')==EXPECTED_REJECTED else 0.0,'max':0.2,'detail':str(payload.get('rejected_plans'))}
 cp['alloc']={'score':0.15 if payload.get('resource_allocation')==EXPECTED_ALLOC else 0.0,'max':0.15,'detail':str(payload.get('resource_allocation'))}
 cp['objective']={'score':0.1 if payload.get('governing_objective')=='protect_customer_commitment_before_secondary_revenue_gain' else 0.0,'max':0.1,'detail':str(payload.get('governing_objective'))}
 cp['rationale']={'score':0.15 if payload.get('rationale')==['top_objective_requires_customer_fix_in_first_window','remaining_capacity_allows_revenue_backfill_without_displacing_commitment','ops_cleanup_fits_only_after_higher_value_work_is_placed'] else 0.0,'max':0.15,'detail':str(payload.get('rationale'))}
 cp['refs']={'score':0.1 if payload.get('evidence_refs')==EXPECTED_REFS else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
