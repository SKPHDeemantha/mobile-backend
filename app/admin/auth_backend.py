from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import select
from starlette.requests import Request

from app.core.db import AdminSessionLocal
from app.core.security import verify_password
from app.models.domain import roles, user_roles, users


class AdminAuth(AuthenticationBackend):
    """Session-cookie login for the /admin panel — deliberately separate
    from the mobile app's JWT flow. Uses the app_admin-scoped connection
    (never the Neon owner role) and requires the ADMIN role in app.user_roles,
    not just a valid account."""

    async def login(self, request: Request) -> bool:
        form = await request.form()
        email = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))
        if not email or not password:
            return False

        async with AdminSessionLocal() as db:
            row = (await db.execute(select(users).where(users.c.email == email))).first()
            if row is None or not row.is_active or not verify_password(password, row.password_hash):
                return False

            role_result = await db.execute(
                select(roles.c.code)
                .select_from(user_roles.join(roles, user_roles.c.role_id == roles.c.role_id))
                .where(user_roles.c.user_id == row.user_id)
            )
            role_codes = {r[0] for r in role_result.all()}
            if "ADMIN" not in role_codes:
                return False

        request.session["admin_user_id"] = str(row.user_id)
        request.session["admin_email"] = email
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("admin_user_id"))
