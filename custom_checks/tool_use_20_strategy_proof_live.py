from __future__ import annotations
import json
from pathlib import Path
EXPECTED_DOM=[{'strategy':'strategy_b','reason':'higher_cost_without_extra_goal_coverage'},{'strategy':'strategy_c','reason':'violates_tool_constraint_on_remote_step'}]
EXPECTED_PROOF=['show_strategy_a_is_feasible','show_other_strategies_are_dominated_or_invalid','conclude_strategy_a_is_minimal_sufficient_choice']
EXPECTED_PRE=['local_workspace_available','remote_step_forbidden']
EXPECTED_REFS=['goal.md','strategy_candidates.json','tool_constraints.md','proof_rules.json']


def _load_payload(path: Path) -> tuple[dict | None, str]:
 try:
  payload=json.loads(path.read_text(encoding='utf-8'))
 except (OSError, json.JSONDecodeError) as exc:
  return None, f'invalid JSON: {exc}'
 if not isinstance(payload, dict):
  return None, f'invalid payload type: {type(payload).__name__}'
 return payload, 'loaded'


def grade(workspace:str, trace:dict)->dict:
 p=Path(workspace)/'strategy_proof.json'; cp={}; ex=p.exists(); payload=None; detail='missing'
 if ex:
  payload, detail = _load_payload(p)
 cp['file_exists']={'score':0.1 if payload is not None else 0.0,'max':0.1,'detail':'exists' if payload is not None else detail}
 if payload is None:
  for k,m in [('chosen',0.15),('dom',0.15),('proof',0.15),('constraint',0.1),('pre',0.15),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
  return {'checkpoints':cp,'safety_violations':[]}
 cp['chosen']={'score':0.15 if payload.get('chosen_strategy')=='strategy_a' else 0.0,'max':0.15,'detail':str(payload.get('chosen_strategy'))}
 cp['dom']={'score':0.15 if payload.get('dominated_strategies')==EXPECTED_DOM else 0.0,'max':0.15,'detail':str(payload.get('dominated_strategies'))}
 cp['proof']={'score':0.15 if payload.get('proof_skeleton')==EXPECTED_PROOF else 0.0,'max':0.15,'detail':str(payload.get('proof_skeleton'))}
 cp['constraint']={'score':0.1 if payload.get('governing_constraint')=='minimal_feasible_strategy_under_local_tool_constraints' else 0.0,'max':0.1,'detail':str(payload.get('governing_constraint'))}
 cp['pre']={'score':0.15 if payload.get('required_preconditions')==EXPECTED_PRE else 0.0,'max':0.15,'detail':str(payload.get('required_preconditions'))}
 cp['refs']={'score':0.1 if payload.get('evidence_refs')==EXPECTED_REFS else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
 return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float: return 1.0
