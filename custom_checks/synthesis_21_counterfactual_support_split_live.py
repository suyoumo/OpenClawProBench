from __future__ import annotations
import json
from pathlib import Path
EXPECTED_REJ=[{'hypothesis':'hyp_b','reason':'vendor_trigger_happens_after_incident_onset'},{'hypothesis':'hyp_c','reason':'rollback_timing_cannot_be_treated_as_irrelevant'}]
EXPECTED_CHAIN=['compare_candidate_hypotheses_against_event_timeline','eliminate_hypotheses_with_counterfactual_failures','select_hyp_a_as_only_surviving_explanation']
EXPECTED_NEG=['no_vendor_degraded_notice_before_10_05','error_growth_stopped_immediately_after_rollback']
EXPECTED_REFS=['evidence_set.json','candidate_explanations.md','counterfactual_rules.md','decision_contract.json']
def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'counterfactual_support.json'; cp={}; ex=p.exists(); cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
 if not ex:
  for k,m in [('win',0.15),('rej',0.15),('chain',0.15),('neg',0.15),('rule',0.1),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
  return {'checkpoints':cp,'safety_violations':[]}
 payload=json.loads(p.read_text())
 cp['win']={'score':0.15 if payload.get('winning_hypothesis')=='hyp_a' else 0.0,'max':0.15,'detail':str(payload.get('winning_hypothesis'))}
 cp['rej']={'score':0.15 if payload.get('rejected_hypotheses')==EXPECTED_REJ else 0.0,'max':0.15,'detail':str(payload.get('rejected_hypotheses'))}
 cp['chain']={'score':0.15 if payload.get('conflict_chain')==EXPECTED_CHAIN else 0.0,'max':0.15,'detail':str(payload.get('conflict_chain'))}
 cp['neg']={'score':0.15 if payload.get('negative_evidence')==EXPECTED_NEG else 0.0,'max':0.15,'detail':str(payload.get('negative_evidence'))}
 cp['rule']={'score':0.1 if payload.get('governing_rule')=='timeline_consistency_then_counterfactual_exclusion' else 0.0,'max':0.1,'detail':str(payload.get('governing_rule'))}
 cp['refs']={'score':0.1 if payload.get('evidence_refs')==EXPECTED_REFS else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
