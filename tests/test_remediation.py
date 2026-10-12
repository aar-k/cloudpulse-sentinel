import pytest
from fastapi.testclient import TestClient
from helpers import auth, internal

from remediation_svc import main as rem


@pytest.fixture(scope="module")
def client():
    with TestClient(rem.app) as c:      # 'with' runs the startup step that creates the tables
        yield c


def recommend(client, incident_id="INC-T-001", service="demo-svc", signals=("cpu",)):
    return client.post("/remediations/recommend", headers=internal(), json={
        "incident_id": incident_id, "service": service, "top_signals": list(signals)}).json()


def test_full_safe_flow(client):
    r = recommend(client, "INC-T-001", "demo-svc")
    assert r["status"] == "recommended" and r["action"] == "scale_service"
    rid = r["id"]
    client.post("/demo/fault", json={"service": "demo-svc", "on": True}, headers=auth("developer"))
    assert client.get("/demo/state/demo-svc", headers=auth("readonly")).json()["fault"] is True

    assert client.post(f"/remediations/{rid}/approve", headers=auth("analyst", "Ana")).status_code == 200
    assert client.post(f"/remediations/{rid}/execute", headers=auth("analyst", "Ana")).json()["status"] == "executed"
    assert client.get("/demo/state/demo-svc", headers=auth("readonly")).json()["fault"] is False

    client.post("/remediations/verify/INC-T-001", headers=internal())
    row = client.get("/remediations", params={"incident_id": "INC-T-001"}, headers=auth("readonly")).json()[0]
    assert row["approved_by"] == "Ana" and row["executed_at"] and row["verified"] is True


def test_approver_name_comes_from_the_login_not_the_request(client):
    rid = recommend(client, "INC-T-004", "demo-4")["id"]
    client.post(f"/remediations/{rid}/approve", headers=auth("admin", "Real Admin"),
                json={"approved_by": "someone else"})
    row = client.get("/remediations", params={"incident_id": "INC-T-004"}, headers=auth("admin")).json()[0]
    assert row["approved_by"] == "Real Admin"


def test_cannot_execute_without_approval(client):
    rid = recommend(client, "INC-T-002", "demo-2")["id"]
    assert client.post(f"/remediations/{rid}/execute", headers=auth("admin")).status_code == 409


def test_readonly_and_developer_cannot_approve(client):
    rid = recommend(client, "INC-T-003", "demo-3")["id"]
    assert client.post(f"/remediations/{rid}/approve", headers=auth("readonly")).status_code == 403
    assert client.post(f"/remediations/{rid}/approve", headers=auth("developer")).status_code == 403


def test_not_logged_in_cannot_approve(client):
    rid = recommend(client, "INC-T-005", "demo-5")["id"]
    assert client.post(f"/remediations/{rid}/approve").status_code == 401


def test_only_services_can_create_recommendations(client):
    r = client.post("/remediations/recommend", headers=auth("analyst"),
                    json={"incident_id": "INC-T-006", "service": "x", "top_signals": []})
    assert r.status_code == 403


def test_policy_blocks_unlisted_action(client):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        rem.policy_check("delete_database")
