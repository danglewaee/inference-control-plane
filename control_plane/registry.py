from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import ceil
from threading import Lock
from time import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from control_plane.storage import PersistenceStore


@dataclass
class BackendState:
    name: str
    url: str
    provider: str
    model_name: str
    cost_weight: float
    max_concurrency: int
    warm_latency_ms: float
    base_concurrency: int = 0
    max_concurrency_limit: int = 0
    cold_start_penalty_ms: float = 650.0
    warm_ttl_s: float = 90.0
    hot_ttl_s: float = 30.0
    unload_ttl_s: float = 150.0
    max_queue_depth: int = 0
    version: str = "stable"
    system_prompt: str = "You are a concise assistant. Answer in one or two short sentences."
    temperature: float = 0.2
    max_tokens: int = 96
    timeout_s: float = 60.0
    healthy: bool = True
    inflight: int = 0
    queue_depth: int = 0
    chaos_extra_latency_ms: int = 0
    chaos_error_rate: float = 0.0
    latencies_ms: deque[float] = field(default_factory=lambda: deque(maxlen=200))
    successes: int = 0
    failures: int = 0
    ewma_latency_ms: float = 0.0
    last_used_at: float | None = None
    last_loaded_at: float | None = None
    last_scale_at: float | None = None
    residency_state: str = "unloaded"
    cold_starts: int = 0
    shed_events: int = 0
    autoscale_up_events: int = 0
    autoscale_down_events: int = 0
    evictions: int = 0

    @property
    def error_rate(self) -> float:
        total = self.successes + self.failures
        return 0.0 if total == 0 else self.failures / total

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        index = max(0, ceil(len(ordered) * 0.95) - 1)
        return float(ordered[index])

    @property
    def outstanding_requests(self) -> int:
        return self.inflight + self.queue_depth

    @property
    def effective_queue_limit(self) -> int:
        return self.max_queue_depth or max(2, self.max_concurrency * 2)

    @property
    def latency_signal_ms(self) -> float:
        return self.ewma_latency_ms or self.p95_latency_ms or self.warm_latency_ms

    @property
    def estimated_wait_ms(self) -> float:
        concurrency = max(1, self.max_concurrency)
        return round((self.outstanding_requests / concurrency) * self.latency_signal_ms * 0.55, 2)

    def is_cold(self, now_s: float | None = None) -> bool:
        now_s = time() if now_s is None else now_s
        if self.residency_state in {"unloaded", "loading"}:
            return True
        return self.last_used_at is None or (now_s - self.last_used_at) > self.warm_ttl_s

    @property
    def warm_state(self) -> str:
        return "cold" if self.is_cold() else "warm"

    @property
    def loaded(self) -> bool:
        return self.residency_state != "unloaded"

    def to_record(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "provider": self.provider,
            "model_name": self.model_name,
            "cost_weight": self.cost_weight,
            "max_concurrency": self.max_concurrency,
            "warm_latency_ms": self.warm_latency_ms,
            "base_concurrency": self.base_concurrency,
            "max_concurrency_limit": self.max_concurrency_limit,
            "cold_start_penalty_ms": self.cold_start_penalty_ms,
            "warm_ttl_s": self.warm_ttl_s,
            "hot_ttl_s": self.hot_ttl_s,
            "unload_ttl_s": self.unload_ttl_s,
            "max_queue_depth": self.max_queue_depth,
            "version": self.version,
            "system_prompt": self.system_prompt,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout_s": self.timeout_s,
            "healthy": self.healthy,
            "inflight": self.inflight,
            "queue_depth": self.queue_depth,
            "chaos_extra_latency_ms": self.chaos_extra_latency_ms,
            "chaos_error_rate": self.chaos_error_rate,
            "latencies_ms": list(self.latencies_ms),
            "successes": self.successes,
            "failures": self.failures,
            "ewma_latency_ms": self.ewma_latency_ms,
            "last_used_at": self.last_used_at,
            "last_loaded_at": self.last_loaded_at,
            "last_scale_at": self.last_scale_at,
            "residency_state": self.residency_state,
            "cold_starts": self.cold_starts,
            "shed_events": self.shed_events,
            "autoscale_up_events": self.autoscale_up_events,
            "autoscale_down_events": self.autoscale_down_events,
            "evictions": self.evictions,
        }

    @classmethod
    def from_record(cls, record: dict) -> "BackendState":
        state = cls(
            name=record["name"],
            url=record["url"],
            provider=record.get("provider", "ollama"),
            model_name=record["model_name"],
            cost_weight=float(record["cost_weight"]),
            max_concurrency=int(record["max_concurrency"]),
            warm_latency_ms=float(record.get("warm_latency_ms", 750.0)),
            base_concurrency=int(record.get("base_concurrency", record.get("max_concurrency", 1))),
            max_concurrency_limit=int(record.get("max_concurrency_limit", max(int(record.get("max_concurrency", 1)), int(record.get("base_concurrency", record.get("max_concurrency", 1)))))),
            cold_start_penalty_ms=float(record.get("cold_start_penalty_ms", 650.0)),
            warm_ttl_s=float(record.get("warm_ttl_s", 90.0)),
            hot_ttl_s=float(record.get("hot_ttl_s", 30.0)),
            unload_ttl_s=float(record.get("unload_ttl_s", 150.0)),
            max_queue_depth=int(record.get("max_queue_depth", 0)),
            version=record.get("version", "stable"),
            system_prompt=record.get("system_prompt", "You are a concise assistant. Answer in one or two short sentences."),
            temperature=float(record.get("temperature", 0.2)),
            max_tokens=int(record.get("max_tokens", 96)),
            timeout_s=float(record.get("timeout_s", 60.0)),
            healthy=bool(record.get("healthy", True)),
            inflight=int(record.get("inflight", 0)),
            queue_depth=int(record.get("queue_depth", 0)),
            chaos_extra_latency_ms=int(record.get("chaos_extra_latency_ms", 0)),
            chaos_error_rate=float(record.get("chaos_error_rate", 0.0)),
        )
        state.latencies_ms.extend(record.get("latencies_ms", []))
        state.successes = int(record.get("successes", 0))
        state.failures = int(record.get("failures", 0))
        state.ewma_latency_ms = float(record.get("ewma_latency_ms", 0.0))
        last_used_at = record.get("last_used_at")
        state.last_used_at = float(last_used_at) if last_used_at is not None else None
        last_loaded_at = record.get("last_loaded_at")
        state.last_loaded_at = float(last_loaded_at) if last_loaded_at is not None else None
        last_scale_at = record.get("last_scale_at")
        state.last_scale_at = float(last_scale_at) if last_scale_at is not None else None
        state.residency_state = record.get("residency_state", "unloaded")
        state.cold_starts = int(record.get("cold_starts", 0))
        state.shed_events = int(record.get("shed_events", 0))
        state.autoscale_up_events = int(record.get("autoscale_up_events", 0))
        state.autoscale_down_events = int(record.get("autoscale_down_events", 0))
        state.evictions = int(record.get("evictions", 0))
        return state


class BackendRegistry:
    def __init__(self, *, storage: PersistenceStore | None = None, max_loaded_backends: int = 2) -> None:
        self._lock = Lock()
        self._states: dict[str, BackendState] = {}
        self._rr_cursor = 0
        self.storage = storage
        self.max_loaded_backends = max(1, max_loaded_backends)

    def load_records(self, records: list[dict]) -> None:
        with self._lock:
            self._states = {record["name"]: BackendState.from_record(record) for record in records}
            self._refresh_runtime_unlocked()

    def register_backend(
        self,
        *,
        name: str,
        url: str,
        provider: str,
        model_name: str,
        cost_weight: float,
        max_concurrency: int,
        warm_latency_ms: float,
        base_concurrency: int | None = None,
        max_concurrency_limit: int | None = None,
        cold_start_penalty_ms: float = 650.0,
        warm_ttl_s: float = 90.0,
        hot_ttl_s: float = 30.0,
        unload_ttl_s: float = 150.0,
        max_queue_depth: int = 0,
        version: str = "stable",
        system_prompt: str = "You are a concise assistant. Answer in one or two short sentences.",
        temperature: float = 0.2,
        max_tokens: int = 96,
        timeout_s: float = 60.0,
    ) -> None:
        base_concurrency = max(1, base_concurrency or max_concurrency)
        max_concurrency_limit = max(base_concurrency, max_concurrency_limit or max_concurrency)
        with self._lock:
            self._states[name] = BackendState(
                name=name,
                url=url,
                provider=provider,
                model_name=model_name,
                cost_weight=cost_weight,
                max_concurrency=base_concurrency,
                warm_latency_ms=warm_latency_ms,
                base_concurrency=base_concurrency,
                max_concurrency_limit=max_concurrency_limit,
                cold_start_penalty_ms=cold_start_penalty_ms,
                warm_ttl_s=warm_ttl_s,
                hot_ttl_s=hot_ttl_s,
                unload_ttl_s=unload_ttl_s,
                max_queue_depth=max_queue_depth,
                version=version,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
            )
            self._persist_unlocked()

    def snapshots(self) -> list[BackendState]:
        with self._lock:
            self._refresh_runtime_unlocked()
            return [self._copy(self._states[name]) for name in sorted(self._states)]

    def get(self, name: str) -> BackendState:
        with self._lock:
            self._refresh_runtime_unlocked()
            return self._copy(self._states[name])

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._states.keys())

    def exists(self, name: str) -> bool:
        with self._lock:
            return name in self._states

    def prepare_dispatch(self, name: str) -> bool:
        with self._lock:
            now_s = time()
            state = self._states[name]
            cold_start = state.residency_state in {"unloaded", "loading"}
            if cold_start:
                state.residency_state = "loading"
                state.last_loaded_at = now_s
            else:
                state.residency_state = "hot"
            self._enforce_loaded_budget_unlocked(preferred=name, now_s=now_s)
            self._persist_unlocked()
            return cold_start

    def next_round_robin(self, candidates: list[str]) -> str:
        with self._lock:
            if not candidates:
                raise ValueError("no candidates")
            choice = candidates[self._rr_cursor % len(candidates)]
            self._rr_cursor += 1
            return choice

    def admit(self, name: str, *, priority: str, allow_queue: bool = True) -> str:
        with self._lock:
            self._refresh_runtime_unlocked()
            now_s = time()
            state = self._states[name]
            if not state.healthy:
                state.shed_events += 1
                self._persist_unlocked()
                return "shed"
            if state.inflight < state.max_concurrency:
                state.inflight += 1
                self._touch_loaded_unlocked(state, now_s=now_s)
                self._persist_unlocked()
                return "reserved"
            if not allow_queue:
                state.shed_events += 1
                self._maybe_scale_up_unlocked(state, now_s=now_s, pressure="direct_shed")
                self._persist_unlocked()
                return "shed"
            queue_limit = state.effective_queue_limit + (1 if priority == "high" else 0)
            if state.queue_depth >= queue_limit:
                state.shed_events += 1
                self._maybe_scale_up_unlocked(state, now_s=now_s, pressure="queue_shed")
                self._persist_unlocked()
                return "shed"
            state.queue_depth += 1
            self._maybe_scale_up_unlocked(state, now_s=now_s, pressure="queued")
            self._persist_unlocked()
            return "queued"

    def reserve(self, name: str) -> bool:
        with self._lock:
            now_s = time()
            state = self._states[name]
            if not state.healthy or state.inflight >= state.max_concurrency:
                return False
            state.inflight += 1
            self._touch_loaded_unlocked(state, now_s=now_s)
            self._persist_unlocked()
            return True

    def promote_queued(self, name: str) -> bool:
        with self._lock:
            self._refresh_runtime_unlocked()
            now_s = time()
            state = self._states[name]
            if state.queue_depth > 0:
                state.queue_depth -= 1
            if not state.healthy or state.inflight >= state.max_concurrency:
                self._maybe_scale_up_unlocked(state, now_s=now_s, pressure="promote_failed")
                self._persist_unlocked()
                return False
            state.inflight += 1
            self._touch_loaded_unlocked(state, now_s=now_s)
            self._persist_unlocked()
            return True

    def release_queue(self, name: str) -> None:
        with self._lock:
            state = self._states[name]
            if state.queue_depth > 0:
                state.queue_depth -= 1
                self._persist_unlocked()

    def release(self, name: str) -> None:
        with self._lock:
            now_s = time()
            state = self._states[name]
            if state.inflight > 0:
                state.inflight -= 1
            self._refresh_runtime_unlocked()
            self._maybe_scale_down_unlocked(state, now_s=now_s)
            self._enforce_loaded_budget_unlocked(preferred=name, now_s=now_s)
            if state.inflight == 0 and state.queue_depth == 0 and state.residency_state == "hot":
                state.residency_state = "warm"
            self._persist_unlocked()

    def record_success(self, name: str, latency_ms: float, *, cold_start: bool = False) -> None:
        with self._lock:
            self._refresh_runtime_unlocked()
            now_s = time()
            state = self._states[name]
            state.successes += 1
            state.latencies_ms.append(latency_ms)
            state.ewma_latency_ms = latency_ms if state.ewma_latency_ms == 0 else ((state.ewma_latency_ms * 0.7) + (latency_ms * 0.3))
            state.healthy = True
            state.last_used_at = now_s
            state.last_loaded_at = now_s
            state.residency_state = "hot"
            if cold_start:
                state.cold_starts += 1
            self._maybe_scale_up_unlocked(state, now_s=now_s, pressure="success")
            self._enforce_loaded_budget_unlocked(preferred=name, now_s=now_s)
            self._persist_unlocked()

    def record_failure(self, name: str) -> None:
        with self._lock:
            self._refresh_runtime_unlocked()
            state = self._states[name]
            state.failures += 1
            if state.error_rate >= 0.2 and (state.successes + state.failures) >= 5:
                state.healthy = False
            self._maybe_scale_down_unlocked(state, now_s=time())
            self._persist_unlocked()

    def mark_rollout(self, baseline: str, canary: str) -> None:
        with self._lock:
            for state in self._states.values():
                state.version = "stable"
            self._states[baseline].version = "baseline"
            self._states[canary].version = "canary"
            self._persist_unlocked()

    def clear_rollout(self) -> None:
        with self._lock:
            for state in self._states.values():
                state.version = "stable"
            self._persist_unlocked()

    def rollback_canary(self, canary: str) -> None:
        with self._lock:
            self._states[canary].healthy = False
            self._states[canary].version = "canary"
            self._persist_unlocked()

    def update_chaos(self, name: str, *, extra_latency_ms: int, error_rate: float) -> BackendState:
        with self._lock:
            state = self._states[name]
            state.chaos_extra_latency_ms = extra_latency_ms
            state.chaos_error_rate = error_rate
            self._persist_unlocked()
            return self._copy(state)

    def reset_runtime(self, *, clear_chaos: bool = True) -> None:
        with self._lock:
            for state in self._states.values():
                state.healthy = True
                state.inflight = 0
                state.queue_depth = 0
                state.latencies_ms.clear()
                state.successes = 0
                state.failures = 0
                state.ewma_latency_ms = 0.0
                state.last_used_at = None
                state.last_loaded_at = None
                state.last_scale_at = None
                state.residency_state = "unloaded"
                state.cold_starts = 0
                state.shed_events = 0
                state.autoscale_up_events = 0
                state.autoscale_down_events = 0
                state.evictions = 0
                state.max_concurrency = state.base_concurrency or state.max_concurrency
                state.version = "stable"
                if clear_chaos:
                    state.chaos_extra_latency_ms = 0
                    state.chaos_error_rate = 0.0
            self._rr_cursor = 0
            self._persist_unlocked()

    def _persist_unlocked(self) -> None:
        if self.storage is not None:
            self.storage.save_backends([state.to_record() for state in self._states.values()])

    def _refresh_runtime_unlocked(self) -> None:
        now_s = time()
        for state in self._states.values():
            idle_s = float("inf") if state.last_used_at is None else max(0.0, now_s - state.last_used_at)
            if state.residency_state == "loading":
                state.residency_state = "loading"
            elif state.inflight > 0:
                state.residency_state = "hot"
            elif state.residency_state == "unloaded":
                state.residency_state = "unloaded"
            elif state.last_used_at is None:
                state.residency_state = "unloaded"
            elif idle_s >= state.unload_ttl_s:
                state.residency_state = "unloaded"
            elif idle_s >= state.hot_ttl_s:
                state.residency_state = "warm"
            else:
                state.residency_state = "hot"
            self._maybe_scale_down_unlocked(state, now_s=now_s)
        self._enforce_loaded_budget_unlocked(preferred=None, now_s=now_s)

    def _touch_loaded_unlocked(self, state: BackendState, *, now_s: float) -> None:
        if state.last_loaded_at is None:
            state.last_loaded_at = now_s
        if state.residency_state == "unloaded":
            state.residency_state = "loading"

    def _maybe_scale_up_unlocked(self, state: BackendState, *, now_s: float, pressure: str) -> None:
        if state.max_concurrency >= state.max_concurrency_limit:
            return
        if state.last_scale_at is not None and (now_s - state.last_scale_at) < 2.0:
            return
        if state.queue_depth <= 0 and state.outstanding_requests < max(1, state.max_concurrency):
            return
        state.max_concurrency += 1
        state.autoscale_up_events += 1
        state.last_scale_at = now_s

    def _maybe_scale_down_unlocked(self, state: BackendState, *, now_s: float) -> None:
        if state.max_concurrency <= max(1, state.base_concurrency):
            return
        if state.inflight > 0 or state.queue_depth > 0:
            return
        if state.last_scale_at is not None and (now_s - state.last_scale_at) < 10.0:
            return
        idle_s = float("inf") if state.last_used_at is None else max(0.0, now_s - state.last_used_at)
        if idle_s < 20.0:
            return
        state.max_concurrency -= 1
        state.autoscale_down_events += 1
        state.last_scale_at = now_s

    def _enforce_loaded_budget_unlocked(self, *, preferred: str | None, now_s: float) -> None:
        loaded_states = [state for state in self._states.values() if state.loaded]
        if len(loaded_states) <= self.max_loaded_backends:
            return
        candidates = sorted(
            (
                state
                for state in loaded_states
                if state.name != preferred and state.inflight == 0 and state.queue_depth == 0
            ),
            key=lambda item: (item.last_used_at or item.last_loaded_at or 0.0, item.cost_weight, item.name),
        )
        while len(loaded_states) > self.max_loaded_backends and candidates:
            evicted = candidates.pop(0)
            evicted.residency_state = "unloaded"
            evicted.last_loaded_at = None
            evicted.max_concurrency = max(1, evicted.base_concurrency)
            evicted.evictions += 1
            loaded_states = [state for state in self._states.values() if state.loaded]

    @staticmethod
    def _copy(state: BackendState) -> BackendState:
        return BackendState.from_record(state.to_record())
