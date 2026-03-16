from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

import httpx

# Allow direct `python benchmarks/...py` execution from the repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loadgen.runner import CONTROL_PLANE_URL, run_load

OUT_PATH = Path("benchmarks") / "latest_results.json"


async def benchmark_suite(*, requests: int, concurrency: int, policies: list[str]) -> dict:
    results = {}
    async with httpx.AsyncClient(timeout=120.0) as client:
        for policy in policies:
            await client.post(
                f"{CONTROL_PLANE_URL}/admin/reset-runtime",
                json={"clear_history": True, "clear_chaos": True},
            )
            results[policy] = await run_load(
                requests=requests,
                concurrency=concurrency,
                policy=policy,
                reset_runtime=False,
            )
            results[policy]["backend_summary"] = (await client.get(f"{CONTROL_PLANE_URL}/metrics/summary")).json()["backends"]
    return {"policies": results}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run a multi-policy benchmark against the control plane.")
    parser.add_argument("--requests", type=int, default=12)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--policies", nargs="*", default=["round_robin", "latency_aware", "cost_aware", "slo_aware"])
    args = parser.parse_args()

    payload = await benchmark_suite(requests=args.requests, concurrency=args.concurrency, policies=args.policies)
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
