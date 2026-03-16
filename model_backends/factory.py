from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


@dataclass
class BackendProfile:
    name: str
    base_latency_ms: int
    jitter_ms: int
    error_rate: float
    max_concurrency: int
    cost_weight: float


class BackendRequest(BaseModel):
    input: str
    priority: str
    latency_budget_ms: int


class BackendServer:
    def __init__(self, profile: BackendProfile) -> None:
        self.profile = profile
        self._semaphore = asyncio.Semaphore(profile.max_concurrency)

    async def infer(self, request: BackendRequest) -> dict:
        if self._semaphore.locked() and request.priority == "low":
            raise HTTPException(status_code=429, detail="backend saturated")
        async with self._semaphore:
            await asyncio.sleep((self.profile.base_latency_ms + random.randint(0, self.profile.jitter_ms)) / 1000.0)
            if random.random() < self.profile.error_rate:
                raise HTTPException(status_code=503, detail="backend error")
            return {
                "backend": self.profile.name,
                "result": f"{self.profile.name} processed '{request.input[:24]}'",
                "cost_weight": self.profile.cost_weight,
            }


def create_backend_app(profile: BackendProfile) -> FastAPI:
    app = FastAPI(title=profile.name)
    server = BackendServer(profile)

    @app.get("/health")
    def health():
        return {"status": "ok", "backend": profile.name}

    @app.post("/infer")
    async def infer(request: BackendRequest):
        return await server.infer(request)

    return app
