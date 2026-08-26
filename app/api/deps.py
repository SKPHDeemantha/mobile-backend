import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import JWTError, decode_token

# auto_error=False so guest-allowed endpoints can inspect "was a token even
# sent" without FastAPI short-circuiting to a 403 first.
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    roles: list[str]

    def has_role(self, code: str) -> bool:
        return code in self.roles


def _decode_access_token(token: str) -> CurrentUser:
    try:
        payload = decode_token(token)
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not an access token")

    return CurrentUser(user_id=uuid.UUID(payload["sub"]), roles=payload.get("roles", []))


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return _decode_access_token(credentials.credentials)


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser | None:
    """For endpoints that support guest access (e.g. POST /scans) — the
    schema's app.scans.user_id is nullable by design, guest use is a
    first-class case, not an afterthought."""
    if credentials is None:
        return None
    return _decode_access_token(credentials.credentials)


def require_role(role_code: str):
    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(role_code):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires the {role_code} role")
        return user

    return _check
