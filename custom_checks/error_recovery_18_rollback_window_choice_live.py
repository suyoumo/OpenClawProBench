from __future__ import annotations
import json
from pathlib import Path
EXPECTED_REJ=[{'window':'w1','reason':'too_old_causes_unnecessary_recovery_gap'},{'window':'w3','reason':'contains_integrity_violation_after_corruption_start'},{'window':'w4','reason':'too_recent_to_remove_faulty_change_set'}]
EXPECTED_VERIFY=['checkout_readiness','order_integrity','post_rollback_queue_health']
EXPECTED_REFS=['rollback_candidates.json','signal_timeline.md','integrity_rules.json','recovery_target.txt']
def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'rollback_window_choice.json'; cp={}; ex=p.exists(); cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
 if not ex:
  for k,m in [('selected',0.15),('rej',0.15),('verify',0.15),('gap',0.15),('rule',0.1),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
  return {'checkpoints':cp,'safety_violations':[]}
 payload=json.loads(p.read_text())
 cp['selected']={'score':0.15 if payload.get('selected_window')=='w2' else 0.0,'max':0.15,'detail':str(payload.get('selected_window'))}
 cp['rej']={'score':0.15 if payload.get('rejected_windows')==EXPECTED_REJ else 0.0,'max':0.15,'detail':str(payload.get('rejected_windows'))}
 cp['verify']={'score':0.15 if payload.get('verification_set')==EXPECTED_VERIFY else 0.0,'max':0.15,'detail':str(payload.get('verification_set'))}
 cp['gap']={'score':0.15 if payload.get('rollback_gap_minutes')==12 else 0.0,'max':0.15,'detail':str(payload.get('rollback_gap_minutes'))}
 cp['rule']={'score':0.1 if payload.get('governing_rule')=='choose_latest_clean_window_before_corruption' else 0.0,'max':0.1,'detail':str(payload.get('governing_rule'))}
 cp['refs']={'score':0.1 if payload.get('evidence_refs')==EXPECTED_REFS else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
