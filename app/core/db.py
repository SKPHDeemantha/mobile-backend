from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

# NOTE: Neon's pooled endpoint runs PgBouncer in transaction-pooling mode.
# asyncpg's server-side prepared statement cache is per-physical-connection,
# but under transaction pooling a "connection" can hop between different
# backend sockets between statements, so a cached prepared statement can
# silently point at the wrong backend. statement_cache_size=0 disables that
# cache — required for correctness against the pooled endpoint, not just a
# performance tweak.
engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"statement_cache_size": 0},
)

admin_engine: AsyncEngine = create_async_engine(
    settings.admin_database_url,
    pool_pre_ping=True,
    connect_args={"statement_cache_size": 0},
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
AdminSessionLocal = async_sessionmaker(admin_engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
