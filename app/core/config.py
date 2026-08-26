from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database -----------------------------------------------------
    # Pooled endpoint, app_api role. Used for all normal request traffic.
    database_url: str
    # Direct (non-pooled) endpoint, app_api role. Migrations/backfills only
    # — never used by the request path.
    database_url_direct: str
    # Pooled endpoint, app_admin role. SQLAdmin only.
    admin_database_url: str

    # --- Auth -----------------------------------------------------------
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 20
    refresh_token_expire_days: int = 30
    admin_session_secret: str

    # --- CORS -------------------------------------------------------------
    cors_origins: str = "http://localhost"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # --- Mail --------------------------------------------------------------
    mail_username: str = ""
    mail_password: str = ""
    mail_from: str = ""
    mail_server: str = "smtp.gmail.com"
    mail_port: int = 587

    # --- Feature flags ---------------------------------------------------
    # Stage 4 (semantic/vector) matching needs sentence-transformers loaded
    # in memory (~90MB+ model). Keep off until hosting RAM is confirmed —
    # see README "Turning on semantic matching".
    enable_semantic_match: bool = False

    # --- Internal maintenance endpoints (GitHub Actions cron) -------------
    maintenance_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
