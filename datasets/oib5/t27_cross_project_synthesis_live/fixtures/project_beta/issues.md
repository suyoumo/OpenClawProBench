# Post-Incident Review - Data Inconsistency Event

**Date**: 2025-08-15
**Severity**: P1
**Duration**: 2 hours

## Issue Summary
During a network partition between shards, the system accepted writes that were later inconsistent when the partition healed.

## Root Cause
- MongoDB's eventual consistency model during network partitions
- Write concern set to "acknowledged" instead of "majority"
- No application-level consistency checks

## Impact
- 3,420 inconsistent records identified
- Required manual reconciliation
- Customer trust impacted

## Lessons Learned
1. Always use write concern "majority" for critical data
2. Implement application-level consistency validation
3. For financial systems, consider ACID-compliant databases
4. Monitor replica set health continuously

## Recommendation
For any system requiring strong consistency (especially financial), MongoDB introduces operational complexity that may outweigh its benefits.
