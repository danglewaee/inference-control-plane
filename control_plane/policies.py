from __future__ import annotations

from typing import Iterable

from control_plane.registry import BackendState, BackendRegistry


PRIORITY_COST_MULTIPLIER = {
    "high": 1.4,
    "medium": 1.0,
    "low": 0.8,
}

PRIORITY_LATENCY_MULTIPLIER = {
    "high": 1.25,
    "medium": 1.0,
    "low": 0.85,
}


def available_candidates(states: Iterable[BackendState]) -> list[BackendState]:
    return [state for state in states if state.healthy]


def choose_backend(*, policy: str, priority: str, latency_budget_ms: int, registry: BackendRegistry) -> str:
    states = available_candidates(registry.snapshots())
    if not states:
        raise ValueError("no healthy backends")

    if policy == "round_robin":
        ordered = sorted(states, key=lambda state: (state.outstanding_requests, _estimated_latency(state), state.name))
        return registry.next_round_robin([state.name for state in ordered])
    if policy == "latency_aware":
        return min(states, key=lambda state: (_estimated_latency(state), state.outstanding_requests, state.cost_weight)).name
    if policy == "cost_aware":
        feasible = [state for state in states if _estimated_latency(state) <= latency_budget_ms]
        pool = feasible or states
        return min(pool, key=lambda state: (state.cost_weight, state.outstanding_requests, _estimated_latency(state))).name
    if policy == "slo_aware":
        return _choose_slo_aware(states, priority=priority, latency_budget_ms=latency_budget_ms).name
    raise ValueError(f"unknown policy: {policy}")


def choose_fallback(*, failed_backend: str, priority: str, latency_budget_ms: int, registry: BackendRegistry) -> str | None:
    states = [state for state in available_candidates(registry.snapshots()) if state.name != failed_backend]
    if not states:
        return None
    feasible = [state for state in states if _estimated_latency(state) <= latency_budget_ms]
    pool = feasible or states
    return _choose_slo_aware(pool, priority=priority, latency_budget_ms=latency_budget_ms).name


def _choose_slo_aware(states: list[BackendState], *, priority: str, latency_budget_ms: int) -> BackendState:
    cost_multiplier = PRIORITY_COST_MULTIPLIER.get(priority, 1.0)
    latency_multiplier = PRIORITY_LATENCY_MULTIPLIER.get(priority, 1.0)
    scored = []
    for state in states:
        estimated = _estimated_latency(state)
        pressure = state.outstanding_requests / max(1, state.max_concurrency)
        budget_penalty = max(0.0, estimated - latency_budget_ms) * (8.0 * latency_multiplier)
        queue_penalty = pressure * 160.0
        cold_penalty = state.cold_start_penalty_ms * 0.7 if state.is_cold() else 0.0
        error_penalty = state.error_rate * 1000.0
        score = budget_penalty + queue_penalty + cold_penalty + error_penalty + (state.cost_weight * cost_multiplier * 25.0)
        scored.append((score, estimated, state))
    scored.sort(key=lambda item: (item[0], item[1], item[2].name))
    return scored[0][2]


def _estimated_latency(state: BackendState) -> float:
    cold_penalty = state.cold_start_penalty_ms if state.is_cold() else 0.0
    return state.latency_signal_ms + state.estimated_wait_ms + cold_penalty + state.chaos_extra_latency_ms
