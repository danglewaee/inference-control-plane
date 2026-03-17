from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from control_plane.metrics import MetricsTracker
from control_plane.registry import BackendRegistry
from control_plane.router import Router
from control_plane.schemas import (
    BackendChaosRequest,
    BackendSnapshot,
    DecisionLogEntry,
    InferenceRequest,
    InferenceResponse,
    MetricsSummary,
    RequestHistoryRecord,
    RolloutRequest,
    RolloutStatus,
    RuntimeResetRequest,
)
from control_plane.storage import PersistenceStore

app = FastAPI(title="Inference Control Plane", version="1.0.0")
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
registry = BackendRegistry()
metrics = MetricsTracker()
storage: PersistenceStore | None = None
router: Router | None = None
ROLLOUT_MIN_SAMPLES = max(1, int(os.getenv("ROLLOUT_MIN_SAMPLES", "5")))
rollout_state = {"baseline": None, "canary": None, "traffic_percent": 0}

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.on_event("startup")
async def startup() -> None:
    global registry, metrics, router, storage, rollout_state
    db_path = os.getenv("CONTROL_PLANE_DB_PATH", str(Path("data") / "control_plane.db"))
    storage = PersistenceStore(db_path)
    storage.initialize()

    registry = BackendRegistry(storage=storage)
    persisted_backends = storage.load_backends()
    if persisted_backends:
        registry.load_records(persisted_backends)
    else:
        for record in _load_backend_records():
            registry.register_backend(**record)

    rollout_state = storage.load_rollout_state() or _default_rollout_state()
    if rollout_state.get("baseline") and rollout_state.get("canary"):
        registry.mark_rollout(rollout_state["baseline"], rollout_state["canary"])
    else:
        storage.save_rollout_state(_default_rollout_state())

    client = httpx.AsyncClient(
        timeout=90.0,
        limits=httpx.Limits(max_keepalive_connections=32, max_connections=64),
    )
    metrics = MetricsTracker()
    router = Router(
        registry=registry,
        metrics=metrics,
        client=client,
        storage=storage,
        default_policy=os.getenv("DEFAULT_POLICY", "slo_aware"),
    )
    app.state.backend_client = client


@app.on_event("shutdown")
async def shutdown() -> None:
    client = getattr(app.state, "backend_client", None)
    if client is not None:
        await client.aclose()
    if storage is not None:
        storage.close()


@app.get("/", include_in_schema=False)
def home():
    if not FRONTEND_DIR.exists():
        raise HTTPException(status_code=404, detail="frontend not available")
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "control-plane",
        "backends": len(registry.names()),
        "storage_path": None if storage is None else storage.path,
    }


@app.get("/backends", response_model=list[BackendSnapshot])
def backends():
    return [_to_snapshot(item) for item in registry.snapshots()]


@app.get("/history", response_model=list[RequestHistoryRecord])
def history(limit: int = Query(default=25, ge=1, le=200)):
    if storage is None:
        return []
    return storage.list_request_history(limit=limit)


@app.get("/decision-logs", response_model=list[DecisionLogEntry])
def decision_logs(limit: int = Query(default=50, ge=1, le=500)):
    if storage is None:
        return []
    return storage.list_decision_logs(limit=limit)


@app.get("/rollouts", response_model=RolloutStatus)
def rollout_status():
    return RolloutStatus(**rollout_state)


@app.post("/infer", response_model=InferenceResponse)
async def infer(request: InferenceRequest):
    if router is None:
        raise HTTPException(status_code=503, detail="router not initialized")
    request = _maybe_route_to_canary(request)
    if request.preferred_backend and not registry.exists(request.preferred_backend):
        raise HTTPException(status_code=404, detail="unknown backend")
    response = await router.handle(request)
    _evaluate_rollout()
    return response


@app.post("/rollouts", response_model=RolloutStatus)
def start_rollout(request: RolloutRequest):
    if request.baseline == request.canary:
        raise HTTPException(status_code=400, detail="baseline and canary must differ")
    if request.baseline not in registry.names() or request.canary not in registry.names():
        raise HTTPException(status_code=404, detail="unknown backend")
    rollout_state.update({
        "baseline": request.baseline,
        "canary": request.canary,
        "traffic_percent": request.traffic_percent,
    })
    registry.mark_rollout(request.baseline, request.canary)
    _save_rollout_state()
    return RolloutStatus(**rollout_state)


@app.post("/admin/backends/{backend_name}/chaos", response_model=BackendSnapshot)
def update_backend_chaos(backend_name: str, request: BackendChaosRequest):
    if not registry.exists(backend_name):
        raise HTTPException(status_code=404, detail="unknown backend")
    state = registry.update_chaos(
        backend_name,
        extra_latency_ms=request.extra_latency_ms,
        error_rate=request.error_rate,
    )
    if storage is not None:
        storage.append_decision_log(
            request_id="system",
            event_type="chaos_updated",
            backend=backend_name,
            detail={
                "extra_latency_ms": request.extra_latency_ms,
                "error_rate": request.error_rate,
            },
        )
    return _to_snapshot(state)


@app.post("/admin/reset-runtime")
def reset_runtime(request: RuntimeResetRequest):
    global rollout_state
    registry.reset_runtime(clear_chaos=request.clear_chaos)
    metrics.reset()
    rollout_state = _default_rollout_state()
    registry.clear_rollout()
    _save_rollout_state()
    if storage is not None and request.clear_history:
        storage.clear_events()
    return {
        "status": "reset",
        "clear_history": request.clear_history,
        "clear_chaos": request.clear_chaos,
        "rollout": rollout_state,
        "backends": [_to_snapshot(item) for item in registry.snapshots()],
    }


@app.get("/metrics")
def prometheus_metrics():
    payload, media_type = metrics.prometheus_payload()
    return Response(content=payload, media_type=media_type)


@app.get("/metrics/summary", response_model=MetricsSummary)
def metrics_summary():
    return MetricsSummary(
        requests_total=metrics.requests_total,
        rejected_total=metrics.rejected_total,
        fallback_total=metrics.fallback_total,
        canary_rollbacks_total=metrics.canary_rollbacks_total,
        rollout=RolloutStatus(**rollout_state),
        backends=[_to_snapshot(item) for item in registry.snapshots()],
    )


def _default_rollout_state() -> dict[str, Any]:
    return {"baseline": None, "canary": None, "traffic_percent": 0}


def _load_backend_records() -> list[dict[str, Any]]:
    config_path = Path(os.getenv("BACKENDS_CONFIG_PATH", "config/backends.demo.json"))
    if config_path.exists():
        return json.loads(config_path.read_text())
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    return [
        {
            "name": "qwen-edge",
            "url": base_url,
            "provider": "ollama",
            "model_name": "qwen2.5:0.5b",
            "cost_weight": 0.8,
            "max_concurrency": 4,
            "warm_latency_ms": 450.0,
        },
        {
            "name": "llama-balanced",
            "url": base_url,
            "provider": "ollama",
            "model_name": "llama3.2:1b",
            "cost_weight": 1.1,
            "max_concurrency": 3,
            "warm_latency_ms": 700.0,
        },
        {
            "name": "qwen-quality",
            "url": base_url,
            "provider": "ollama",
            "model_name": "qwen2.5:1.5b",
            "cost_weight": 1.7,
            "max_concurrency": 2,
            "warm_latency_ms": 1100.0,
        },
    ]


def _to_snapshot(item) -> BackendSnapshot:
    return BackendSnapshot(
        name=item.name,
        url=item.url,
        provider=item.provider,
        model_name=item.model_name,
        healthy=item.healthy,
        inflight=item.inflight,
        max_concurrency=item.max_concurrency,
        queue_depth=item.queue_depth,
        p95_latency_ms=round(item.p95_latency_ms, 2),
        error_rate=round(item.error_rate, 3),
        cost_weight=item.cost_weight,
        warm_latency_ms=round(item.warm_latency_ms, 2),
        version=item.version,
        chaos_extra_latency_ms=item.chaos_extra_latency_ms,
        chaos_error_rate=round(item.chaos_error_rate, 3),
    )


def _maybe_route_to_canary(request: InferenceRequest) -> InferenceRequest:
    canary = rollout_state.get("canary")
    if not canary or rollout_state["traffic_percent"] <= 0:
        return request
    if _rollout_targets_canary(rollout_state["traffic_percent"]):
        return request.model_copy(update={"preferred_backend": canary})
    baseline = rollout_state.get("baseline")
    return request.model_copy(update={"preferred_backend": baseline}) if baseline else request


def _rollout_targets_canary(traffic_percent: int) -> bool:
    return random.random() < (traffic_percent / 100.0)


def _evaluate_rollout() -> None:
    canary_name = rollout_state.get("canary")
    baseline_name = rollout_state.get("baseline")
    if not canary_name or not baseline_name:
        return
    canary = registry.get(canary_name)
    baseline = registry.get(baseline_name)
    canary_samples = canary.successes + canary.failures
    baseline_samples = baseline.successes + baseline.failures
    if canary_samples < ROLLOUT_MIN_SAMPLES or baseline_samples < ROLLOUT_MIN_SAMPLES:
        return

    error_regression = canary.error_rate > baseline.error_rate + 0.03
    latency_regression = False
    if canary.latencies_ms and baseline.latencies_ms:
        latency_regression = canary.p95_latency_ms > (baseline.p95_latency_ms * 1.3)

    if error_regression or latency_regression:
        registry.rollback_canary(canary_name)
        rollout_state.update(_default_rollout_state())
        _save_rollout_state()
        metrics.record_rollback()
        if storage is not None:
            storage.append_decision_log(
                request_id="system",
                event_type="canary_rollback",
                backend=canary_name,
                detail={
                    "baseline": baseline_name,
                    "canary_error_rate": canary.error_rate,
                    "baseline_error_rate": baseline.error_rate,
                    "canary_p95_latency_ms": canary.p95_latency_ms,
                    "baseline_p95_latency_ms": baseline.p95_latency_ms,
                },
            )


def _save_rollout_state() -> None:
    if storage is not None:
        storage.save_rollout_state(dict(rollout_state))
