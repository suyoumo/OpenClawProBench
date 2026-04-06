from __future__ import annotations
import json
from pathlib import Path
EXPECTED_REJECTED=[{'action':'full_rebuild','reason':'too_slow_for_sla_window'},{'action':'manual_row_repair','reason':'data_risk_remains_high_under_time_limit'},{'action':'traffic_drain_then_investigate','reason':'does_not_restore_critical_path_in_time'}]
EXPECTED_VERIFY=['checkout_smoke_test','order_write_guard','tax_response_validation']
EXPECTED_REFS=['incident_snapshot.json','candidate_actions.json','sla_constraints.md','validation_rules.json']
def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'short_window_recovery.json'; cp={}; ex=p.exists(); cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
 if not ex:
  for k,m in [('selected',0.2),('rejected',0.2),('verify',0.2),('constraint',0.1),('minutes',0.1),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
  return {'checkpoints':cp,'safety_violations':[]}
 payload=json.loads(p.read_text())
 cp['selected']={'score':0.2 if payload.get('selected_action')=='rollback_last_config_and_replay_safe_queue' else 0.0,'max':0.2,'detail':str(payload.get('selected_action'))}
 cp['rejected']={'score':0.2 if payload.get('rejected_actions')==EXPECTED_REJECTED else 0.0,'max':0.2,'detail':str(payload.get('rejected_actions'))}
 cp['verify']={'score':0.2 if payload.get('verification_steps')==EXPECTED_VERIFY else 0.0,'max':0.2,'detail':str(payload.get('verification_steps'))}
 cp['constraint']={'score':0.1 if payload.get('governing_constraint')=='restore_checkout_under_15_minutes_without_expanding_data_risk' else 0.0,'max':0.1,'detail':str(payload.get('governing_constraint'))}
 cp['minutes']={'score':0.1 if payload.get('expected_restore_minutes')==12 else 0.0,'max':0.1,'detail':str(payload.get('expected_restore_minutes'))}
 cp['refs']={'score':0.1 if payload.get('evidence_refs')==EXPECTED_REFS else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
