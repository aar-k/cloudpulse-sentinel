import pytest
from fastapi.testclient import TestClient
from helpers import auth

from auth_svc import main as authmod


@pytest.fixture(scope="module")
def client():
    with TestClient(authmod.app) as c:      # startup creates tables and seeds 4 demo users
        yield c


def login(client, email, password="Demo12345"):
    return client.post("/login", json={"email": email, "password": password})


def test_password_hashing_roundtrip():
    h = authmod.hash_password("S3cret-pass")
    assert h.startswith("scrypt$") and "S3cret-pass" not in h
    assert authmod.verify_password("S3cret-pass", h)
    assert not authmod.verify_password("wrong", h)
    assert not authmod.verify_password("x", "garbage")


def test_seeded_users_can_log_in_with_their_roles(client):
    expected = {"admin@cloudpulse.local": "admin", "analyst@cloudpulse.local": "analyst",
                "developer@cloudpulse.local": "developer", "viewer@cloudpulse.local": "readonly"}
    for email, role in expected.items():
        r = login(client, email)
        assert r.status_code == 200 and r.json()["role"] == role
        me = client.get("/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
        assert me["role"] == role and me["email"] == email


def test_wrong_password_and_unknown_user_are_rejected_the_same_way(client):
    a = login(client, "admin@cloudpulse.local", "nope")
    b = login(client, "ghost@cloudpulse.local")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_only_admin_can_list_and_create_users(client):
    assert client.get("/users", headers=auth("analyst")).status_code == 403
    assert client.get("/users").status_code == 401
    assert len(client.get("/users", headers=auth("admin")).json()) >= 4
    new = {"name": "New Dev", "email": "New.Dev@cloudpulse.local", "password": "LongEnough1", "role": "developer"}
    assert client.post("/users", json=new, headers=auth("admin")).status_code == 201
    assert login(client, "new.dev@cloudpulse.local", "LongEnough1").status_code == 200
    assert client.post("/users", json=new, headers=auth("admin")).status_code == 409


def test_create_user_validates_role_and_password(client):
    bad_role = {"name": "X", "email": "x@x.io", "password": "LongEnough1", "role": "superuser"}
    assert client.post("/users", json=bad_role, headers=auth("admin")).status_code == 400
    short = {"name": "X", "email": "y@x.io", "password": "short", "role": "readonly"}
    assert client.post("/users", json=short, headers=auth("admin")).status_code == 422


def test_expired_token_is_rejected(client):
    from helpers import token
    expired = token("admin", hours=-1)
    assert client.get("/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
