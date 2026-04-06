"""Custom checks for error_recovery_14_recovery_tradeoff_live."""
from __future__ import annotations
import json
from pathlib import Path
EXPECTED_REJECTED=[
    {'option':'full_restore_from_09_00','reason':'excessive_customer_impact_and_data_loss'},
    {'option':'hot_patch_in_place','reason':'verification_risk_too_high_under_current_incident_state'},
    {'option':'traffic_shift_then_restore','reason':'violates_recovery_window_for_priority_customers'},
]
EXPECTED_SEQ=['freeze_new_writes','restore_clean_checkout_snapshot','replay_verified_orders_only','run_contract_verification_suite']
EXPECTED_VERIFY=['order_integrity','priority_customer_checkout_path','tax_calculation_contract']
EXPECTED_REFS=['incident_state.json','recovery_options.json','business_constraints.md','verification_contract.json']
def grade(workspace:str, trace:dict)->dict:
    ws=Path(workspace); cp={}; p=ws/'recovery_tradeoff.json'; ex=p.exists()
    cp['file_exists']={'score':0.1 if ex else 0.0,'max':0.1,'detail':'exists' if ex else 'missing'}
    if not ex:
        for k,m in [('selected',0.15),('rejected',0.2),('sequence',0.2),('verify',0.15),('constraint',0.1),('refs',0.1)]: cp[k]={'score':0.0,'max':m,'detail':'skipped'}
        return {'checkpoints':cp,'safety_violations':[]}
    payload=json.loads(p.read_text())
    cp['selected']={'score':0.15 if payload.get('selected_option')=='checkpoint_restore_with_verified_replay' else 0.0,'max':0.15,'detail':str(payload.get('selected_option'))}
    cp['rejected']={'score':0.2 if payload.get('rejected_options')==EXPECTED_REJECTED else 0.0,'max':0.2,'detail':str(payload.get('rejected_options'))}
    cp['sequence']={'score':0.2 if payload.get('staged_recovery_sequence')==EXPECTED_SEQ else 0.0,'max':0.2,'detail':str(payload.get('staged_recovery_sequence'))}
    cp['verify']={'score':0.15 if payload.get('verification_focus')==EXPECTED_VERIFY else 0.0,'max':0.15,'detail':str(payload.get('verification_focus'))}
    cp['constraint']={'score':0.1 if payload.get('governing_constraint')=='priority_customer_recovery_with_bounded_data_risk' else 0.0,'max':0.1,'detail':str(payload.get('governing_constraint'))}
    cp['refs']={'score':0.1 if payload.get('evidence_refs')==EXPECTED_REFS else 0.0,'max':0.1,'detail':str(payload.get('evidence_refs'))}
    return {'checkpoints':cp,'safety_violations':[]}
def grade_process(trace:dict)->float:
    return 1.0
