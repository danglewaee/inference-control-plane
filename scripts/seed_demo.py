from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx


def load_models(config_path: Path) -> list[str]:
    records = json.loads(config_path.read_text())
    return sorted({record["model_name"] for record in records})


async def wait_for_ollama(base_url: str, *, timeout_s: int = 600) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(timeout_s):
            try:
                response = await client.get(f"{base_url}/api/tags")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
    raise TimeoutError(f"Ollama did not become ready within {timeout_s} seconds")


async def pull_model(client: httpx.AsyncClient, base_url: str, model_name: str) -> None:
    response = await client.post(
        f"{base_url}/api/pull",
        json={"model": model_name, "stream": False},
        timeout=3600.0,
    )
    response.raise_for_status()


async def warm_model(client: httpx.AsyncClient, base_url: str, model_name: str) -> None:
    response = await client.post(
        f"{base_url}/v1/chat/completions",
        json={
            "model": model_name,
            "messages": [{"role": "user", "content": "Say ready."}],
            "max_tokens": 16,
            "temperature": 0.0,
            "stream": False,
        },
        timeout=300.0,
    )
    response.raise_for_status()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Ollama models for the demo stack.")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--config", default="config/backends.demo.json")
    parser.add_argument("--warmup", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    models = load_models(config_path)
    await wait_for_ollama(args.ollama_url)

    async with httpx.AsyncClient() as client:
        for model_name in models:
            print(f"Pulling {model_name}...")
            await pull_model(client, args.ollama_url, model_name)
            if args.warmup:
                print(f"Warming {model_name}...")
                await warm_model(client, args.ollama_url, model_name)

    print(json.dumps({"status": "seeded", "models": models}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
