"""Test fixtures. Assumes the docker-compose `postgres` service (pgvector/
pgvector:pg16) is already running and reachable at localhost:5432 with the
credentials in docker-compose.yml — CI starts it before pytest, see
.github/workflows/ci.yml. Locally: `docker compose up -d postgres`.

The test DB gets a fresh copy of sql/00_schema.sql + the refresh_tokens
migration once at the start of the session (schema setup cost paid once, not
per test). Tests that go through the `client` fixture commit real rows to
that shared database, so test functions use distinct emails/data to avoid
colliding with each other rather than relying on per-test rollback. The
`db_session` fixture is available separately for callers that do want a
session they roll back themselves."""

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://foodlence:foodlence@localhost:5432/foodlence")
os.environ.setdefault("DATABASE_URL_DIRECT", os.environ["DATABASE_URL"])
os.environ.setdefault("ADMIN_DATABASE_URL", os.environ["DATABASE_URL"])
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_SESSION_SECRET", "test-session-secret")
os.environ.setdefault("CORS_ORIGINS", "http://testserver")
os.environ.setdefault("ENABLE_SEMANTIC_MATCH", "false")

ROOT = Path(__file__).resolve().parent.parent

from app.core.dsn import to_asyncpg_dsn  # noqa: E402

RAW_DSN = to_asyncpg_dsn(os.environ["DATABASE_URL"])

# Safety net: _reset_schema() runs DROP SCHEMA ... CASCADE. Never let that
# point at the live Neon database, no matter what DATABASE_URL is set to.
if "neon.tech" in RAW_DSN:
    raise RuntimeError(
        "Refusing to run the test suite against a Neon database - the schema "
        "fixture runs 'DROP SCHEMA kb, app, audit CASCADE'. Unset DATABASE_URL "
        "(the suite then defaults to the local docker-compose Postgres) or set "
        "it to a throwaway database."
    )


async def _reset_schema() -> None:
    conn = await asyncpg.connect(RAW_DSN)
    try:
        await conn.execute("DROP SCHEMA IF EXISTS kb, app, audit CASCADE")
        schema_sql = (ROOT / "sql" / "00_schema.sql").read_text(encoding="utf-8")
        await conn.execute(schema_sql)
        migration_sql = (ROOT / "sql" / "migrations" / "0001_refresh_tokens.sql").read_text(encoding="utf-8")
        await conn.execute(migration_sql)
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    # asyncio.run() (not get_event_loop().run_until_complete()) so this
    # bootstrap uses — and fully closes — its own loop on Python 3.13,
    # instead of leaving a lingering deprecated loop behind.
    asyncio.run(_reset_schema())
    yield


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engines_between_tests():
    """pytest-asyncio (auto mode) runs each async test on its own event
    loop. SQLAlchemy's async engine pools connections, so without this the
    second test is handed an asyncpg connection opened on the first test's
    now-closed loop -> `RuntimeError: Event loop is closed` in do_ping
    (pool_pre_ping) and a cascade of AttributeErrors. Disposing after every
    test forces each one to open its own connections on its own loop."""
    yield
    from app.core.db import admin_engine, engine

    await engine.dispose()
    await admin_engine.dispose()


@pytest_asyncio.fixture
async def db_session():
    from app.core.db import SessionLocal

    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client():
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def raw_conn():
    conn = await asyncpg.connect(RAW_DSN)
    try:
        yield conn
    finally:
        await conn.close()
