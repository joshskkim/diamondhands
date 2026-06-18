"""Load driver for the HTTP MCP server.

Opens N concurrent MCP sessions (the real Streamable-HTTP client + JSON-RPC handshake) and
fires a fixed number of `tools/call` requests per session, then reports latency percentiles
and throughput. Used to produce the numbers in docs/mcp-server.md.

Prereqs: the Diamond API running, and the MCP server running with MCP_TRANSPORT=http
(disable rate limiting to measure raw capacity: MCP_RATE_LIMIT_ENABLED=false).

Example:
    MCP_RATE_LIMIT_ENABLED=false MCP_TRACING_ENABLED=false MCP_TRANSPORT=http \\
        uv run diamond-mcp &
    uv run python loadtest/driver.py --concurrency 20 --requests 50 --tool get_today_games
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def _worker(url: str, headers: dict[str, str], tool: str, n: int, out: list[float]) -> None:
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for _ in range(n):
                start = time.perf_counter()
                await session.call_tool(tool, {})
                out.append(time.perf_counter() - start)


async def run(args: argparse.Namespace) -> None:
    headers = {"Authorization": f"Bearer {args.api_key}"} if args.api_key else {}
    latencies: list[float] = []

    started = time.perf_counter()
    await asyncio.gather(
        *(
            _worker(args.url, headers, args.tool, args.requests, latencies)
            for _ in range(args.concurrency)
        )
    )
    elapsed = time.perf_counter() - started

    latencies.sort()
    total = len(latencies)
    ms = [x * 1000 for x in latencies]

    def pct(p: float) -> float:
        return ms[min(total - 1, int(p / 100 * total))]

    print(f"\ntool={args.tool}  concurrency={args.concurrency}  requests={total}")
    print(f"throughput : {total / elapsed:8.1f} req/s   (wall {elapsed:.2f}s)")
    print(f"latency p50: {statistics.median(ms):8.1f} ms")
    print(f"latency p95: {pct(95):8.1f} ms")
    print(f"latency p99: {pct(99):8.1f} ms")
    print(f"latency max: {ms[-1]:8.1f} ms")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:8090/mcp")
    ap.add_argument("--tool", default="get_today_games")
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--requests", type=int, default=50, help="requests per worker session")
    ap.add_argument("--api-key", default=None)
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
