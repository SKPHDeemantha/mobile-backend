import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.core.security import (
    JWTError,
    create_access_token,
    create_purpose_token,
    create_refresh_token,
    decode_token,
    generate_numeric_code,
    hash_password,
    verify_password,
)
from app.models.domain import refresh_tokens, roles, user_roles, users
from app.schemas.auth import (
    AuthResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
    UserOut,
    VerifyEmailRequest,
)
from app.services.mail import send_password_reset_email, send_verification_email

router = APIRouter(prefix="/auth", tags=["auth"])

VERIFY_PURPOSE = "email_verify"
RESET_PURPOSE = "password_reset"
CHALLENGE_MINUTES = 30


async def _load_roles(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    result = await db.execute(
        select(roles.c.code).select_from(user_roles.join(roles, user_roles.c.role_id == roles.c.role_id)).where(user_roles.c.user_id == user_id)
    )
    return [row[0] for row in result.all()]


async def _issue_tokens(db: AsyncSession, user_id: uuid.UUID, role_codes: list[str]) -> TokenPair:
    access = create_access_token(user_id, role_codes)
    refresh, jti, expires_at = create_refresh_token(user_id)
    await db.execute(insert(refresh_tokens).values(token_id=jti, user_id=user_id, expires_at=expires_at))
    return TokenPair(access_token=access, refresh_token=refresh)


def _to_user_out(row, role_codes: list[str]) -> UserOut:
    return UserOut(
        user_id=row.user_id,
        email=row.email,
        display_name=row.display_name,
        preferred_language=row.preferred_language,
        email_verified=row.email_verified_at is not None,
        roles=role_codes,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    existing = await db.execute(select(users.c.user_id).where(users.c.email == body.email))
    if existing.first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    user_id = uuid.uuid4()
    await db.execute(
        insert(users).values(
            user_id=user_id,
            email=body.email,
            password_hash=hash_password(body.password),
            display_name=body.display_name,
            preferred_language=body.preferred_language,
        )
    )
    # Every new account gets the USER role. Only an existing admin can grant
    # ADMIN afterwards (via the SQLAdmin panel) — never self-service.
    user_role_id = await db.execute(select(roles.c.role_id).where(roles.c.code == "USER"))
    role_id = user_role_id.scalar_one()
    await db.execute(insert(user_roles).values(user_id=user_id, role_id=role_id))

    tokens = await _issue_tokens(db, user_id, ["USER"])

    code = generate_numeric_code()
    challenge = create_purpose_token(user_id, VERIFY_PURPOSE, CHALLENGE_MINUTES, code)
    await send_verification_email(body.email, code)

    await db.commit()

    row = (await db.execute(select(users).where(users.c.user_id == user_id))).one()
    return AuthResponse(tokens=tokens, user=_to_user_out(row, ["USER"]), verification_challenge=challenge)


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    row = (await db.execute(select(users).where(users.c.email == body.email))).first()
    if row is None or not verify_password(body.password, row.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not row.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated")

    role_codes = await _load_roles(db, row.user_id)
    tokens = await _issue_tokens(db, row.user_id, role_codes)
    await db.commit()

    return AuthResponse(tokens=tokens, user=_to_user_out(row, role_codes))


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    try:
        payload = decode_token(body.refresh_token)
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from exc
    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not a refresh token")

    jti = uuid.UUID(payload["jti"])
    user_id = uuid.UUID(payload["sub"])

    row = (await db.execute(select(refresh_tokens).where(refresh_tokens.c.token_id == jti))).first()
    if row is None or row.revoked_at is not None or row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token is no longer valid")

    role_codes = await _load_roles(db, user_id)
    access = create_access_token(user_id, role_codes)

    # Rotate: issue a new refresh token, revoke the old one, link them.
    new_refresh, new_jti, new_expires = create_refresh_token(user_id)
    await db.execute(insert(refresh_tokens).values(token_id=new_jti, user_id=user_id, expires_at=new_expires))
    await db.execute(
        update(refresh_tokens)
        .where(refresh_tokens.c.token_id == jti)
        .values(revoked_at=datetime.now(timezone.utc), replaced_by=new_jti)
    )
    await db.commit()

    return TokenPair(access_token=access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest, db: AsyncSession = Depends(get_db)) -> None:
    try:
        payload = decode_token(body.refresh_token)
        jti = uuid.UUID(payload["jti"])
    except (JWTError, KeyError, ValueError):
        # Logging out with an already-invalid token is not an error from the
        # client's point of view — the end state (logged out) is achieved.
        return None

    await db.execute(update(refresh_tokens).where(refresh_tokens.c.token_id == jti).values(revoked_at=datetime.now(timezone.utc)))
    await db.commit()
    return None


@router.post("/verify-email", response_model=UserOut)
async def verify_email(body: VerifyEmailRequest, db: AsyncSession = Depends(get_db)) -> UserOut:
    try:
        payload = decode_token(body.challenge)
    except JWTError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Verification challenge is invalid or has expired") from exc
    if payload.get("purpose") != VERIFY_PURPOSE or payload.get("code") != body.code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incorrect verification code")

    user_id = uuid.UUID(payload["sub"])
    await db.execute(update(users).where(users.c.user_id == user_id).values(email_verified_at=datetime.now(timezone.utc)))
    await db.commit()

    row = (await db.execute(select(users).where(users.c.user_id == user_id))).one()
    role_codes = await _load_roles(db, user_id)
    return _to_user_out(row, role_codes)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)) -> ForgotPasswordResponse:
    row = (await db.execute(select(users.c.user_id).where(users.c.email == body.email))).first()
    if row is None:
        # Do not reveal whether the email exists — return a challenge that
        # simply won't verify against anything, same response shape either way.
        dummy_challenge = create_purpose_token(uuid.uuid4(), RESET_PURPOSE, CHALLENGE_MINUTES, generate_numeric_code())
        return ForgotPasswordResponse(reset_challenge=dummy_challenge)

    code = generate_numeric_code()
    challenge = create_purpose_token(row.user_id, RESET_PURPOSE, CHALLENGE_MINUTES, code)
    await send_password_reset_email(body.email, code)
    return ForgotPasswordResponse(reset_challenge=challenge)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)) -> None:
    try:
        payload = decode_token(body.reset_challenge)
    except JWTError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reset challenge is invalid or has expired") from exc
    if payload.get("purpose") != RESET_PURPOSE or payload.get("code") != body.code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incorrect reset code")

    user_id = uuid.UUID(payload["sub"])
    await db.execute(update(users).where(users.c.user_id == user_id).values(password_hash=hash_password(body.new_password)))
    # A password reset invalidates every existing session on this account.
    await db.execute(
        update(refresh_tokens)
        .where(refresh_tokens.c.user_id == user_id, refresh_tokens.c.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return None


@router.get("/me", response_model=UserOut)
async def me(current=Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> UserOut:
    row = (await db.execute(select(users).where(users.c.user_id == current.user_id))).one()
    return _to_user_out(row, current.roles)
