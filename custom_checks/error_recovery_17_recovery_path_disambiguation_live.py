from __future__ import annotations
import json
from pathlib import Path
EXPECTED_RULED=[{'path':'path_b','reason':'fast_but_violates_data_integrity_rule'},{'path':'path_c','reason':'meets_goal_too_late_for_recovery_window'},{'path':'path_d','reason':'requires_unavailable_precondition'}]
EXPECTED_VERIFY=['restore_primary_api','verify_order_consistency','verify_downstream_replay_state']
EXPECTED_REFS=['incident_paths.json','system_signals.md','risk_rules.json','recovery_goal.txt']
def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'recovery_path_decision.json'; cp={}; ex=p.exists(); cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
 if not ex:
  for k,m in [('chosen',0.2),('ruled',0.2),('verify',0.2),('risk',0.1),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
  return {'checkpoints':cp,'safety_violations':[]}
 payload=json.loads(p.read_text())
 cp['chosen']={'score':0.2 if payload.get('chosen_path')=='path_a' else 0.0,'max':0.2,'detail':str(payload.get('chosen_path'))}
 cp['ruled']={'score':0.2 if payload.get('ruled_out_paths')==EXPECTED_RULED else 0.0,'max':0.2,'detail':str(payload.get('ruled_out_paths'))}
 cp['verify']={'score':0.2 if payload.get('verification_order')==EXPECTED_VERIFY else 0.0,'max':0.2,'detail':str(payload.get('verification_order'))}
 cp['risk']={'score':0.1 if payload.get('governing_risk_rule')=='preserve_integrity_before_speed_only_paths' else 0.0,'max':0.1,'detail':str(payload.get('governing_risk_rule'))}
 cp['refs']={'score':0.1 if payload.get('evidence_refs')==EXPECTED_REFS else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
