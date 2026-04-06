from __future__ import annotations
import json
from pathlib import Path
EXPECTED_SELECTED=['read_error_budget','read_recent_alerts','read_release_note']
EXPECTED_SKIPPED=[{'action':'query_full_audit_archive','reason':'over_budget_for_incremental_signal_gain'},{'action':'run_expensive_trace_join','reason':'budget_exceeded_after_required_signal_coverage'},{'action':'scan_all_service_logs','reason':'redundant_given_selected_signal_sources'}]
EXPECTED_SIGNALS=['budget_breach_risk','recent_regression_signal']
EXPECTED_REFS=['investigation_goal.md','action_costs.json','signal_map.json','budget_rules.md']
def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'budgeted_evidence_plan.json'; cp={}; ex=p.exists(); cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
 if not ex:
  for k,m in [('selected',0.2),('skipped',0.2),('signals',0.15),('budget',0.1),('tradeoff',0.15),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
  return {'checkpoints':cp,'safety_violations':[]}
 payload=json.loads(p.read_text())
 cp['selected']={'score':0.2 if payload.get('selected_actions')==EXPECTED_SELECTED else 0.0,'max':0.2,'detail':str(payload.get('selected_actions'))}
 cp['skipped']={'score':0.2 if payload.get('skipped_actions')==EXPECTED_SKIPPED else 0.0,'max':0.2,'detail':str(payload.get('skipped_actions'))}
 cp['signals']={'score':0.15 if payload.get('expected_signal_coverage')==EXPECTED_SIGNALS else 0.0,'max':0.15,'detail':str(payload.get('expected_signal_coverage'))}
 cp['budget']={'score':0.1 if payload.get('budget_used')==9 else 0.0,'max':0.1,'detail':str(payload.get('budget_used'))}
 cp['tradeoff']={'score':0.15 if payload.get('governing_tradeoff')=='cover_required_signals_before_optional_high_cost_actions' else 0.0,'max':0.15,'detail':str(payload.get('governing_tradeoff'))}
 cp['refs']={'score':0.1 if payload.get('evidence_refs')==EXPECTED_REFS else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
