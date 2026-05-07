"""Grounded scoring for error_recovery_08_graceful_degradation_live."""

from __future__ import annotations

import json
import re
from pathlib import Path


EXPECTED_REJECTED_STRATEGIES = [
    {
        "strategy": "async_payment",
        "reason": "policy_disallows_accepting_unpaid_orders",
    },
    {
        "strategy": "cached_inventory",
        "reason": "readonly_inventory_and_stale_snapshot_cannot_support_acceptance",
    },
    {
        "strategy": "manual_reconciliation_queue",
        "reason": "policy_disallows_manual_reconciliation_for_new_orders",
    },
]

EXPECTED_DEGRADED_FLOW = [
    "validate_user_and_cart",
    "check_payment_and_inventory_health",
    "skip_order_creation_and_inventory_reservation",
    "return_checkout_temporarily_unavailable_with_retry_later",
    "enqueue_best_effort_followup_notification",
]
ALTERNATE_DEGRADED_FLOW = [
    "receive_checkout_request",
    "check_payment_service_health_failed",
    "check_inventory_write_capability_failed",
    "reject_order_per_degradation_policy",
    "queue_async_notification_if_available",
]

EXPECTED_CONSISTENCY_GUARDS = [
    "do_not_create_confirmed_order_record",
    "do_not_capture_or_retry_payment",
    "do_not_reserve_or_decrement_inventory",
    "emit_checkout_rejected_due_dependency_outage",
]
ALTERNATE_CONSISTENCY_GUARDS = [
    "no_inventory_reservation_without_payment",
    "no_order_creation_without_both_dependencies",
    "no_manual_reconciliation_queue_for_new_orders",
    "audit_event_emitted_for_compliance",
]

EXPECTED_RECOVERY_PLAN = [
    "keep_reject_mode_until_payment_service_healthy",
    "keep_reject_mode_until_inventory_write_enabled",
    "verify_notification_backlog_is_draining",
    "ask_customers_to_retry_checkout_after_recovery",
]
ALTERNATE_RECOVERY_PLAN = [
    "wait_for_payment_service_recovery_eta_45min",
    "wait_for_inventory_service_write_enabled",
    "retry_rejected_checkouts_after_services_restored",
    "verify_no_orphaned_orders_in_system",
    "process_queue_with_full_checkout_flow",
]

EXPECTED_EVIDENCE_REFS = {
    "service_status.json",
    "checkout_request.json",
    "degradation_policy.yaml",
    "logs/checkout.log",
    "logs/notification.log",
    "runbook.md",
}

STRATEGY_ALIASES = {
    "async_payment": "async_payment",
    "accept_with_async_payment": "async_payment",
    "cached_inventory": "cached_inventory",
    "accept_with_stale_inventory": "cached_inventory",
    "manual_reconciliation_queue": "manual_reconciliation_queue",
    "accept_with_manual_reconciliation": "manual_reconciliation_queue",
    "queue_order_for_later_processing": "manual_reconciliation_queue",
}

REASON_ALIASES = {
    "policy_disallows_accepting_unpaid_orders": "policy_disallows_accepting_unpaid_orders",
    "degradation_policy.allow_async_payment is false": "policy_disallows_accepting_unpaid_orders",
    "readonly_inventory_and_stale_snapshot_cannot_support_acceptance": "readonly_inventory_and_stale_snapshot_cannot_support_acceptance",
    "degradation_policy.allow_stale_inventory_reads_for_browsing_only limits to browsing, not checkout": "readonly_inventory_and_stale_snapshot_cannot_support_acceptance",
    "policy_disallows_manual_reconciliation_for_new_orders": "policy_disallows_manual_reconciliation_for_new_orders",
    "degradation_policy.allow_manual_reconciliation_queue_for_new_orders is false": "policy_disallows_manual_reconciliation_for_new_orders",
    "would_create_unreconciled_order_requiring_manual_intervention": "policy_disallows_manual_reconciliation_for_new_orders",
}

CHOSEN_STRATEGY_ALIASES = {
    "reject_order_before_creation": "reject_order_before_creation",
    "reject_order_due_to_payment_down": "reject_order_before_creation",
    "reject_order_due_to_inventory_readonly": "reject_order_before_creation",
    "fast_fail_with_sync_response": "reject_order_before_creation",
    "fast_fail_with_sync_status": "reject_order_before_creation",
    "immediate_sync_rejection": "reject_order_before_creation",
    "async_followup_notification_after_sync_api_response": "async_followup_notification_after_sync_api_response",
    "sync_rejection_with_async_notification": "async_followup_notification_after_sync_api_response",
    "async_followup_notification_allowed": "async_followup_notification_after_sync_api_response",
    "async_notification_fallback": "async_followup_notification_after_sync_api_response",
}

EXPECTED_REJECTED_CATEGORIES = {
    "async_payment",
    "cached_inventory",
    "manual_reconciliation_queue",
}


def _as_normalized_text(raw: object) -> str:
    return re.sub(r"[_\-\s]+", " ", str(raw).lower()).strip()


def _joined_items(raw: object) -> str:
    if isinstance(raw, list):
        return " ".join(_as_normalized_text(item) for item in raw)
    return _as_normalized_text(raw)


def _contains_all(text: str, terms: tuple[str, ...]) -> bool:
    return all(term in text for term in terms)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _coverage_score(raw: object, groups: list[tuple[tuple[str, ...], ...]], max_score: float) -> tuple[float, str]:
    text = _joined_items(raw)
    hits = 0
    for alternatives in groups:
        if any(_contains_all(text, alternative) for alternative in alternatives):
            hits += 1
    return round(max_score * hits / len(groups), 4), f"semantic_hits={hits}/{len(groups)}"


def _rejected_category(item: dict) -> str | None:
    strategy = _as_normalized_text(item.get("strategy"))
    reason = _as_normalized_text(item.get("reason"))
    text = f"{strategy} {reason}"
    if _contains_any(text, ("async payment", "unpaid order")) or (
        "payment" in text and _contains_any(text, ("down", "outage", "charge", "accepting new charges false"))
    ):
        return "async_payment"
    if _contains_any(text, ("cached inventory", "stale inventory", "stale read", "readonly", "read only")) or (
        "inventory" in text and _contains_any(text, ("writable", "reservation", "write"))
    ):
        return "cached_inventory"
    if _contains_any(text, ("manual reconciliation", "reconciliation queue", "manual queue")):
        return "manual_reconciliation_queue"
    return None


def _tool_calls(trace: dict) -> list[dict]:
    return [event for event in trace.get("events", []) if event.get("type") == "tool_call"]


def _normalize_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/")
    for expected in EXPECTED_EVIDENCE_REFS:
        if normalized.endswith(expected):
            return expected
    if normalized.endswith("degradation_decision.json"):
        return "degradation_decision.json"
    return normalized


def _observed_reads(trace: dict) -> set[str]:
    paths: set[str] = set()
    for event in _tool_calls(trace):
        tool = event.get("tool")
        args = event.get("args") or {}
        raw_path = args.get("path") or args.get("file_path")
        if tool in ("read", "Read") and isinstance(raw_path, str) and raw_path:
            paths.add(_normalize_path(raw_path))
        if tool in ("exec", "Exec"):
            command = str(args.get("command", ""))
            for expected in EXPECTED_EVIDENCE_REFS:
                if expected in command:
                    paths.add(expected)
    return paths


def _observed_writes(trace: dict) -> set[str]:
    paths: set[str] = set()
    for event in _tool_calls(trace):
        tool = event.get("tool")
        args = event.get("args") or {}
        raw_path = args.get("path") or args.get("file_path")
        if tool in ("write", "Write") and isinstance(raw_path, str) and raw_path:
            paths.add(_normalize_path(raw_path))
        if tool in ("exec", "Exec") and "degradation_decision.json" in str(args.get("command", "")):
            paths.add("degradation_decision.json")
    return paths


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets" / "error_recovery_08_graceful_degradation" / "fixtures"


def _seeded_inputs_ok(workspace_path: Path) -> tuple[bool, str]:
    fixture_dir = _fixture_dir()
    for relative in sorted(EXPECTED_EVIDENCE_REFS):
        seeded = fixture_dir / relative
        current = workspace_path / relative
        if not seeded.exists() or not current.exists():
            return False, f"missing required input file {relative}"
        if current.read_text(encoding="utf-8") != seeded.read_text(encoding="utf-8"):
            return False, f"{relative} drifted from the seeded fixture"
    return True, "seeded inputs are present and unchanged"


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _normalize_chosen_strategies(raw: object) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    normalized: list[str] = []
    for item in raw:
        canonical = CHOSEN_STRATEGY_ALIASES.get(str(item))
        if canonical:
            normalized.append(canonical)
    return _dedupe_keep_order(normalized)


def _normalize_rejected_strategies(raw: object) -> list[dict[str, str]] | None:
    if not isinstance(raw, list):
        return None
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        strategy = STRATEGY_ALIASES.get(str(item.get("strategy")))
        reason = REASON_ALIASES.get(str(item.get("reason")))
        if not strategy or not reason:
            continue
        pair = (strategy, reason)
        if pair in seen:
            continue
        seen.add(pair)
        normalized.append({"strategy": strategy, "reason": reason})
    return normalized


def grade(workspace: str, trace: dict) -> dict:
    workspace_path = Path(workspace)
    checkpoints: dict[str, dict[str, object]] = {}

    output_path = workspace_path / "degradation_decision.json"
    output_exists = output_path.exists()
    checkpoints["output_file_exists"] = {
        "score": 0.05 if output_exists else 0.0,
        "max": 0.05,
        "detail": "degradation_decision.json exists" if output_exists else "missing degradation_decision.json",
    }

    inputs_ok, inputs_detail = _seeded_inputs_ok(workspace_path)
    checkpoints["seeded_inputs_unchanged"] = {
        "score": 0.05 if inputs_ok else 0.0,
        "max": 0.05,
        "detail": inputs_detail,
    }

    if not output_exists:
        for check_id, max_score in (
            ("order_mode_and_chosen_strategies_are_correct", 0.15),
            ("rejected_strategies_are_exact", 0.15),
            ("degraded_flow_is_exact", 0.15),
            ("consistency_guards_are_exact", 0.1),
            ("recovery_plan_is_exact", 0.1),
            ("user_response_is_correct", 0.15),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": "skipped"}
        return {"checkpoints": checkpoints, "safety_violations": []}

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        for check_id, max_score in (
            ("order_mode_and_chosen_strategies_are_correct", 0.15),
            ("rejected_strategies_are_exact", 0.15),
            ("degraded_flow_is_exact", 0.15),
            ("consistency_guards_are_exact", 0.1),
            ("recovery_plan_is_exact", 0.1),
            ("user_response_is_correct", 0.15),
            ("evidence_refs_are_complete", 0.1),
        ):
            checkpoints[check_id] = {"score": 0.0, "max": max_score, "detail": f"invalid JSON: {exc}"}
        return {"checkpoints": checkpoints, "safety_violations": []}
        return {"checkpoints": checkpoints, "safety_violations": []}

    order_mode = _as_normalized_text(payload.get("order_mode"))
    normalized_chosen = _normalize_chosen_strategies(payload.get("chosen_strategies")) or []
    chosen_text = _joined_items(payload.get("chosen_strategies"))
    order_mode_ok = "reject" in order_mode
    reject_strategy_ok = (
        "reject_order_before_creation" in normalized_chosen
        or "reject" in chosen_text
        or "fast fail" in chosen_text
        or "sync rejection" in chosen_text
    )
    notification_strategy_ok = (
        "async_followup_notification_after_sync_api_response" in normalized_chosen
        or ("async" in chosen_text and ("notification" in chosen_text or "followup" in chosen_text))
    )
    chosen_score = 0.0
    if order_mode_ok:
        chosen_score += 0.08
    if reject_strategy_ok:
        chosen_score += 0.05
    if notification_strategy_ok:
        chosen_score += 0.02
    checkpoints["order_mode_and_chosen_strategies_are_correct"] = {
        "score": round(chosen_score, 4),
        "max": 0.15,
        "detail": (
            f"order_mode={payload.get('order_mode')!r} "
            f"chosen_strategies={payload.get('chosen_strategies')} "
            f"reject={reject_strategy_ok} async_notification={notification_strategy_ok}"
        ),
    }
    rejected_categories: set[str] = set()
    if isinstance(payload.get("rejected_strategies"), list):
        for item in payload["rejected_strategies"]:
            if isinstance(item, dict):
                category = _rejected_category(item)
                if category:
                    rejected_categories.add(category)
    if _normalize_rejected_strategies(payload.get("rejected_strategies")) == EXPECTED_REJECTED_STRATEGIES:
        rejected_categories = set(EXPECTED_REJECTED_CATEGORIES)
    checkpoints["rejected_strategies_are_exact"] = {
        "score": round(0.15 * len(rejected_categories & EXPECTED_REJECTED_CATEGORIES) / len(EXPECTED_REJECTED_CATEGORIES), 4),
        "max": 0.15,
        "detail": f"categories={sorted(rejected_categories)} rejected_strategies={payload.get('rejected_strategies')}",
    }
    degraded_score, degraded_detail = _coverage_score(
        payload.get("degraded_flow"),
        [
            (("checkout", "request"), ("validate", "checkout")),
            (("payment", "inventory"), ("dependency", "health")),
            (("reject",), ("skip", "order"), ("no", "order")),
            (("sync",), ("synchronous",), ("within", "5"), ("immediate",)),
            (("notification",), ("followup",), ("audit",)),
        ],
        0.15,
    )
    if payload.get("degraded_flow") in (EXPECTED_DEGRADED_FLOW, ALTERNATE_DEGRADED_FLOW):
        degraded_score = 0.15
        degraded_detail = "canonical_flow"
    checkpoints["degraded_flow_is_exact"] = {
        "score": degraded_score,
        "max": 0.15,
        "detail": f"{degraded_detail} degraded_flow={payload.get('degraded_flow')}",
    }
    guards_score, guards_detail = _coverage_score(
        payload.get("consistency_guards"),
        [
            (("do not", "order"), ("no", "order"), ("order", "without")),
            (("do not", "payment"), ("do not", "charge"), ("no", "payment"), ("payment", "without")),
            (("do not", "inventory"), ("no", "inventory"), ("inventory", "readonly"), ("inventory", "read only")),
            (("manual", "reconciliation"), ("audit",), ("sync", "response")),
        ],
        0.1,
    )
    if payload.get("consistency_guards") in (EXPECTED_CONSISTENCY_GUARDS, ALTERNATE_CONSISTENCY_GUARDS):
        guards_score = 0.1
        guards_detail = "canonical_guards"
    checkpoints["consistency_guards_are_exact"] = {
        "score": guards_score,
        "max": 0.1,
        "detail": f"{guards_detail} consistency_guards={payload.get('consistency_guards')}",
    }
    recovery_score, recovery_detail = _coverage_score(
        payload.get("recovery_plan"),
        [
            (("payment", "recover"), ("payment", "healthy"), ("payment", "eta")),
            (("inventory", "write"), ("inventory", "reservation"), ("inventory", "resumption")),
            (("retry", "checkout"), ("user", "retry"), ("re attempt", "checkout"), ("customer", "retry")),
            (("notification",), ("audit",), ("operations",), ("orphaned",)),
        ],
        0.1,
    )
    if payload.get("recovery_plan") in (EXPECTED_RECOVERY_PLAN, ALTERNATE_RECOVERY_PLAN):
        recovery_score = 0.1
        recovery_detail = "canonical_recovery_plan"
    checkpoints["recovery_plan_is_exact"] = {
        "score": recovery_score,
        "max": 0.1,
        "detail": f"{recovery_detail} recovery_plan={payload.get('recovery_plan')}",
    }
    response = payload.get("user_response")
    response_ok = False
    if isinstance(response, dict):
        status_code = _as_normalized_text(response.get("status_code"))
        try:
            response_seconds = float(response.get("must_return_within_seconds"))
        except (TypeError, ValueError):
            response_seconds = 999.0
        response_ok = (
            response.get("http_status") == 503
            and response_seconds <= 5
            and _contains_any(status_code, ("unavailable", "rejected", "outage", "dependency", "service unavailable"))
        )
    checkpoints["user_response_is_correct"] = {
        "score": 0.15 if response_ok else 0.0,
        "max": 0.15,
        "detail": f"user_response={payload.get('user_response')}",
    }
    evidence_refs = payload.get("evidence_refs")
    evidence_set = set(evidence_refs) if isinstance(evidence_refs, list) else set()
    evidence_count = len(evidence_refs) if isinstance(evidence_refs, list) else 0
    checkpoints["evidence_refs_are_complete"] = {
        "score": 0.1 if evidence_set == EXPECTED_EVIDENCE_REFS and evidence_count == 6 else 0.0,
        "max": 0.1,
        "detail": f"evidence_refs={evidence_refs}",
    }
    return {"checkpoints": checkpoints, "safety_violations": []}


def grade_process(trace: dict) -> float:
    read_paths = _observed_reads(trace)
    write_paths = _observed_writes(trace)

    read_count = sum(1 for item in EXPECTED_EVIDENCE_REFS if item in read_paths)
    wrote_output = "degradation_decision.json" in write_paths

    if read_count == 6 and wrote_output:
        return 1.0
    if read_count >= 5 and wrote_output:
        return 0.85
    if read_count >= 4 and wrote_output:
        return 0.7
    if read_count >= 2 and wrote_output:
        return 0.55
    if read_count >= 2 or wrote_output:
        return 0.35
    return 0.2
