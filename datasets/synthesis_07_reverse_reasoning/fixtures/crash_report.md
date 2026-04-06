# Crash Report

## Incident Summary
- Time: 2026-03-22 09:17:44 CST
- Service: order-processing
- Deployment: v3.8.2
- Exit Type: oom_kill_by_cgroup
- Last surfaced application error: `DBAcquireTimeout after 8000ms`

## User Impact
- Checkout submit requests failed for 11 minutes
- Peak waiting orders in memory: 3,900+
- Three pods entered CrashLoopBackOff within 90 seconds

## Crash Snapshot
- Heap usage reached 96% before container termination
- 74 request threads were blocked in `FraudDecisionClient.evaluate()`
- Thread dump note: blocked request threads still owned open DB sessions
- Kubernetes node health stayed normal during the event
- No Redis eviction burst was observed during the crash window

## Immediate Clues
1. The last fatal symptom is OOM, not a direct database crash
2. Requests were waiting on fraud decisions while DB acquire timeouts were already happening
3. The crash happened minutes after an early-morning config hot-reload
