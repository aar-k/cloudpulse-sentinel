"""Fake services that send metrics. Healthy by default; a service goes faulty when the
Remediation Service says so (dashboard button) and recovers when a fix is executed.

  python data/simulator.py                      # run from your laptop
Environment: METRICS_URL, REMEDIATION_URL, INTERVAL, SERVICES (comma separated), INTERNAL_KEY
"""
import os
import random
import time

import httpx

METRICS_URL = os.getenv("METRICS_URL", "http://localhost:8001/metrics")
REMEDIATION_URL = os.getenv("REMEDIATION_URL", "http://localhost:8003")
INTERVAL = float(os.getenv("INTERVAL", "2"))
SERVICES = os.getenv("SERVICES", "payment-api,auth-api,orders-api,batch-worker").split(",")
HEADERS = {"X-Internal-Key": os.getenv("INTERNAL_KEY", "")}


def sample(service: str, fault: bool) -> dict:
    m = {
        "service": service,
        "cpu": random.gauss(35, 5),
        "memory": random.gauss(50, 4),
        "latency_ms": random.gauss(120, 15),
        "error_rate": abs(random.gauss(0.5, 0.2)),
        "request_count": random.gauss(100, 8),
    }
    if service == "batch-worker":      # an under-used service, used by the cost/waste report
        m.update(cpu=random.gauss(6, 2), memory=random.gauss(28, 3))
    if fault:
        m.update(cpu=random.gauss(95, 2), memory=random.gauss(85, 3),
                 latency_ms=random.gauss(900, 60), error_rate=random.gauss(9, 1),
                 request_count=random.gauss(220, 15))
    for k in ("cpu", "memory", "error_rate"):
        m[k] = round(min(max(m[k], 0), 100), 2)
    m["latency_ms"] = round(max(m["latency_ms"], 1), 1)
    m["request_count"] = round(max(m["request_count"], 0), 1)
    return m


def is_faulty(client: httpx.Client, service: str) -> bool:
    try:
        return client.get(f"{REMEDIATION_URL}/demo/state/{service}", headers=HEADERS, timeout=3).json()["fault"]
    except Exception:  # noqa: BLE001
        return False


def main():
    print(f"Simulator sending to {METRICS_URL} every {INTERVAL}s for {SERVICES}")
    with httpx.Client() as client:
        while True:
            for s in SERVICES:
                fault = is_faulty(client, s)
                try:
                    r = client.post(METRICS_URL, json=sample(s, fault), headers=HEADERS, timeout=5).json()
                    print(f"{s:12} fault={fault!s:5} risk={r.get('risk_score')} "
                          f"sev={r.get('severity')} action={r.get('action')}")
                except Exception as exc:  # noqa: BLE001
                    print(f"{s}: cannot reach metrics service yet ({exc.__class__.__name__})")
            time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
