"""Thin wrapper around kb.fn_match_ingredient / kb.fn_log_unrecognised_term /
app.fn_scan_summary. The matching cascade, the profile-match flag, and the
result-shaping logic all live IN the database (see sql/00_schema.sql SECTION
9) — this module deliberately does not reimplement any of it, it only calls
through."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _format_embedding(embedding: list[float] | None) -> str | None:
    if embedding is None:
        return None
    return "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"


async def match_ingredient(
    db: AsyncSession,
    raw_text: str,
    embedding: list[float] | None = None,
    fuzzy_threshold: float = 0.45,
    vector_threshold: float = 0.55,
    max_results: int = 5,
) -> list[dict]:
    result = await db.execute(
        text(
            """
            SELECT ingredient_id, canonical_name, match_method, match_score
            FROM kb.fn_match_ingredient(
                p_raw_text := :raw_text,
                p_embedding := CAST(:embedding AS vector),
                p_fuzzy_threshold := :fuzzy_threshold,
                p_vector_threshold := :vector_threshold,
                p_max_results := :max_results
            )
            """
        ),
        {
            "raw_text": raw_text,
            "embedding": _format_embedding(embedding),
            "fuzzy_threshold": fuzzy_threshold,
            "vector_threshold": vector_threshold,
            "max_results": max_results,
        },
    )
    return [dict(row) for row in result.mappings().all()]


async def log_unrecognised_term(db: AsyncSession, raw_text: str) -> None:
    await db.execute(text("SELECT kb.fn_log_unrecognised_term(:raw_text)"), {"raw_text": raw_text})


async def scan_summary(db: AsyncSession, scan_id, language: str = "en") -> dict:
    result = await db.execute(
        text("SELECT app.fn_scan_summary(:scan_id, :language) AS summary"),
        {"scan_id": str(scan_id), "language": language},
    )
    return result.mappings().one()["summary"]
