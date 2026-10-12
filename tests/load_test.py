"""Simple load test for the metrics service (run it yourself, not part of pytest).

  python tests/load_test.py --url http://localhost:8001/metrics --key YOUR_INTERNAL_KEY \
        --requests 300 --concurrency 10

It sends healthy fake metrics for a service called "load-test" and prints throughput and latency.
Copy the printed summary into your report (section 19: Testing and results).
"""
import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

BODY = {"service": "load-test", "cpu": 30, "memory": 40, "latency_ms": 110,
        "error_rate": 0.3, "request_count": 100}


def one(client: httpx.Client, url: str, headers: dict):
    t0 = time.perf_counter()
    try:
        ok = client.post(url, json=BODY, headers=headers, timeout=15).status_code == 200
    except httpx.HTTPError:
        ok = False
    return ok, (time.perf_counter() - t0) * 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8001/metrics")
    ap.add_argument("--key", required=True, help="the INTERNAL_KEY value from your .env file")
    ap.add_argument("--requests", type=int, default=300)
    ap.add_argument("--concurrency", type=int, default=10)
    a = ap.parse_args()
    headers = {"X-Internal-Key": a.key}
    start = time.perf_counter()
    with httpx.Client() as client, ThreadPoolExecutor(max_workers=a.concurrency) as pool:
        results = list(pool.map(lambda _: one(client, a.url, headers), range(a.requests)))
    elapsed = time.perf_counter() - start
    lat = sorted(ms for ok, ms in results if ok)
    ok_count = len(lat)
    print(f"Requests: {a.requests}   concurrency: {a.concurrency}   duration: {elapsed:.1f}s")
    print(f"Succeeded: {ok_count}   failed: {a.requests - ok_count}")
    print(f"Throughput: {a.requests / elapsed:.1f} requests/second")
    if lat:
        print(f"Latency ms: median {statistics.median(lat):.0f}   p95 {lat[int(len(lat) * 0.95) - 1]:.0f}   max {lat[-1]:.0f}")


if __name__ == "__main__":
    main()
