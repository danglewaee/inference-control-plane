# Inference Control Plane

A persistence-backed inference control plane that routes requests across real Ollama models under latency, cost, and health constraints.

## What this demo includes
- Real model-server integration via `Ollama` instead of mock backends
- Persistent backend registry, rollout state, request history, and decision logs in SQLite
- Routing policies: `round_robin`, `latency_aware`, `cost_aware`, `slo_aware`
- Queue-aware admission control, fallback routing, canary rollout, rollback guardrails
- Prometheus metrics + provisioned Grafana dashboard
- Chaos demo and before/after benchmark report generator
- `docker compose up --build -d` core stack startup
- `docker compose --profile demo up --build` full benchmark demo

## Core stack
```bash
docker compose up --build -d
```

What happens on first boot:
- `ollama` starts
- `model-seed` pulls and warms the demo models from `config/backends.demo.json`
- `control-plane`, `prometheus`, and `grafana` start

The first boot can take a while because Ollama needs to download models.

## Full demo run
```bash
docker compose --profile demo up --build
```

The `demo-suite` profile runs a baseline benchmark, injects chaos, runs an after benchmark, and writes `docs/demo-report.md`.

## URLs
- Web app: [http://localhost:8000](http://localhost:8000)
- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Prometheus: [http://localhost:9090](http://localhost:9090)
- Grafana: [http://localhost:3000](http://localhost:3000) (`admin` / `admin`)

## Useful endpoints
- `GET /backends`
- `GET /history`
- `GET /decision-logs`
- `GET /metrics`
- `GET /metrics/summary`
- `POST /rollouts`
- `POST /admin/backends/{name}/chaos`
- `POST /admin/reset-runtime`

## Manual scripts
```bash
python scripts/seed_demo.py --ollama-url http://127.0.0.1:11434 --config config/backends.demo.json --warmup
python benchmarks/run_benchmark.py --requests 12 --concurrency 3
python scripts/run_demo_suite.py --policy slo_aware --requests 12 --concurrency 3
```

## Local test loop
```bash
python -m unittest discover -s tests -v
python -m compileall control_plane benchmarks loadgen scripts tests
docker compose config
```

## Demo architecture
See `docs/architecture.md`, `docs/benchmark.md`, and the generated `docs/demo-report.md`.
