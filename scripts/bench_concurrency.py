from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from pathlib import Path

import httpx


async def one_request(client: httpx.AsyncClient, url: str, image_path: Path) -> tuple[int, float]:
    start = time.perf_counter()
    with image_path.open("rb") as image_file:
        files = {"image": (image_path.name, image_file.read(), "image/png")}
    response = await client.post(url, files=files)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return response.status_code, elapsed_ms


async def run_benchmark(url: str, image_path: Path, requests: int, concurrency: int) -> None:
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    timeout = httpx.Timeout(180)
    latencies: list[float] = []
    status_counts: dict[int, int] = {}

    started = time.perf_counter()
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        async def guarded_request() -> None:
            async with semaphore:
                status_code, elapsed_ms = await one_request(client, url, image_path)
                status_counts[status_code] = status_counts.get(status_code, 0) + 1
                latencies.append(elapsed_ms)

        await asyncio.gather(*(guarded_request() for _ in range(requests)))

    total_seconds = time.perf_counter() - started
    sorted_latencies = sorted(latencies)
    p95 = sorted_latencies[int(len(sorted_latencies) * 0.95) - 1]

    print(f"requests={requests}")
    print(f"concurrency={concurrency}")
    print(f"total_seconds={total_seconds:.2f}")
    print(f"throughput_rps={requests / total_seconds:.2f}")
    print(f"latency_avg_ms={statistics.mean(latencies):.2f}")
    print(f"latency_p50_ms={statistics.median(latencies):.2f}")
    print(f"latency_p95_ms={p95:.2f}")
    print(f"status_counts={status_counts}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark PaddleOCR LAN service concurrency.")
    parser.add_argument("image", type=Path, help="Path to one image file.")
    parser.add_argument("--url", default="http://127.0.0.1:8866/ocr")
    parser.add_argument("--requests", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()

    asyncio.run(run_benchmark(args.url, args.image, args.requests, args.concurrency))


if __name__ == "__main__":
    main()
