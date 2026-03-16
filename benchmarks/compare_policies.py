from __future__ import annotations

import asyncio
import json

from benchmarks.run_benchmark import benchmark_suite


async def main() -> None:
    payload = await benchmark_suite(requests=12, concurrency=3, policies=["round_robin", "latency_aware", "cost_aware", "slo_aware"])
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
