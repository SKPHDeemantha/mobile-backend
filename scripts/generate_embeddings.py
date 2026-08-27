"""Backfills kb.ingredient_embeddings for ingredients that have none yet, or
whose embedding was flagged is_stale by the kb.fn_invalidate_embedding
trigger (fires when canonical_name changes — see sql/00_schema.sql 10.3).

Only meaningful once ENABLE_SEMANTIC_MATCH=true (see README "Turning on
semantic matching") — pointless to run before that, since Stage 4 of
kb.fn_match_ingredient is never reached while the API always passes a NULL
embedding.

Usage: python scripts/generate_embeddings.py
Reads DATABASE_URL_DIRECT from the environment. Must run against the DIRECT
endpoint — this does a bulk read+write pass, not per-request traffic.
"""

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.dsn import to_asyncpg_dsn  # noqa: E402

MODEL_NAME = "all-MiniLM-L6-v2"  # must match app/services/embeddings.py
MODEL_VERSION = "1.0"


def _format_vector(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"


async def main() -> None:
    url = os.environ.get("DATABASE_URL_DIRECT")
    if not url:
        print("ERROR: set DATABASE_URL_DIRECT", file=sys.stderr)
        sys.exit(1)
    dsn = to_asyncpg_dsn(url)

    # Imported lazily: torch + sentence-transformers are a heavy, optional
    # dependency (see requirements.txt comment) — no reason to require them
    # just to import this module.
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME)

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT i.ingredient_id, i.canonical_name
            FROM kb.ingredients i
            LEFT JOIN kb.ingredient_embeddings e
                   ON e.ingredient_id = i.ingredient_id
                  AND e.model_name = $1 AND e.model_version = $2
            WHERE i.is_active AND (e.ingredient_id IS NULL OR e.is_stale)
            """,
            MODEL_NAME,
            MODEL_VERSION,
        )
        print(f"{len(rows)} ingredients need an embedding")

        for row in rows:
            vector = model.encode(row["canonical_name"], normalize_embeddings=True).tolist()
            await conn.execute(
                """
                INSERT INTO kb.ingredient_embeddings (ingredient_id, model_name, model_version, embedding, is_stale)
                VALUES ($1, $2, $3, $4::vector, false)
                ON CONFLICT (ingredient_id, model_name, model_version)
                    DO UPDATE SET embedding = EXCLUDED.embedding, is_stale = false, generated_at = now()
                """,
                row["ingredient_id"],
                MODEL_NAME,
                MODEL_VERSION,
                _format_vector(vector),
            )

        print("Done.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
