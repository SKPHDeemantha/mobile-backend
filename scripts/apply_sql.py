"""Applies one or more .sql files against the DIRECT database endpoint.

Usage:
    python scripts/apply_sql.py sql/00_schema.sql
    python scripts/apply_sql.py sql/01_roles_and_grants.sql
    python scripts/apply_sql.py sql/migrations/0001_refresh_tokens.sql

Reads DATABASE_URL_DIRECT from the environment (or .env, via python-dotenv
if installed) unless --url is given explicitly. Deliberately NOT Alembic —
see mobile-backend/README.md "Why not Alembic" for the reasoning. Migration
files under sql/migrations/ are append-only: never edit one that has already
been applied to a real environment, add a new numbered file instead.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.dsn import to_asyncpg_dsn  # noqa: E402


async def apply_file(dsn: str, path: str) -> None:
    with open(path, encoding="utf-8") as f:
        sql = f.read()

    conn = await asyncpg.connect(dsn)
    try:
        print(f"Applying {path} ...")
        await conn.execute(sql)
        print(f"OK: {path}")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="One or more .sql files, applied in order")
    parser.add_argument("--url", default=None, help="Override DATABASE_URL_DIRECT")
    args = parser.parse_args()

    url = args.url or os.environ.get("DATABASE_URL_DIRECT")
    if not url:
        print("ERROR: set DATABASE_URL_DIRECT (or pass --url) — this must be the DIRECT, non-pooled Neon endpoint.", file=sys.stderr)
        sys.exit(1)

    dsn = to_asyncpg_dsn(url)
    for path in args.files:
        asyncio.run(apply_file(dsn, path))


if __name__ == "__main__":
    main()
