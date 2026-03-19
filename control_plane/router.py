from __future__ import annotations

import asyncio
import random
import time
from uuid import uuid4

import httpx

from control_plane.metrics import MetricsTracker
from control_plane.policies import choose_backend, choose_fallback
from control_plane.registry import BackendRegistry
from control_plane.schemas import InferenceRequest, InferenceResponse
from control_plane.storage import PersistenceStore, utcnow


class Router:
    def __init__(
        self,
        *,
        registry: BackendRegistry,
        metrics: MetricsTracker,
        client: httpx.AsyncClient,
        storage: PersistenceStore | None = None,
        default_policy: str = "slo_aware",
    ) -> None:
        self.registry = registry
        self.metrics = metrics
        self.client = client
        self.storage = storage
        self.default_policy = default_policy

    async def handle(self, request: InferenceRequest) -> InferenceResponse:
        request_id = uuid4().hex
        policy = request.policy or self.default_policy
        chosen_backend = request.preferred_backend
        final_backend = request.preferred_backend
        model_name: str | None = None
        status = "rejected"
        reason: str | None = None
        queued = False
        fallback_used = False
        latency_ms = 0.0
        result: str | None = None
        reserved_backend: str | None = None
        response_backend: str | None = None

        self._log_decision(request_id, "request_received", None, {
            "policy": policy,
            "priority": request.priority,
            "latency_budget_ms": request.latency_budget_ms,
            "preferred_backend": request.preferred_backend,
        })

        try:
            if chosen_backend is None:
                chosen_backend = choose_backend(
                    policy=policy,
                    priority=request.priority,
                    latency_budget_ms=request.latency_budget_ms,
                    registry=self.registry,
                )
            if not self.registry.exists(chosen_backend):
                return self._reject(
                    request_id=request_id,
                    request=request,
                    policy=policy,
                    backend=chosen_backend,
                    chosen_backend=chosen_backend,
                    final_backend=chosen_backend,
                    queued=False,
                    fallback_used=False,
                    status="rejected",
                    reason="unknown backend",
                    rejection_reason="unknown_backend",
                )
            self._log_decision(request_id, "backend_selected", chosen_backend, {"policy": policy})
        except ValueError:
            return self._reject(
                request_id=request_id,
                request=request,
                policy=policy,
                backend="none",
                chosen_backend=None,
                final_backend="none",
                queued=False,
                fallback_used=False,
                status="rejected",
                reason="no healthy backends",
                rejection_reason="no_healthy_backends",
            )

        admission = self.registry.admit(chosen_backend, priority=request.priority, allow_queue=True)
        queued = admission == "queued"
        self._refresh_backend_metrics()
        if admission == "shed":
            self.metrics.record_load_shed(backend=chosen_backend, priority=request.priority, reason="capacity")
            self._log_decision(request_id, "load_shed", chosen_backend, {"priority": request.priority})
            fallback = choose_fallback(
                failed_backend=chosen_backend,
                priority=request.priority,
                latency_budget_ms=request.latency_budget_ms,
                registry=self.registry,
            )
            if not fallback:
                return self._reject(
                    request_id=request_id,
                    request=request,
                    policy=policy,
                    backend=chosen_backend,
                    chosen_backend=chosen_backend,
                    final_backend=chosen_backend,
                    queued=False,
                    fallback_used=False,
                    status="rejected",
                    reason="load shed",
                    rejection_reason="load_shed",
                )
            fallback_used = True
            self.metrics.record_fallback(from_backend=chosen_backend, to_backend=fallback)
            self._log_decision(request_id, "fallback_selected", fallback, {"from_backend": chosen_backend, "stage": "load_shed"})
            chosen_backend = fallback
            admission = self.registry.admit(chosen_backend, priority=request.priority, allow_queue=request.priority == "high")
            queued = admission == "queued"
            if admission == "shed":
                self.metrics.record_load_shed(backend=chosen_backend, priority=request.priority, reason="fallback_capacity")
                return self._reject(
                    request_id=request_id,
                    request=request,
                    policy=policy,
                    backend=chosen_backend,
                    chosen_backend=chosen_backend,
                    final_backend=chosen_backend,
                    queued=False,
                    fallback_used=True,
                    status="rejected",
                    reason="fallback capacity",
                    rejection_reason="fallback_capacity",
                )

        if queued:
            self._log_decision(request_id, "queued", chosen_backend, {"priority": request.priority})
            if request.priority == "low":
                self.registry.release_queue(chosen_backend)
                self.metrics.record_load_shed(backend=chosen_backend, priority=request.priority, reason="low_priority_queue")
                return self._reject(
                    request_id=request_id,
                    request=request,
                    policy=policy,
                    backend=chosen_backend,
                    chosen_backend=chosen_backend,
                    final_backend=chosen_backend,
                    queued=True,
                    fallback_used=False,
                    status="rejected",
                    reason="capacity",
                        rejection_reason="capacity",
                    )
            await asyncio.sleep(0.05)
            if not self.registry.promote_queued(chosen_backend):
                fallback = choose_fallback(
                    failed_backend=chosen_backend,
                    priority=request.priority,
                    latency_budget_ms=request.latency_budget_ms,
                    registry=self.registry,
                )
                if not fallback:
                    self.metrics.record_load_shed(backend=chosen_backend, priority=request.priority, reason="no_fallback")
                    return self._reject(
                        request_id=request_id,
                        request=request,
                        policy=policy,
                        backend=chosen_backend,
                        chosen_backend=chosen_backend,
                        final_backend=chosen_backend,
                        queued=True,
                        fallback_used=False,
                        status="rejected",
                        reason="no fallback",
                        rejection_reason="no_fallback",
                    )
                fallback_used = True
                self.metrics.record_fallback(from_backend=chosen_backend, to_backend=fallback)
                self._log_decision(request_id, "fallback_selected", fallback, {"from_backend": chosen_backend, "stage": "capacity"})
                chosen_backend = fallback
                fallback_admission = self.registry.admit(chosen_backend, priority=request.priority, allow_queue=False)
                if fallback_admission != "reserved":
                    self.metrics.record_load_shed(backend=chosen_backend, priority=request.priority, reason="fallback_capacity")
                    return self._reject(
                        request_id=request_id,
                        request=request,
                        policy=policy,
                        backend=chosen_backend,
                        chosen_backend=chosen_backend,
                        final_backend=chosen_backend,
                        queued=True,
                        fallback_used=True,
                        status="rejected",
                        reason="fallback capacity",
                        rejection_reason="fallback_capacity",
                    )

        start = time.perf_counter()
        reserved_backend = chosen_backend
        response_backend = chosen_backend
        final_backend = chosen_backend
        try:
            payload = await self._dispatch(chosen_backend, request)
            latency_ms = (time.perf_counter() - start) * 1000.0
            model_name = payload.get("model", self.registry.get(chosen_backend).model_name)
            cold_start = bool(payload.get("cold_start"))
            result = payload.get("result", "")
            status = "success"
            self.registry.record_success(chosen_backend, latency_ms, cold_start=cold_start)
            if cold_start:
                self.metrics.record_cold_start(backend=chosen_backend)
            self.metrics.record_request(policy=policy, priority=request.priority, backend=chosen_backend, status=status, latency_ms=latency_ms)
            self._log_decision(
                request_id,
                "dispatch_success",
                chosen_backend,
                {"latency_ms": round(latency_ms, 2), "model_name": model_name, "cold_start": cold_start},
            )
            return self._build_response(
                request_id=request_id,
                backend=chosen_backend,
                model_name=model_name,
                latency_ms=latency_ms,
                queued=queued,
                fallback_used=fallback_used,
                rejected=False,
                result=result,
                reason=None,
            )
        except httpx.HTTPError as exc:
            self.registry.record_failure(chosen_backend)
            self._log_decision(request_id, "dispatch_failed", chosen_backend, {"error": str(exc)})
            fallback = choose_fallback(
                failed_backend=chosen_backend,
                priority=request.priority,
                latency_budget_ms=request.latency_budget_ms,
                registry=self.registry,
            )
            if not fallback:
                status = "error"
                reason = "backend error"
                final_backend = chosen_backend
                self.metrics.record_request(policy=policy, priority=request.priority, backend=chosen_backend, status=status)
                self.metrics.record_rejection(reason="backend_error", priority=request.priority)
                return self._build_response(
                    request_id=request_id,
                    backend=chosen_backend,
                    model_name=None,
                    latency_ms=0.0,
                    queued=queued,
                    fallback_used=fallback_used,
                    rejected=True,
                    result=None,
                    reason=reason,
                )

            fallback_used = True
            self.metrics.record_fallback(from_backend=chosen_backend, to_backend=fallback)
            self._log_decision(request_id, "fallback_selected", fallback, {"from_backend": chosen_backend, "stage": "dispatch_failure"})
            if self.registry.admit(fallback, priority=request.priority, allow_queue=False) != "reserved":
                self.metrics.record_load_shed(backend=fallback, priority=request.priority, reason="fallback_capacity")
                status = "rejected"
                reason = "fallback capacity"
                final_backend = fallback
                self.metrics.record_request(policy=policy, priority=request.priority, backend=fallback, status=status)
                self.metrics.record_rejection(reason="fallback_capacity", priority=request.priority)
                return self._build_response(
                    request_id=request_id,
                    backend=fallback,
                    model_name=None,
                    latency_ms=0.0,
                    queued=queued,
                    fallback_used=True,
                    rejected=True,
                    result=None,
                    reason=reason,
                )

            response_backend = fallback
            final_backend = fallback
            start = time.perf_counter()
            try:
                payload = await self._dispatch(fallback, request)
            except httpx.HTTPError as fallback_exc:
                self.registry.record_failure(fallback)
                status = "fallback_error"
                reason = "backend error"
                self.metrics.record_request(policy=policy, priority=request.priority, backend=fallback, status=status)
                self.metrics.record_rejection(reason="backend_error", priority=request.priority)
                self._log_decision(request_id, "fallback_failed", fallback, {"error": str(fallback_exc)})
                return self._build_response(
                    request_id=request_id,
                    backend=fallback,
                    model_name=None,
                    latency_ms=0.0,
                    queued=queued,
                    fallback_used=True,
                    rejected=True,
                    result=None,
                    reason=reason,
                )

            latency_ms = (time.perf_counter() - start) * 1000.0
            model_name = payload.get("model", self.registry.get(fallback).model_name)
            cold_start = bool(payload.get("cold_start"))
            result = payload.get("result", "")
            status = "fallback_success"
            self.registry.record_success(fallback, latency_ms, cold_start=cold_start)
            if cold_start:
                self.metrics.record_cold_start(backend=fallback)
            self.metrics.record_request(policy=policy, priority=request.priority, backend=fallback, status=status, latency_ms=latency_ms)
            self._log_decision(
                request_id,
                "fallback_success",
                fallback,
                {"latency_ms": round(latency_ms, 2), "model_name": model_name, "cold_start": cold_start},
            )
            return self._build_response(
                request_id=request_id,
                backend=fallback,
                model_name=model_name,
                latency_ms=latency_ms,
                queued=queued,
                fallback_used=True,
                rejected=False,
                result=result,
                reason=None,
            )
        finally:
            if reserved_backend is not None:
                self.registry.release(reserved_backend)
            if response_backend is not None and response_backend != reserved_backend:
                self.registry.release(response_backend)
            self._refresh_backend_metrics()
            self._record_history(
                request_id=request_id,
                request=request,
                policy=policy,
                chosen_backend=chosen_backend,
                final_backend=final_backend,
                model_name=model_name,
                queued=queued,
                fallback_used=fallback_used,
                status=status,
                reason=reason,
                latency_ms=latency_ms,
            )

    async def _dispatch(self, backend: str, request: InferenceRequest) -> dict:
        cold_start = self.registry.prepare_dispatch(backend)
        self._refresh_backend_metrics()
        state = self.registry.get(backend)
        if cold_start and state.cold_start_penalty_ms > 0:
            await asyncio.sleep(state.cold_start_penalty_ms / 1000.0)
        if state.chaos_extra_latency_ms > 0:
            await asyncio.sleep(state.chaos_extra_latency_ms / 1000.0)
        if state.chaos_error_rate > 0 and random.random() < state.chaos_error_rate:
            raise httpx.ReadTimeout(f"Injected chaos failure for {backend}")

        messages = []
        system_prompt = request.system_prompt or state.system_prompt
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": request.input})

        response = await self.client.post(
            f"{state.url}/v1/chat/completions",
            json={
                "model": state.model_name,
                "messages": messages,
                "max_tokens": request.max_tokens or state.max_tokens,
                "temperature": state.temperature,
                "stream": False,
            },
            timeout=state.timeout_s,
        )
        response.raise_for_status()
        payload = response.json()
        choice = payload["choices"][0]["message"]["content"]
        return {
            "result": choice.strip(),
            "model": payload.get("model", state.model_name),
            "usage": payload.get("usage", {}),
            "cold_start": cold_start,
        }

    def _refresh_backend_metrics(self) -> None:
        for state in self.registry.snapshots():
            self.metrics.set_backend_state(
                backend=state.name,
                inflight=state.inflight,
                queue_depth=state.queue_depth,
                healthy=state.healthy,
                outstanding_requests=state.outstanding_requests,
                estimated_wait_ms=state.estimated_wait_ms,
                warm_state=state.warm_state,
                residency_state=state.residency_state,
                current_concurrency=state.max_concurrency,
                max_concurrency_limit=state.max_concurrency_limit,
            )

    def _build_response(
        self,
        *,
        request_id: str,
        backend: str,
        model_name: str | None,
        latency_ms: float,
        queued: bool,
        fallback_used: bool,
        rejected: bool,
        result: str | None,
        reason: str | None,
    ) -> InferenceResponse:
        return InferenceResponse(
            request_id=request_id,
            backend=backend,
            model_name=model_name,
            latency_ms=round(latency_ms, 2),
            queued=queued,
            fallback_used=fallback_used,
            rejected=rejected,
            result=result,
            reason=reason,
        )

    def _reject(
        self,
        *,
        request_id: str,
        request: InferenceRequest,
        policy: str,
        backend: str,
        chosen_backend: str | None,
        final_backend: str | None,
        queued: bool,
        fallback_used: bool,
        status: str,
        reason: str,
        rejection_reason: str,
    ) -> InferenceResponse:
        self._refresh_backend_metrics()
        self.metrics.record_request(policy=policy, priority=request.priority, backend=backend, status=status)
        self.metrics.record_rejection(reason=rejection_reason, priority=request.priority)
        self._record_history(
            request_id=request_id,
            request=request,
            policy=policy,
            chosen_backend=chosen_backend,
            final_backend=final_backend,
            model_name=None,
            queued=queued,
            fallback_used=fallback_used,
            status=status,
            reason=reason,
            latency_ms=0.0,
        )
        return self._build_response(
            request_id=request_id,
            backend=backend,
            model_name=None,
            latency_ms=0.0,
            queued=queued,
            fallback_used=fallback_used,
            rejected=True,
            result=None,
            reason=reason,
        )

    def _record_history(
        self,
        *,
        request_id: str,
        request: InferenceRequest,
        policy: str,
        chosen_backend: str | None,
        final_backend: str | None,
        model_name: str | None,
        queued: bool,
        fallback_used: bool,
        status: str,
        reason: str | None,
        latency_ms: float,
    ) -> None:
        if self.storage is None:
            return
        payload = {
            "created_at": utcnow(),
            "request_id": request_id,
            "policy": policy,
            "priority": request.priority,
            "latency_budget_ms": request.latency_budget_ms,
            "preferred_backend": request.preferred_backend,
            "chosen_backend": chosen_backend,
            "final_backend": final_backend,
            "model_name": model_name,
            "queued": queued,
            "fallback_used": fallback_used,
            "rejected": status in {"rejected", "error", "fallback_error"},
            "status": status,
            "reason": reason,
            "latency_ms": round(latency_ms, 2),
            "input_excerpt": request.input.replace("\n", " ")[:160],
        }
        self.storage.append_request_history(payload)

    def _log_decision(self, request_id: str, event_type: str, backend: str | None, detail: dict) -> None:
        if self.storage is not None:
            self.storage.append_decision_log(request_id=request_id, event_type=event_type, backend=backend, detail=detail)
