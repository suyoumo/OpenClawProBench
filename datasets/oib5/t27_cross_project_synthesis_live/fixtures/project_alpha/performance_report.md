# Performance Report - Q4 2025

## Transaction Throughput
- Daily average: 2,450 TPS
- Peak hour (12:00-13:00): 4,800 TPS
- Black Friday peak: 12,500 TPS (brief degradation)

## Latency Distribution
- P50: 12ms
- P90: 28ms
- P95: 38ms
- P99: 45ms

## Concurrency Issues
- At 5000+ concurrent connections, latency increased to 120ms
- After implementing PgBouncer: latency stable at 50ms even at 8000 TPS
- Recommendation: Never exceed 500 direct connections per instance

## Storage Performance
- SSD NVMe: 50K IOPS sustained
- Table size: 2.5TB (orders table)
- Index size: 800GB
- Vacuum time: 4 hours weekly
