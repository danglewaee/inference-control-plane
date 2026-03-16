# Demo Benchmark Report

Policy: `slo_aware`
Chaos backend: `qwen-quality`
Injected error rate: `0.35`
Injected latency: `900 ms`

## Before Chaos
- avg: `16007.0 ms`
- p95: `26923.81 ms`
- rejected: `1`
- fallbacks: `1`
- errors: `0`
- backend mix: `{"qwen-edge": 5, "llama-balanced": 4, "qwen-quality": 3}`

## After Chaos + Rollout
- avg: `7058.27 ms`
- p95: `14127.54 ms`
- rejected: `0`
- fallbacks: `0`
- errors: `0`
- backend mix: `{"qwen-edge": 10, "qwen-quality": 2}`

## Backend Summary Before
```json
{
  "requests_total": 12,
  "rejected_total": 1,
  "fallback_total": 1,
  "canary_rollbacks_total": 0,
  "rollout": {
    "baseline": null,
    "canary": null,
    "traffic_percent": 0
  },
  "backends": [
    {
      "name": "llama-balanced",
      "url": "http://ollama:11434",
      "provider": "ollama",
      "model_name": "llama3.2:1b",
      "healthy": true,
      "inflight": 0,
      "max_concurrency": 3,
      "queue_depth": 0,
      "p95_latency_ms": 18030.18,
      "error_rate": 0.0,
      "cost_weight": 1.1,
      "warm_latency_ms": 700.0,
      "version": "stable",
      "chaos_extra_latency_ms": 0,
      "chaos_error_rate": 0.0
    },
    {
      "name": "qwen-edge",
      "url": "http://ollama:11434",
      "provider": "ollama",
      "model_name": "qwen2.5:0.5b",
      "healthy": true,
      "inflight": 0,
      "max_concurrency": 4,
      "queue_depth": 0,
      "p95_latency_ms": 26800.69,
      "error_rate": 0.0,
      "cost_weight": 0.8,
      "warm_latency_ms": 450.0,
      "version": "stable",
      "chaos_extra_latency_ms": 0,
      "chaos_error_rate": 0.0
    },
    {
      "name": "qwen-quality",
      "url": "http://ollama:11434",
      "provider": "ollama",
      "model_name": "qwen2.5:1.5b",
      "healthy": true,
      "inflight": 0,
      "max_concurrency": 2,
      "queue_depth": 0,
      "p95_latency_ms": 32978.13,
      "error_rate": 0.0,
      "cost_weight": 1.7,
      "warm_latency_ms": 1100.0,
      "version": "stable",
      "chaos_extra_latency_ms": 0,
      "chaos_error_rate": 0.0
    }
  ]
}
```

## Backend Summary After
```json
{
  "requests_total": 12,
  "rejected_total": 0,
  "fallback_total": 0,
  "canary_rollbacks_total": 0,
  "rollout": {
    "baseline": "qwen-edge",
    "canary": "qwen-quality",
    "traffic_percent": 20
  },
  "backends": [
    {
      "name": "llama-balanced",
      "url": "http://ollama:11434",
      "provider": "ollama",
      "model_name": "llama3.2:1b",
      "healthy": true,
      "inflight": 0,
      "max_concurrency": 3,
      "queue_depth": 0,
      "p95_latency_ms": 0.0,
      "error_rate": 0.0,
      "cost_weight": 1.1,
      "warm_latency_ms": 700.0,
      "version": "stable",
      "chaos_extra_latency_ms": 0,
      "chaos_error_rate": 0.0
    },
    {
      "name": "qwen-edge",
      "url": "http://ollama:11434",
      "provider": "ollama",
      "model_name": "qwen2.5:0.5b",
      "healthy": true,
      "inflight": 0,
      "max_concurrency": 4,
      "queue_depth": 0,
      "p95_latency_ms": 11399.49,
      "error_rate": 0.0,
      "cost_weight": 0.8,
      "warm_latency_ms": 450.0,
      "version": "baseline",
      "chaos_extra_latency_ms": 0,
      "chaos_error_rate": 0.0
    },
    {
      "name": "qwen-quality",
      "url": "http://ollama:11434",
      "provider": "ollama",
      "model_name": "qwen2.5:1.5b",
      "healthy": true,
      "inflight": 0,
      "max_concurrency": 2,
      "queue_depth": 0,
      "p95_latency_ms": 14632.99,
      "error_rate": 0.0,
      "cost_weight": 1.7,
      "warm_latency_ms": 1100.0,
      "version": "canary",
      "chaos_extra_latency_ms": 900,
      "chaos_error_rate": 0.35
    }
  ]
}
```
