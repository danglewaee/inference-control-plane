# Architecture

## Runtime path
Client -> FastAPI control plane -> policy selection -> Ollama model dispatch -> persistence + metrics + rollout evaluation

## Core components
- `control_plane/main.py`: API surface, startup/bootstrap, rollout/admin endpoints
- `control_plane/router.py`: routing, fallback, queue-aware admission, Ollama dispatch, decision logging
- `control_plane/registry.py`: persistent backend state, health, queue depth, chaos knobs
- `control_plane/storage.py`: SQLite persistence for registry, rollout state, history, decision logs
- `loadgen/runner.py`: concurrent load driver for real model calls
- `scripts/seed_demo.py`: pulls and warms Ollama models from config
- `scripts/run_demo_suite.py`: baseline vs chaos benchmark and markdown report generation

## Persistence
State lives in SQLite at `CONTROL_PLANE_DB_PATH` and survives control-plane restarts:
- backend registry + runtime state
- rollout state
- request history
- decision logs

## Demo stack
- `ollama`: model server
- `control-plane`: routing and admin API
- `prometheus`: metrics scrape
- `grafana`: provisioned dashboard
- `demo-suite`: before/after benchmark + chaos report

## Chaos model
Chaos is injected per logical backend with:
- extra latency
- synthetic error rate

That keeps the demo realistic enough to exercise rollout/fallback logic while still using real model responses from Ollama.
