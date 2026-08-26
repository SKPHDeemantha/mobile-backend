import pytest

pytestmark = pytest.mark.asyncio


async def test_register_login_me(client):
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "correct horse battery", "display_name": "Alice"},
    )
    assert register.status_code == 201
    body = register.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["roles"] == ["USER"]
    assert body["user"]["email_verified"] is False
    assert body["verification_challenge"]

    access_token = body["tokens"]["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"

    login = await client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "correct horse battery"})
    assert login.status_code == 200

    bad_login = await client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "wrong"})
    assert bad_login.status_code == 401


async def test_duplicate_registration_rejected(client):
    payload = {"email": "bob@example.com", "password": "correct horse battery", "display_name": "Bob"}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


async def test_refresh_rotates_and_revokes_old_token(client):
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "carol@example.com", "password": "correct horse battery", "display_name": "Carol"},
    )
    old_refresh = register.json()["tokens"]["refresh_token"]

    refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != old_refresh

    reused = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert reused.status_code == 401


async def test_verify_email_with_correct_and_incorrect_code(client, monkeypatch):
    # The 6-digit code is only ever emailed, never stored server-side (see
    # app/core/security.py create_purpose_token) — so to test the success
    # path we intercept the "send" call instead of the database.
    sent = {}

    async def _fake_send(to_email: str, code: str) -> None:
        sent["code"] = code

    monkeypatch.setattr("app.api.v1.auth.send_verification_email", _fake_send)

    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "dave@example.com", "password": "correct horse battery", "display_name": "Dave"},
    )
    challenge = register.json()["verification_challenge"]
    assert sent["code"]

    wrong = await client.post("/api/v1/auth/verify-email", json={"challenge": challenge, "code": "000000"})
    assert wrong.status_code == 400

    correct = await client.post("/api/v1/auth/verify-email", json={"challenge": challenge, "code": sent["code"]})
    assert correct.status_code == 200
    assert correct.json()["email_verified"] is True


async def test_logout_revokes_refresh_token(client):
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "erin@example.com", "password": "correct horse battery", "display_name": "Erin"},
    )
    refresh_token = register.json()["tokens"]["refresh_token"]

    logout = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout.status_code == 204

    reused = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert reused.status_code == 401
