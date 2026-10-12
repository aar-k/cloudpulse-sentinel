from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from helpers import auth, internal
from sqlalchemy import insert

from metrics_svc import main as met
from metrics_svc.analytics import waste_report
from metrics_svc.db import utcnow


@pytest.fixture(scope="module")
def client():
    with TestClient(met.app) as c:      # 'with' runs the startup step that creates the tables
        yield c


M = dict(service="m-svc", cpu=30, memory=40, latency_ms=100, error_rate=0.2, request_count=90)


def test_ingest_and_read_back(client):
    assert client.post("/metrics", json=M, headers=internal()).status_code == 200   # incident-service down: still OK
    rows = client.get("/metrics/m-svc", headers=auth("readonly")).json()
    assert rows and rows[-1]["cpu"] == 30


def test_metrics_need_login(client):
    assert client.post("/metrics", json=M).status_code == 401
    assert client.get("/metrics/m-svc").status_code == 401
    assert client.post("/metrics", json=M, headers=auth("readonly")).status_code == 403


def test_s3_batch_upload_uses_client():
    class FakeS3:
        def __init__(self):
            self.calls = []

        def put_object(self, **kw):
            self.calls.append(kw)

    met.S3_BUCKET = "test-bucket"
    met._buffer.clear()
    met._buffer.extend([{"a": 1}, {"a": 2}])
    fake = FakeS3()
    assert met.flush_to_s3(fake) == 2
    assert fake.calls[0]["Bucket"] == "test-bucket"
    assert fake.calls[0]["Key"].startswith("raw-metrics/")
    met.S3_BUCKET = ""


def test_waste_report_flags_idle_service_and_not_busy_one(client):
    now = utcnow()
    with met.engine.begin() as conn:
        for i in range(30):
            ts = now - timedelta(minutes=i)
            conn.execute(insert(met.metrics).values(service="idle-svc", ts=ts, cpu=5, memory=25,
                                                    latency_ms=100, error_rate=0.1, request_count=90))
            conn.execute(insert(met.metrics).values(service="busy-svc", ts=ts, cpu=60, memory=70,
                                                    latency_ms=100, error_rate=0.1, request_count=90))
        conn.execute(insert(met.metrics).values(service="new-svc", ts=now, cpu=2, memory=10,
                                                latency_ms=100, error_rate=0.1, request_count=90))
    with met.engine.connect() as conn:
        report = {r["service"]: r for r in waste_report(conn, met.metrics)}
    assert report["idle-svc"]["underutilized"] is True
    assert report["idle-svc"]["estimated_monthly_saving_usd"] > 0
    assert "Average CPU" in report["idle-svc"]["reason"]
    assert report["busy-svc"]["underutilized"] is False
    assert report["new-svc"]["underutilized"] is False         # too few samples to judge
    r = client.get("/analytics/waste", headers=auth("readonly"))
    assert r.status_code == 200 and r.json()[0]["service"] == "idle-svc"
