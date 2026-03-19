from __future__ import annotations

from pydantic import BaseModel, Field


class InferenceRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4_000)
    priority: str = Field(default="medium", pattern="^(low|medium|high)$")
    latency_budget_ms: int = Field(default=2_500, ge=1, le=60_000)
    policy: str | None = Field(default=None, pattern="^(round_robin|latency_aware|cost_aware|slo_aware)$")
    preferred_backend: str | None = None
    system_prompt: str | None = Field(default=None, max_length=2_000)
    max_tokens: int | None = Field(default=None, ge=1, le=1_024)


class InferenceResponse(BaseModel):
    request_id: str
    backend: str
    model_name: str | None = None
    latency_ms: float
    queued: bool
    fallback_used: bool
    rejected: bool = False
    result: str | None = None
    reason: str | None = None


class RolloutRequest(BaseModel):
    baseline: str
    canary: str
    traffic_percent: int = Field(default=10, ge=1, le=100)


class RolloutStatus(BaseModel):
    baseline: str | None = None
    canary: str | None = None
    traffic_percent: int = 0


class BackendChaosRequest(BaseModel):
    extra_latency_ms: int = Field(default=0, ge=0, le=30_000)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class RuntimeResetRequest(BaseModel):
    clear_history: bool = True
    clear_chaos: bool = True


class BackendSnapshot(BaseModel):
    name: str
    url: str
    provider: str
    model_name: str
    healthy: bool
    inflight: int
    base_concurrency: int
    max_concurrency: int
    max_concurrency_limit: int
    queue_depth: int
    p95_latency_ms: float
    error_rate: float
    cost_weight: float
    warm_latency_ms: float
    cold_start_penalty_ms: float
    warm_state: str
    residency_state: str
    outstanding_requests: int
    estimated_wait_ms: float
    ewma_latency_ms: float
    max_queue_depth: int
    cold_starts: int
    shed_events: int
    autoscale_up_events: int
    autoscale_down_events: int
    evictions: int
    version: str
    chaos_extra_latency_ms: int
    chaos_error_rate: float


class RequestHistoryRecord(BaseModel):
    created_at: str
    request_id: str
    policy: str
    priority: str
    latency_budget_ms: int
    preferred_backend: str | None = None
    chosen_backend: str | None = None
    final_backend: str | None = None
    model_name: str | None = None
    queued: bool
    fallback_used: bool
    rejected: bool
    status: str
    reason: str | None = None
    latency_ms: float
    input_excerpt: str


class DecisionLogEntry(BaseModel):
    created_at: str
    request_id: str
    event_type: str
    backend: str | None = None
    detail: dict


class MetricsSummary(BaseModel):
    requests_total: int
    rejected_total: int
    load_shed_total: int
    fallback_total: int
    cold_start_total: int
    autoscale_up_total: int
    autoscale_down_total: int
    eviction_total: int
    loaded_backends_total: int
    canary_rollbacks_total: int
    rollout: RolloutStatus
    backends: list[BackendSnapshot]
