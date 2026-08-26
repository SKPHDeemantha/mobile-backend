import secrets
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _pwd_context.verify(plain_password, password_hash)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: uuid.UUID, role_codes: list[str]) -> str:
    payload = {
        "sub": str(user_id),
        "roles": role_codes,
        "type": "access",
        "iat": _now(),
        "exp": _now() + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: uuid.UUID) -> tuple[str, uuid.UUID, datetime]:
    """Returns (token, jti, expires_at). The caller persists (jti, user_id,
    expires_at) into app.refresh_tokens — the JWT signature alone is not
    enough to allow revocation on logout."""
    jti = uuid.uuid4()
    expires_at = _now() + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": str(user_id),
        "jti": str(jti),
        "type": "refresh",
        "iat": _now(),
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti, expires_at


def generate_numeric_code(digits: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(digits))


def create_purpose_token(user_id: uuid.UUID, purpose: str, minutes: int, code: str) -> str:
    """Stateless signed 'challenge' for email-verification / password-reset.
    No DB row needed: the code is emailed to the user, this signed token is
    handed straight back to the client in the API response, and the client
    submits BOTH together. The server just checks the code inside the token
    matches what the user typed, and that purpose/expiry/signature hold."""
    payload = {
        "sub": str(user_id),
        "purpose": purpose,
        "code": code,
        "iat": _now(),
        "exp": _now() + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Raises jose.JWTError on any invalid/expired/tampered token."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


__all__ = [
    "JWTError",
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "generate_numeric_code",
    "create_purpose_token",
    "decode_token",
]
