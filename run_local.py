"""Run the whole CloudPulse Sentinel stack on your laptop WITHOUT Docker.

    python run_local.py

Starts: auth (8004), metrics (8001), incident (8002), remediation (8003), the simulator and the
dashboard (8501). They share one SQLite file (cloudpulse.db). Press Ctrl+C to stop everything.
Settings come from your .env file (JWT_SECRET, INTERNAL_KEY, SEED_PASSWORD); missing ones are made up.
Each program writes its log to the logs/ folder.
"""
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"


def load_env():
    env = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def main():
    if "--reset" in sys.argv:
        for p in ROOT.glob("cloudpulse.db*"):
            p.unlink()
        print("Local database deleted.")
    LOGS.mkdir(exist_ok=True)
    cfg = load_env()
    env = os.environ.copy()
    env["JWT_SECRET"] = cfg.get("JWT_SECRET") or env.get("JWT_SECRET") or "local-" + secrets.token_hex(16)
    env["INTERNAL_KEY"] = cfg.get("INTERNAL_KEY") or env.get("INTERNAL_KEY") or "local-" + secrets.token_hex(16)
    env["SEED_PASSWORD"] = cfg.get("SEED_PASSWORD") or env.get("SEED_PASSWORD") or "Demo12345"
    env["DATABASE_URL"] = "sqlite:///" + (ROOT / "cloudpulse.db").as_posix()
    env["PYTHONUNBUFFERED"] = "1"
    for k in ("SQS_QUEUE_URL", "SNS_TOPIC_ARN", "S3_BUCKET"):
        env[k] = ""          # no AWS when running locally
    py = sys.executable

    def uv(folder, module, port):
        return [py, "-m", "uvicorn", f"{module}.main:app", "--app-dir", f"services/{folder}",
                "--host", "127.0.0.1", "--port", str(port)]

    programs = [
        ("auth", uv("auth-service", "auth_svc", 8004)),
        ("metrics", uv("metrics-service", "metrics_svc", 8001)),
        ("incident", uv("incident-service", "incident_svc", 8002)),
        ("remediation", uv("remediation-service", "remediation_svc", 8003)),
    ]
    procs = []
    try:
        for name, cmd in programs:
            log = open(LOGS / f"{name}.log", "w")
            procs.append(subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT))
        print("Waiting for the four services...")
        for port in (8004, 8001, 8002, 8003):
            for _ in range(60):
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise SystemExit(f"Service on port {port} did not start. Open the logs/ folder and read the newest log.")
        for name, cmd in [
            ("simulator", [py, "-u", "data/simulator.py"]),
            ("dashboard", [py, "-m", "streamlit", "run", "dashboard/app.py", "--server.port=8501",
                           "--server.address=127.0.0.1", "--browser.gatherUsageStats=false",
                           "--server.headless=true"]),
        ]:
            log = open(LOGS / f"{name}.log", "w")
            procs.append(subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT))
        print("\nAll running. Open  http://localhost:8501  and log in as developer@cloudpulse.local")
        print(f"Password: {env['SEED_PASSWORD']}")
        print("Press Ctrl+C in this window to stop everything.\n")
        while True:
            time.sleep(2)
            dead = [p for p in procs if p.poll() is not None]
            if dead:
                print("A program stopped. Check the logs/ folder.")
                break
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
        print("Stopped.")


if __name__ == "__main__":
    main()
