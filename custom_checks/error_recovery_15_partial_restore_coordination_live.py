"""Custom checks for error_recovery_15_partial_restore_coordination_live."""
from __future__ import annotations
import json
from pathlib import Path
from harness.custom_check_helpers import evidence_refs_match
EXPECTED_NOW=['config-service','status-api']
EXPECTED_LATER=[
    {'service':'checkout-api','reason':'depends_on_unrestored_payment-adapter'},
    {'service':'payment-adapter','reason':'upstream_gateway_state_not_yet_clean'},
    {'service':'receipt-worker','reason':'low_priority_until_checkout_path_recovers'},
]
EXPECTED_ORDER=['config-service','status-api','checkout-api']
EXPECTED_CHECKS=['config_consistency','status_api_readiness','checkout_dependency_probe']
EXPECTED_REFS=['service_graph.json','restore_status.json','dependency_rules.md','customer_impact.json']
def grade(workspace:str, trace:dict)->dict:
    ws=Path(workspace); cp={}; p=ws/'partial_restore_plan.json'; ex=p.exists()
    cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
    if not ex:
        for k,m in [('now',0.15),('later',0.2),('order',0.15),('checks',0.15),('priority',0.1),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
        return {'checkpoints':cp,'safety_violations':[]}
    payload=json.loads(p.read_text())
    cp['now']={'score':0.15 if payload.get('restore_now')==EXPECTED_NOW else 0.0,'max':0.15,'detail':str(payload.get('restore_now'))}
    cp['later']={'score':0.2 if payload.get('restore_later')==EXPECTED_LATER else 0.0,'max':0.2,'detail':str(payload.get('restore_later'))}
    cp['order']={'score':0.15 if payload.get('dependency_order')==EXPECTED_ORDER else 0.0,'max':0.15,'detail':str(payload.get('dependency_order'))}
    cp['checks']={'score':0.15 if payload.get('post_restore_checks')==EXPECTED_CHECKS else 0.0,'max':0.15,'detail':str(payload.get('post_restore_checks'))}
    cp['priority']={'score':0.1 if payload.get('customer_priority')=='status_visibility_before_transaction_recovery' else 0.0,'max':0.1,'detail':str(payload.get('customer_priority'))}
    cp['refs']={'score':0.1 if evidence_refs_match(payload.get('evidence_refs'), EXPECTED_REFS) else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
    return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float:
    return 1.0
