from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import httpx

import control_plane.main as main_module
from control_plane.metrics import MetricsTracker
from control_plane.registry import BackendRegistry
from control_plane.router import Router
from control_plane.schemas import BackendChaosRequest, InferenceRequest, RuntimeResetRequest
from control_plane.storage import PersistenceStore


SAMPLE_BACKENDS = [
    {
        "name": "qwen-edge",
        "url": "http://ollama",
        "provider": "ollama",
        "model_name": "qwen2.5:0.5b",
        "cost_weight": 0.8,
        "max_concurrency": 1,
        "warm_latency_ms": 450.0,
    },
    {
        "name": "llama-balanced",
        "url": "http://ollama",
        "provider": "ollama",
        "model_name": "llama3.2:1b",
        "cost_weight": 1.1,
        "max_concurrency": 1,
        "warm_latency_ms": 700.0,
    },
]


def register_backends(registry: BackendRegistry) -> None:
    for backend in SAMPLE_BACKENDS:
        registry.register_backend(**backend)


class ScriptedRouter(Router):
    def __init__(self, *, outcomes: dict[str, list[dict | Exception]], **kwargs) -> None:
        super().__init__(**kwargs)
        self.outcomes = {backend: list(values) for backend, values in outcomes.items()}
        self.calls: list[str] = []

    async def _dispatch(self, backend: str, request: InferenceRequest) -> dict:
        self.calls.append(backend)
        outcome = self.outcomes[backend].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class StorageRegressionTests(unittest.TestCase):
    def test_backend_round_trip_persists_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PersistenceStore(str(Path(tmpdir) / "state.db"))
            store.initialize()
            registry = BackendRegistry(storage=store)
            register_backends(registry)
            registry.record_success("qwen-edge", 123.0)
            registry.update_chaos("qwen-edge", extra_latency_ms=250, error_rate=0.25)

            restored = BackendRegistry(storage=store)
            restored.load_records(store.load_backends())
            snapshot = restored.get("qwen-edge")

            self.assertEqual(snapshot.successes, 1)
            self.assertEqual(snapshot.p95_latency_ms, 123.0)
            self.assertEqual(snapshot.chaos_extra_latency_ms, 250)
            self.assertAlmostEqual(snapshot.chaos_error_rate, 0.25)
            store.close()


class RouterRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.store = PersistenceStore(str(Path(self.tempdir.name) / "state.db"))
        self.store.initialize()
        self.addCleanup(self.store.close)

    async def test_queue_depth_resets_when_retry_and_fallback_are_saturated(self) -> None:
        registry = BackendRegistry(storage=self.store)
        register_backends(registry)
        metrics = MetricsTracker()
        client = httpx.AsyncClient()
        self.addAsyncCleanup(client.aclose)
        router = Router(registry=registry, metrics=metrics, client=client, storage=self.store)

        self.assertTrue(registry.reserve("qwen-edge"))
        self.assertTrue(registry.reserve("llama-balanced"))

        with patch("control_plane.router.asyncio.sleep", new=AsyncMock()):
            response = await router.handle(InferenceRequest(input="x", preferred_backend="qwen-edge", priority="medium"))

        self.assertTrue(response.rejected)
        self.assertTrue(response.fallback_used)
        self.assertEqual(response.reason, "fallback capacity")
        self.assertEqual(registry.get("qwen-edge").queue_depth, 0)
        self.assertEqual(registry.get("llama-balanced").queue_depth, 0)
        self.assertEqual(self.store.list_request_history(limit=1)[0]["reason"], "fallback capacity")

    async def test_backend_error_uses_fallback_successfully(self) -> None:
        registry = BackendRegistry(storage=self.store)
        register_backends(registry)
        metrics = MetricsTracker()
        client = httpx.AsyncClient()
        self.addAsyncCleanup(client.aclose)
        router = ScriptedRouter(
            registry=registry,
            metrics=metrics,
            client=client,
            storage=self.store,
            outcomes={
                "qwen-edge": [httpx.ConnectError("primary failed")],
                "llama-balanced": [{"result": "recovered", "model": "llama3.2:1b"}],
            },
        )

        response = await router.handle(InferenceRequest(input="x", preferred_backend="qwen-edge"))

        self.assertEqual(router.calls, ["qwen-edge", "llama-balanced"])
        self.assertEqual(response.backend, "llama-balanced")
        self.assertTrue(response.fallback_used)
        self.assertFalse(response.rejected)
        self.assertEqual(response.result, "recovered")
        self.assertTrue(self.store.list_request_history(limit=1))

    async def test_backend_error_returns_rejected_response_when_fallback_fails(self) -> None:
        registry = BackendRegistry(storage=self.store)
        register_backends(registry)
        metrics = MetricsTracker()
        client = httpx.AsyncClient()
        self.addAsyncCleanup(client.aclose)
        router = ScriptedRouter(
            registry=registry,
            metrics=metrics,
            client=client,
            storage=self.store,
            outcomes={
                "qwen-edge": [httpx.ConnectError("primary failed")],
                "llama-balanced": [httpx.ConnectError("fallback failed")],
            },
        )

        response = await router.handle(InferenceRequest(input="x", preferred_backend="qwen-edge"))

        self.assertEqual(router.calls, ["qwen-edge", "llama-balanced"])
        self.assertTrue(response.rejected)
        self.assertTrue(response.fallback_used)
        self.assertEqual(response.backend, "llama-balanced")
        self.assertEqual(response.reason, "backend error")


class MainModuleRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.store = PersistenceStore(str(Path(self.tempdir.name) / "state.db"))
        self.store.initialize()
        self.addCleanup(self.store.close)
        self.client = httpx.AsyncClient()
        self.addCleanup(lambda: asyncio.run(self.client.aclose()))
        main_module.storage = self.store
        main_module.registry = BackendRegistry(storage=self.store)
        register_backends(main_module.registry)
        main_module.metrics = MetricsTracker()
        main_module.router = Router(
            registry=main_module.registry,
            metrics=main_module.metrics,
            client=self.client,
            storage=self.store,
        )
        main_module.rollout_state = {"baseline": None, "canary": None, "traffic_percent": 0}

    def tearDown(self) -> None:
        self.store.close()

    def test_unknown_preferred_backend_returns_404(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(main_module.infer(InferenceRequest(input="x", preferred_backend="missing-backend")))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_rollout_waits_for_minimum_samples(self) -> None:
        main_module.rollout_state.update({"baseline": "qwen-edge", "canary": "llama-balanced", "traffic_percent": 10})
        main_module.registry.record_success("llama-balanced", 50.0)

        main_module._evaluate_rollout()

        self.assertEqual(main_module.rollout_state["baseline"], "qwen-edge")
        self.assertEqual(main_module.rollout_state["canary"], "llama-balanced")
        self.assertTrue(main_module.registry.get("llama-balanced").healthy)
        self.assertEqual(main_module.metrics.canary_rollbacks_total, 0)

    def test_rollout_routes_to_canary_when_random_sample_hits(self) -> None:
        main_module.rollout_state.update({"baseline": "qwen-edge", "canary": "llama-balanced", "traffic_percent": 10})
        with patch("control_plane.main.random.random", return_value=0.05):
            routed = main_module._maybe_route_to_canary(InferenceRequest(input="x"))
        self.assertEqual(routed.preferred_backend, "llama-balanced")

    def test_rollout_routes_to_baseline_when_random_sample_misses(self) -> None:
        main_module.rollout_state.update({"baseline": "qwen-edge", "canary": "llama-balanced", "traffic_percent": 10})
        with patch("control_plane.main.random.random", return_value=0.15):
            routed = main_module._maybe_route_to_canary(InferenceRequest(input="x"))
        self.assertEqual(routed.preferred_backend, "qwen-edge")

    def test_chaos_update_and_reset_persist(self) -> None:
        main_module.update_backend_chaos("qwen-edge", BackendChaosRequest(extra_latency_ms=300, error_rate=0.4))
        main_module.storage.append_request_history({
            "created_at": "2026-01-01T00:00:00+00:00",
            "request_id": "req-1",
            "policy": "slo_aware",
            "priority": "medium",
            "latency_budget_ms": 2500,
            "preferred_backend": None,
            "chosen_backend": "qwen-edge",
            "final_backend": "qwen-edge",
            "model_name": "qwen2.5:0.5b",
            "queued": False,
            "fallback_used": False,
            "rejected": False,
            "status": "success",
            "reason": None,
            "latency_ms": 100.0,
            "input_excerpt": "x",
        })

        main_module.reset_runtime(RuntimeResetRequest(clear_history=True, clear_chaos=True))
        restored = BackendRegistry(storage=self.store)
        restored.load_records(self.store.load_backends())
        snapshot = restored.get("qwen-edge")

        self.assertEqual(snapshot.chaos_extra_latency_ms, 0)
        self.assertEqual(snapshot.chaos_error_rate, 0.0)
        self.assertEqual(self.store.list_request_history(limit=10), [])


if __name__ == "__main__":
    unittest.main()


