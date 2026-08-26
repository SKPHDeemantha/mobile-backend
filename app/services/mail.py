import logging
from functools import lru_cache

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@lru_cache
def _get_mailer() -> FastMail | None:
    if not settings.mail_username:
        return None
    # Constructed lazily and only once mail_username is confirmed present:
    # ConnectionConfig eagerly validates MAIL_FROM as a real email address,
    # which would crash at import time in any environment that hasn't
    # configured mail yet (local dev, tests, CI) if built at module scope.
    conf = ConnectionConfig(
        MAIL_USERNAME=settings.mail_username,
        MAIL_PASSWORD=settings.mail_password,
        MAIL_FROM=settings.mail_from or settings.mail_username,
        MAIL_PORT=settings.mail_port,
        MAIL_SERVER=settings.mail_server,
        MAIL_STARTTLS=True,
        MAIL_SSL_TLS=False,
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True,
    )
    return FastMail(conf)


async def send_verification_email(to_email: str, token: str) -> None:
    mailer = _get_mailer()
    if mailer is None:
        logger.warning("MAIL_USERNAME not configured — skipping verification email to %s (token=%s)", to_email, token)
        return
    message = MessageSchema(
        subject="Verify your FoodLence account",
        recipients=[to_email],
        body=(
            "Welcome to FoodLence.\n\n"
            f"Verification code: {token}\n\n"
            "Paste this code into the app to verify your email. It expires in 30 minutes."
        ),
        subtype=MessageType.plain,
    )
    await mailer.send_message(message)


async def send_password_reset_email(to_email: str, code: str) -> None:
    mailer = _get_mailer()
    if mailer is None:
        logger.warning("MAIL_USERNAME not configured — skipping reset email to %s (code=%s)", to_email, code)
        return
    message = MessageSchema(
        subject="Reset your FoodLence password",
        recipients=[to_email],
        body=(
            "A password reset was requested for your FoodLence account.\n\n"
            f"Reset code: {code}\n\n"
            "Enter this code in the app to choose a new password. It expires in 30 minutes. "
            "If you didn't request this, you can ignore this email."
        ),
        subtype=MessageType.plain,
    )
    await mailer.send_message(message)
