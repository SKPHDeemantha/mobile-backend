from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.dsn import sanitize_pg_url, wants_ssl

settings = get_settings()

# NOTE: Neon's pooled endpoint runs PgBouncer in transaction-pooling mode.
# asyncpg's server-side prepared statement cache is per-physical-connection,
# but under transaction pooling a "connection" can hop between different
# backend sockets between statements, so a cached prepared statement can
# silently point at the wrong backend. statement_cache_size=0 disables that
# cache — required for correctness against the pooled endpoint, not just a
# performance tweak.
#
# ssl=True is passed explicitly (only when the original URL asked for it via
# sslmode=require, e.g. every Neon URL — never for the unencrypted local
# docker-compose Postgres used by tests) rather than left as a
# "?sslmode=require" query parameter: SQLAlchemy's asyncpg dialect forwards
# URL query params straight through as connect() keyword arguments, and
# asyncpg.connect() has no 'sslmode' parameter (only 'ssl') — see
# app/core/dsn.py for the confirmed-live error this avoids.
def _connect_args(url: str) -> dict:
    args: dict = {"statement_cache_size": 0}
    if wants_ssl(url):
        args["ssl"] = True
    return args


engine: AsyncEngine = create_async_engine(
    sanitize_pg_url(settings.database_url),
    pool_pre_ping=True,
    connect_args=_connect_args(settings.database_url),
)

admin_engine: AsyncEngine = create_async_engine(
    sanitize_pg_url(settings.admin_database_url),
    pool_pre_ping=True,
    connect_args=_connect_args(settings.admin_database_url),
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
AdminSessionLocal = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def get_admin_db() -> AsyncIterator[AsyncSession]:
    """For the small number of request-path operations that need app_admin
    privileges rather than app_api — currently only the materialized-view
    refresh in api/v1/sync.py, since REFRESH MATERIALIZED VIEW requires
    ownership of the view (see sql/01_roles_and_grants.sql, which transfers
    kb.mv_allergen_lookup's ownership to app_admin) and app_api is
    deliberately not granted that."""
    async with AdminSessionLocal() as session:
        yield session
