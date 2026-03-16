from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

import httpx

# Allow direct `python scripts/...py` execution from the repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loadgen.runner import CONTROL_PLANE_URL, run_load

BEFORE_PATH = Path("benchmarks") / "demo_before.json"
AFTER_PATH = Path("benchmarks") / "demo_after.json"
REPORT_PATH = Path("docs") / "demo-report.md"


async def wait_for_control_plane(client: httpx.AsyncClient, *, timeout_s: int = 300) -> None:
    for _ in range(timeout_s):
        try:
            response = await client.get(f"{CONTROL_PLANE_URL}/health")
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1)
    raise TimeoutError("Control plane did not become healthy in time")


def render_report(*, policy: str, before: dict, after: dict, before_summary: dict, after_summary: dict, chaos_backend: str, chaos_error_rate: float, chaos_extra_latency_ms: int) -> str:
    lines = [
        "# Demo Benchmark Report",
        "",
        f"Policy: `{policy}`",
        f"Chaos backend: `{chaos_backend}`",
        f"Injected error rate: `{chaos_error_rate}`",
        f"Injected latency: `{chaos_extra_latency_ms} ms`",
        "",
        "## Before Chaos",
        f"- avg: `{before['avg_ms']} ms`",
        f"- p95: `{before['p95_ms']} ms`",
        f"- rejected: `{before['rejected']}`",
        f"- fallbacks: `{before['fallbacks']}`",
        f"- errors: `{before['errors']}`",
        f"- backend mix: `{json.dumps(before['backends'])}`",
        "",
        "## After Chaos + Rollout",
        f"- avg: `{after['avg_ms']} ms`",
        f"- p95: `{after['p95_ms']} ms`",
        f"- rejected: `{after['rejected']}`",
        f"- fallbacks: `{after['fallbacks']}`",
        f"- errors: `{after['errors']}`",
        f"- backend mix: `{json.dumps(after['backends'])}`",
        "",
        "## Backend Summary Before",
        "```json",
        json.dumps(before_summary, indent=2),
        "```",
        "",
        "## Backend Summary After",
        "```json",
        json.dumps(after_summary, indent=2),
        "```",
    ]
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run a before/after chaos demo suite against the control plane.")
    parser.add_argument("--policy", default="slo_aware")
    parser.add_argument("--requests", type=int, default=12)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--baseline", default="qwen-edge")
    parser.add_argument("--canary", default="qwen-quality")
    parser.add_argument("--traffic-percent", type=int, default=20)
    parser.add_argument("--chaos-backend", default="qwen-quality")
    parser.add_argument("--chaos-error-rate", type=float, default=0.35)
    parser.add_argument("--chaos-extra-latency-ms", type=int, default=900)
    args = parser.parse_args()

    async with httpx.AsyncClient(timeout=120.0) as client:
        await wait_for_control_plane(client)

        await client.post(
            f"{CONTROL_PLANE_URL}/admin/reset-runtime",
            json={"clear_history": True, "clear_chaos": True},
        )
        before = await run_load(
            requests=args.requests,
            concurrency=args.concurrency,
            policy=args.policy,
            reset_runtime=False,
        )
        before_summary = (await client.get(f"{CONTROL_PLANE_URL}/metrics/summary")).json()

        await client.post(
            f"{CONTROL_PLANE_URL}/admin/reset-runtime",
            json={"clear_history": True, "clear_chaos": True},
        )
        await client.post(
            f"{CONTROL_PLANE_URL}/admin/backends/{args.chaos_backend}/chaos",
            json={
                "extra_latency_ms": args.chaos_extra_latency_ms,
                "error_rate": args.chaos_error_rate,
            },
        )
        await client.post(
            f"{CONTROL_PLANE_URL}/rollouts",
            json={
                "baseline": args.baseline,
                "canary": args.canary,
                "traffic_percent": args.traffic_percent,
            },
        )
        after = await run_load(
            requests=args.requests,
            concurrency=args.concurrency,
            policy=args.policy,
            reset_runtime=False,
        )
        after_summary = (await client.get(f"{CONTROL_PLANE_URL}/metrics/summary")).json()

    BEFORE_PATH.write_text(json.dumps(before, indent=2))
    AFTER_PATH.write_text(json.dumps(after, indent=2))
    REPORT_PATH.write_text(
        render_report(
            policy=args.policy,
            before=before,
            after=after,
            before_summary=before_summary,
            after_summary=after_summary,
            chaos_backend=args.chaos_backend,
            chaos_error_rate=args.chaos_error_rate,
            chaos_extra_latency_ms=args.chaos_extra_latency_ms,
        )
    )
    print(json.dumps({
        "before": before,
        "after": after,
        "report": str(REPORT_PATH),
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
