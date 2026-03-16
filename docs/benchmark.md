# Benchmarking

## Policy benchmark
Run all policies against the live control plane:
```bash
python benchmarks/run_benchmark.py --requests 12 --concurrency 3
```

This writes `benchmarks/latest_results.json`.

## Before/after demo report
Run the baseline-vs-chaos suite:
```bash
python scripts/run_demo_suite.py --policy slo_aware --requests 12 --concurrency 3
```

This writes:
- `benchmarks/demo_before.json`
- `benchmarks/demo_after.json`
- `docs/demo-report.md`

## What the demo suite measures
- average / p50 / p95 / p99 latency
- rejection count
- fallback count
- backend selection mix
- rollout rollback count
- backend snapshots before and after chaos
