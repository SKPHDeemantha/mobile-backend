"""Unit tests for app/admin/auth_backend.py — the SQLAdmin login gate must
reject anyone without the ADMIN role, even with a correct password, and
must never accept a non-existent/incorrect login."""

import pytest

from app.admin.auth_backend import AdminAuth
from app.core.security import hash_password

pytestmark = pytest.mark.asyncio


class _FakeRequest:
    def __init__(self, form_data: dict):
        self._form_data = form_data
        self.session: dict = {}

    async def form(self):
        return self._form_data


async def test_login_rejects_unknown_email():
    backend = AdminAuth(secret_key="test")
    request = _FakeRequest({"username": "nobody@example.com", "password": "whatever"})
    assert await backend.login(request) is False


async def test_login_rejects_regular_user_without_admin_role(raw_conn):
    email = "plain-user@example.com"
    await raw_conn.execute(
        "INSERT INTO app.users (user_id, email, password_hash, display_name) VALUES (gen_random_uuid(), $1, $2, 'Plain User')",
        email,
        hash_password("correct horse battery"),
    )

    backend = AdminAuth(secret_key="test")
    request = _FakeRequest({"username": email, "password": "correct horse battery"})
    assert await backend.login(request) is False
    assert "admin_user_id" not in request.session


async def test_login_accepts_user_with_admin_role(raw_conn):
    email = "admin-user@example.com"
    user_id = await raw_conn.fetchval(
        "INSERT INTO app.users (user_id, email, password_hash, display_name) VALUES (gen_random_uuid(), $1, $2, 'Admin User') RETURNING user_id",
        email,
        hash_password("correct horse battery"),
    )
    admin_role_id = await raw_conn.fetchval("SELECT role_id FROM app.roles WHERE code = 'ADMIN'")
    await raw_conn.execute("INSERT INTO app.user_roles (user_id, role_id) VALUES ($1, $2)", user_id, admin_role_id)

    backend = AdminAuth(secret_key="test")
    request = _FakeRequest({"username": email, "password": "correct horse battery"})
    assert await backend.login(request) is True
    assert request.session["admin_user_id"] == str(user_id)


async def test_login_rejects_wrong_password_even_for_admin(raw_conn):
    email = "admin-wrongpass@example.com"
    user_id = await raw_conn.fetchval(
        "INSERT INTO app.users (user_id, email, password_hash, display_name) VALUES (gen_random_uuid(), $1, $2, 'Admin User 2') RETURNING user_id",
        email,
        hash_password("correct horse battery"),
    )
    admin_role_id = await raw_conn.fetchval("SELECT role_id FROM app.roles WHERE code = 'ADMIN'")
    await raw_conn.execute("INSERT INTO app.user_roles (user_id, role_id) VALUES ($1, $2)", user_id, admin_role_id)

    backend = AdminAuth(secret_key="test")
    request = _FakeRequest({"username": email, "password": "not the right password"})
    assert await backend.login(request) is False
