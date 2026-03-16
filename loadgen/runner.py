from __future__ import annotations

import asyncio
import os
import random
import statistics
import time
from collections import Counter

import httpx

CONTROL_PLANE_URL = os.getenv("CONTROL_PLANE_URL", "http://127.0.0.1:8000")
PROMPTS = [
    "Summarize why tail latency matters for distributed systems.",
    "Explain fallback routing in one sentence.",
    "Give a short note on canary rollouts.",
    "Describe why observability matters for AI inference platforms.",
]


async def _send(client: httpx.AsyncClient, *, priority: str, latency_budget_ms: int, policy: str | None) -> tuple[float, dict, int]:
    start = time.perf_counter()
    response = await client.post(
        f"{CONTROL_PLANE_URL}/infer",
        json={
            "input": random.choice(PROMPTS),
            "priority": priority,
            "latency_budget_ms": latency_budget_ms,
            "policy": policy,
            "max_tokens": 64,
        },
    )
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    body = response.json()
    return elapsed_ms, body, response.status_code


async def run_load(*, requests: int = 12, concurrency: int = 3, policy: str | None = None, reset_runtime: bool = False, clear_chaos: bool = False) -> dict:
    latencies: list[float] = []
    rejected = 0
    fallbacks = 0
    errors = 0
    backends = Counter()
    priorities = ["high", "medium", "low"]
    budgets = {"high": 1_500, "medium": 2_500, "low": 4_000}
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=120.0) as client:
        if reset_runtime:
            await client.post(
                f"{CONTROL_PLANE_URL}/admin/reset-runtime",
                json={"clear_history": True, "clear_chaos": clear_chaos},
            )

        async def worker(idx: int) -> None:
            nonlocal rejected, fallbacks, errors
            async with sem:
                priority = priorities[idx % len(priorities)]
                try:
                    latency_ms, body, status_code = await _send(
                        client,
                        priority=priority,
                        latency_budget_ms=budgets[priority],
                        policy=policy,
                    )
                except httpx.HTTPError:
                    errors += 1
                    return
                latencies.append(latency_ms)
                if status_code >= 500:
                    errors += 1
                    return
                if body.get("rejected"):
                    rejected += 1
                if body.get("fallback_used"):
                    fallbacks += 1
                if body.get("backend"):
                    backends[body["backend"]] += 1

        await asyncio.gather(*(worker(i) for i in range(requests)))

    ordered = sorted(latencies)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)] if ordered else 0.0
    p99 = ordered[max(0, int(len(ordered) * 0.99) - 1)] if ordered else 0.0
    return {
        "requests": requests,
        "completed": len(latencies),
        "concurrency": concurrency,
        "avg_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "p50_ms": round(statistics.median(latencies), 2) if latencies else 0.0,
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "rejected": rejected,
        "fallbacks": fallbacks,
        "errors": errors,
        "backends": dict(backends),
    }


if __name__ == "__main__":
    print(asyncio.run(run_load()))
