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
RAW_DSN = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)


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
    asyncio.get_event_loop().run_until_complete(_reset_schema())
    yield


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
