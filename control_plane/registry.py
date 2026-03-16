from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import ceil
from threading import Lock
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

    def to_record(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "provider": self.provider,
            "model_name": self.model_name,
            "cost_weight": self.cost_weight,
            "max_concurrency": self.max_concurrency,
            "warm_latency_ms": self.warm_latency_ms,
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
        return state


class BackendRegistry:
    def __init__(self, *, storage: PersistenceStore | None = None) -> None:
        self._lock = Lock()
        self._states: dict[str, BackendState] = {}
        self._rr_cursor = 0
        self.storage = storage

    def load_records(self, records: list[dict]) -> None:
        with self._lock:
            self._states = {record["name"]: BackendState.from_record(record) for record in records}

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
        version: str = "stable",
        system_prompt: str = "You are a concise assistant. Answer in one or two short sentences.",
        temperature: float = 0.2,
        max_tokens: int = 96,
        timeout_s: float = 60.0,
    ) -> None:
        with self._lock:
            self._states[name] = BackendState(
                name=name,
                url=url,
                provider=provider,
                model_name=model_name,
                cost_weight=cost_weight,
                max_concurrency=max_concurrency,
                warm_latency_ms=warm_latency_ms,
                version=version,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
            )
            self._persist_unlocked()

    def snapshots(self) -> list[BackendState]:
        with self._lock:
            return [self._copy(self._states[name]) for name in sorted(self._states)]

    def get(self, name: str) -> BackendState:
        with self._lock:
            return self._copy(self._states[name])

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._states.keys())

    def exists(self, name: str) -> bool:
        with self._lock:
            return name in self._states

    def next_round_robin(self, candidates: list[str]) -> str:
        with self._lock:
            if not candidates:
                raise ValueError("no candidates")
            ordered = sorted(candidates)
            choice = ordered[self._rr_cursor % len(ordered)]
            self._rr_cursor += 1
            return choice

    def reserve(self, name: str) -> bool:
        with self._lock:
            state = self._states[name]
            if not state.healthy or state.inflight >= state.max_concurrency:
                state.queue_depth += 1
                self._persist_unlocked()
                return False
            state.inflight += 1
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
            state = self._states[name]
            if state.inflight > 0:
                state.inflight -= 1
                self._persist_unlocked()

    def record_success(self, name: str, latency_ms: float) -> None:
        with self._lock:
            state = self._states[name]
            state.successes += 1
            state.latencies_ms.append(latency_ms)
            state.healthy = True
            self._persist_unlocked()

    def record_failure(self, name: str) -> None:
        with self._lock:
            state = self._states[name]
            state.failures += 1
            if state.error_rate >= 0.2 and (state.successes + state.failures) >= 5:
                state.healthy = False
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
                state.version = "stable"
                if clear_chaos:
                    state.chaos_extra_latency_ms = 0
                    state.chaos_error_rate = 0.0
            self._rr_cursor = 0
            self._persist_unlocked()

    def _persist_unlocked(self) -> None:
        if self.storage is not None:
            self.storage.save_backends([state.to_record() for state in self._states.values()])

    @staticmethod
    def _copy(state: BackendState) -> BackendState:
        return BackendState.from_record(state.to_record())
