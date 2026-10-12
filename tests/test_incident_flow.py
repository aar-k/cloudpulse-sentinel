import pytest
from fastapi.testclient import TestClient
from helpers import auth, internal

from incident_svc import main as inc


@pytest.fixture(scope="module")
def client():
    with TestClient(inc.app) as c:      # 'with' runs the startup step that creates the tables
        yield c


GOOD = dict(cpu=35, memory=50, latency_ms=120, error_rate=0.5, request_count=100)
BAD = dict(cpu=95, memory=85, latency_ms=900, error_rate=9, request_count=220)


def post(client, service, m):
    return client.post("/evaluate", json={"service": service, **m}, headers=internal()).json()


def test_healthy_metrics_make_no_incident(client):
    r = post(client, "svc-healthy", GOOD)
    assert r["severity"] == "Low" and r["incident_id"] is None


def test_fault_opens_exactly_one_incident_and_timeline(client):
    first = post(client, "svc-a", BAD)
    assert first["action"] == "incident_created"
    second = post(client, "svc-a", BAD)                       # same fault again: no duplicate incident
    assert second["incident_id"] == first["incident_id"]
    assert second["action"] == "incident_ongoing"
    replay = client.get(f"/incidents/{first['incident_id']}/replay", headers=auth("readonly")).json()
    types = [e["event_type"] for e in replay["events"]]
    for needed in ("anomaly_detected", "ml_score_recorded", "incident_created", "alert_generated"):
        assert needed in types


def test_incident_resolves_after_normal_samples(client):
    inc_id = post(client, "svc-b", BAD)["incident_id"]
    actions = [post(client, "svc-b", GOOD)["action"] for _ in range(3)]
    assert actions[-1] == "incident_resolved"
    replay = client.get(f"/incidents/{inc_id}/replay", headers=auth("readonly")).json()
    assert replay["incident"]["status"] == "resolved"
    assert "metrics_normalized" in [e["event_type"] for e in replay["events"]]


def test_ml_predict_endpoint_shape(client):
    r = client.post("/predict", json={"service": "x", **BAD}, headers=auth("analyst")).json()
    assert set(r) == {"service", "anomaly", "anomaly_score", "signals"}
    assert r["anomaly"] is True and r["signals"]
    ok = client.post("/predict", json={"service": "x", **GOOD}, headers=auth("analyst")).json()
    assert ok["anomaly"] is False


def test_idle_batch_worker_is_not_an_incident(client):
    idle = dict(cpu=6, memory=28, latency_ms=110, error_rate=0.4, request_count=100)
    assert post(client, "batch-test", idle)["incident_id"] is None


def test_validation_rejects_bad_input(client):
    bad = {"service": "x", **GOOD, "cpu": 400}
    assert client.post("/evaluate", json=bad, headers=internal()).status_code == 422


# ---------- login / roles ----------
def test_no_login_is_rejected(client):
    assert client.get("/incidents").status_code == 401
    assert client.post("/evaluate", json={"service": "x", **GOOD}).status_code == 401


def test_bad_token_is_rejected(client):
    assert client.get("/incidents", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_readonly_cannot_resolve_but_analyst_can(client):
    inc_id = post(client, "svc-c", BAD)["incident_id"]
    assert client.post(f"/incidents/{inc_id}/resolve", headers=auth("readonly")).status_code == 403
    r = client.post(f"/incidents/{inc_id}/resolve", headers=auth("analyst", "Ana"))
    assert r.status_code == 200


def test_readonly_cannot_push_metrics_into_evaluate(client):
    r = client.post("/evaluate", json={"service": "x", **GOOD}, headers=auth("readonly"))
    assert r.status_code == 403


# ---------- alerts via SQS ----------
def test_notify_sends_incident_to_sqs(client, monkeypatch):
    class FakeSQS:
        def __init__(self):
            self.sent = []

        def send_message(self, **kw):
            self.sent.append(kw)

    monkeypatch.setattr(inc, "SQS_QUEUE_URL", "https://sqs.example/queue")
    fake = FakeSQS()
    inc.notify({"id": "INC-1", "service": "s", "severity": "High", "risk_score": 70}, sqs_client=fake)
    assert fake.sent[0]["QueueUrl"] == "https://sqs.example/queue"
    assert '"INC-1"' in fake.sent[0]["MessageBody"]
    assert "SQS" in inc.alert_channel()


def test_notify_never_crashes_when_sqs_fails(monkeypatch):
    class Broken:
        def send_message(self, **kw):
            raise RuntimeError("queue gone")

    monkeypatch.setattr(inc, "SQS_QUEUE_URL", "https://sqs.example/queue")
    inc.notify({"id": "INC-2", "service": "s", "severity": "High", "risk_score": 70}, sqs_client=Broken())
