from __future__ import annotations

from typing import Iterable

from control_plane.registry import BackendState, BackendRegistry


PRIORITY_COST_MULTIPLIER = {
    "high": 1.4,
    "medium": 1.0,
    "low": 0.8,
}


def available_candidates(states: Iterable[BackendState]) -> list[BackendState]:
    return [state for state in states if state.healthy]


def choose_backend(*, policy: str, priority: str, latency_budget_ms: int, registry: BackendRegistry) -> str:
    states = available_candidates(registry.snapshots())
    if not states:
        raise ValueError("no healthy backends")

    if policy == "round_robin":
        return registry.next_round_robin([state.name for state in states])
    if policy == "latency_aware":
        return min(states, key=lambda state: (_estimated_latency(state), state.queue_depth, state.cost_weight)).name
    if policy == "cost_aware":
        feasible = [state for state in states if _estimated_latency(state) <= latency_budget_ms]
        pool = feasible or states
        return min(pool, key=lambda state: (state.cost_weight, state.queue_depth, _estimated_latency(state))).name
    if policy == "slo_aware":
        return _choose_slo_aware(states, priority=priority, latency_budget_ms=latency_budget_ms).name
    raise ValueError(f"unknown policy: {policy}")


def choose_fallback(*, failed_backend: str, latency_budget_ms: int, registry: BackendRegistry) -> str | None:
    states = [state for state in available_candidates(registry.snapshots()) if state.name != failed_backend]
    if not states:
        return None
    feasible = [state for state in states if _estimated_latency(state) <= latency_budget_ms]
    pool = feasible or states
    return min(pool, key=lambda state: (state.queue_depth, _estimated_latency(state), state.cost_weight)).name


def _choose_slo_aware(states: list[BackendState], *, priority: str, latency_budget_ms: int) -> BackendState:
    multiplier = PRIORITY_COST_MULTIPLIER.get(priority, 1.0)
    scored = []
    for state in states:
        estimated = _estimated_latency(state)
        penalty = max(0.0, estimated - latency_budget_ms)
        score = penalty * 8.0 + state.queue_depth * 3.0 + (state.cost_weight * multiplier)
        scored.append((score, estimated, state))
    scored.sort(key=lambda item: (item[0], item[1], item[2].name))
    return scored[0][2]


def _estimated_latency(state: BackendState) -> float:
    baseline = state.p95_latency_ms or state.warm_latency_ms
    return baseline + (state.queue_depth * 60.0) + (state.inflight * 40.0) + state.chaos_extra_latency_ms
