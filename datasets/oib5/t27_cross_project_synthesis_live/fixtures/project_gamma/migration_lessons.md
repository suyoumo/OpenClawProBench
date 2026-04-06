# High-Concurrency Lessons Learned

## Context
Project Gamma handles 200K concurrent sessions with strong consistency requirements.

## Key Decisions That Worked

### 1. Read Replicas
- Implemented 3 read replicas
- Reduced master load by 70%
- Read latency: 5ms (replicas) vs 15ms (master)

### 2. Connection Pooling
- ProxySQL with 2000 backend connections
- Frontend: 10,000 application connections
- Latency improvement: 40%

### 3. Partitioning Strategy
- Sessions table partitioned by date
- 50x faster queries for recent sessions
- Easier maintenance (drop old partitions)

## What Didn't Work

### 1. Direct Connection from Application
- Attempted without pooling initially
- Connection storms at peak hours
- Database became unresponsive

### 2. Heavy Write Operations During Peak
- Batch updates during peak caused lock contention
- Solution: Defer non-critical writes to off-peak hours

## Financial System Suitability
**Highly suitable** for financial systems because:
- Strong ACID guarantees
- Predictable performance under load
- Well-tested replication and failover
- Extensive tooling for monitoring and backup

## Concurrency Limitations
- Observed contention at >6000 concurrent writes
- Row-level locking becomes bottleneck
- Recommendation: Use sharding for >10K TPS write-heavy workloads
