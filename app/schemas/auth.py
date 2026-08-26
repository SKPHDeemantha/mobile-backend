import uuid

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=150)
    preferred_language: str = Field(default="en", max_length=5)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class VerifyEmailRequest(BaseModel):
    challenge: str
    code: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    # Client must hold onto this and send it back with the code the user
    # receives by email — see app/core/security.py create_purpose_token().
    reset_challenge: str


class ResetPasswordRequest(BaseModel):
    reset_challenge: str
    code: str
    new_password: str = Field(min_length=8, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    display_name: str
    preferred_language: str
    email_verified: bool
    roles: list[str]


class AuthResponse(BaseModel):
    tokens: TokenPair
    user: UserOut
    # Present only on register: client holds this and pairs it with the
    # code the user receives by email to call /auth/verify-email.
    verification_challenge: str | None = None
