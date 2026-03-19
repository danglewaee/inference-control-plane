from __future__ import annotations

from collections import Counter

from prometheus_client import CONTENT_TYPE_LATEST, Counter as PromCounter, Gauge, Histogram, generate_latest

REQUESTS = PromCounter("icp_requests_total", "Inference requests", ["policy", "priority", "backend", "status"])
LATENCY = Histogram("icp_request_latency_ms", "Inference latency ms", ["policy", "backend"], buckets=(25, 50, 100, 250, 500, 1000, 2000, 4000, 8000, 16000))
REJECTIONS = PromCounter("icp_rejections_total", "Rejected requests", ["reason", "priority"])
LOAD_SHED = PromCounter("icp_load_shed_total", "Requests shed under overload", ["backend", "priority", "reason"])
FALLBACKS = PromCounter("icp_fallback_total", "Fallback requests", ["from_backend", "to_backend"])
BACKEND_COLD_STARTS = PromCounter("icp_backend_cold_starts_total", "Cold starts by backend", ["backend"])
ROLLBACKS = PromCounter("icp_rollbacks_total", "Canary rollbacks")
BACKEND_INFLIGHT = Gauge("icp_backend_inflight", "Inflight by backend", ["backend"])
BACKEND_QUEUE = Gauge("icp_backend_queue_depth", "Queue depth by backend", ["backend"])
BACKEND_OUTSTANDING = Gauge("icp_backend_outstanding_requests", "Outstanding work by backend", ["backend"])
BACKEND_ESTIMATED_WAIT = Gauge("icp_backend_estimated_wait_ms", "Estimated wait by backend", ["backend"])
BACKEND_WARM = Gauge("icp_backend_warm", "Backend warm state by backend", ["backend"])
BACKEND_LOADED = Gauge("icp_backend_loaded", "Backend loaded state by backend", ["backend"])
BACKEND_HOT = Gauge("icp_backend_hot", "Backend hot residency by backend", ["backend"])
BACKEND_CAPACITY = Gauge("icp_backend_capacity", "Current backend concurrency capacity", ["backend"])
BACKEND_CAPACITY_LIMIT = Gauge("icp_backend_capacity_limit", "Backend max concurrency limit", ["backend"])
BACKEND_HEALTH = Gauge("icp_backend_healthy", "Backend health by backend", ["backend"])


class MetricsTracker:
    def __init__(self) -> None:
        self.requests_total = 0
        self.rejected_total = 0
        self.load_shed_total = 0
        self.fallback_total = 0
        self.cold_start_total = 0
        self.canary_rollbacks_total = 0
        self._status_counts = Counter()

    def record_request(self, *, policy: str, priority: str, backend: str, status: str, latency_ms: float | None = None) -> None:
        self.requests_total += 1
        self._status_counts[status] += 1
        REQUESTS.labels(policy=policy, priority=priority, backend=backend, status=status).inc()
        if latency_ms is not None:
            LATENCY.labels(policy=policy, backend=backend).observe(latency_ms)

    def record_rejection(self, *, reason: str, priority: str) -> None:
        self.rejected_total += 1
        REJECTIONS.labels(reason=reason, priority=priority).inc()

    def record_load_shed(self, *, backend: str, priority: str, reason: str) -> None:
        self.load_shed_total += 1
        LOAD_SHED.labels(backend=backend, priority=priority, reason=reason).inc()

    def record_fallback(self, *, from_backend: str, to_backend: str) -> None:
        self.fallback_total += 1
        FALLBACKS.labels(from_backend=from_backend, to_backend=to_backend).inc()

    def record_cold_start(self, *, backend: str) -> None:
        self.cold_start_total += 1
        BACKEND_COLD_STARTS.labels(backend=backend).inc()

    def record_rollback(self) -> None:
        self.canary_rollbacks_total += 1
        ROLLBACKS.inc()

    def set_backend_state(
        self,
        *,
        backend: str,
        inflight: int,
        queue_depth: int,
        healthy: bool,
        outstanding_requests: int,
        estimated_wait_ms: float,
        warm_state: str,
        residency_state: str,
        current_concurrency: int,
        max_concurrency_limit: int,
    ) -> None:
        BACKEND_INFLIGHT.labels(backend=backend).set(inflight)
        BACKEND_QUEUE.labels(backend=backend).set(queue_depth)
        BACKEND_OUTSTANDING.labels(backend=backend).set(outstanding_requests)
        BACKEND_ESTIMATED_WAIT.labels(backend=backend).set(estimated_wait_ms)
        BACKEND_WARM.labels(backend=backend).set(1 if warm_state == "warm" else 0)
        BACKEND_LOADED.labels(backend=backend).set(0 if residency_state == "unloaded" else 1)
        BACKEND_HOT.labels(backend=backend).set(1 if residency_state == "hot" else 0)
        BACKEND_CAPACITY.labels(backend=backend).set(current_concurrency)
        BACKEND_CAPACITY_LIMIT.labels(backend=backend).set(max_concurrency_limit)
        BACKEND_HEALTH.labels(backend=backend).set(1 if healthy else 0)

    def reset(self) -> None:
        self.requests_total = 0
        self.rejected_total = 0
        self.load_shed_total = 0
        self.fallback_total = 0
        self.cold_start_total = 0
        self.canary_rollbacks_total = 0
        self._status_counts.clear()

    @staticmethod
    def prometheus_payload() -> tuple[bytes, str]:
        return generate_latest(), CONTENT_TYPE_LATEST
