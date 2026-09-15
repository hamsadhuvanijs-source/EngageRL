"""Auth flow + cross-user isolation. Uses TestClient against the same isolated test DB the
rest of the suite uses (conftest points DATABASE_URL at it before app import, and resets the
schema per test)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient, email: str, password: str = "hunter2!pw") -> str:
    res = client.post("/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201, res.text
    return res.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_register_returns_token_and_user(client: TestClient):
    res = client.post("/auth/register", json={"email": "A@Example.com", "password": "hunter2!pw"})
    assert res.status_code == 201
    body = res.json()
    assert body["token"]
    assert body["user"]["email"] == "a@example.com"  # normalized


def test_register_rejects_duplicate_email(client: TestClient):
    _register(client, "dupe@example.com")
    res = client.post("/auth/register", json={"email": "dupe@example.com", "password": "hunter2!pw"})
    assert res.status_code == 409


def test_register_rejects_short_password(client: TestClient):
    res = client.post("/auth/register", json={"email": "x@example.com", "password": "short"})
    assert res.status_code == 422


def test_login_good_and_bad_password(client: TestClient):
    _register(client, "login@example.com", "correct-horse")
    ok = client.post("/auth/login", json={"email": "login@example.com", "password": "correct-horse"})
    assert ok.status_code == 200 and ok.json()["token"]

    bad = client.post("/auth/login", json={"email": "login@example.com", "password": "nope"})
    assert bad.status_code == 401


def test_me_requires_valid_token(client: TestClient):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers=_auth("garbage")).status_code == 401

    token = _register(client, "me@example.com")
    res = client.get("/auth/me", headers=_auth(token))
    assert res.status_code == 200 and res.json()["email"] == "me@example.com"


def test_logout_revokes_token(client: TestClient):
    token = _register(client, "bye@example.com")
    assert client.post("/auth/logout", headers=_auth(token)).status_code == 204
    assert client.get("/auth/me", headers=_auth(token)).status_code == 401


def test_unauthenticated_endpoints_401(client: TestClient):
    assert client.get("/chats").status_code == 401
    assert client.get("/stats").status_code == 401
    assert client.post("/chats").status_code == 401


def test_chats_are_isolated_per_user(client: TestClient):
    token_a = _register(client, "owner@example.com")
    token_b = _register(client, "intruder@example.com")

    chat_id = client.post("/chats", headers=_auth(token_a)).json()["id"]

    # A sees the chat, B does not
    assert [c["id"] for c in client.get("/chats", headers=_auth(token_a)).json()] == [chat_id]
    assert client.get("/chats", headers=_auth(token_b)).json() == []

    # B cannot read A's chat by id
    assert client.get(f"/chats/{chat_id}", headers=_auth(token_b)).status_code == 403
    assert client.get(f"/chats/{chat_id}", headers=_auth(token_a)).status_code == 200
