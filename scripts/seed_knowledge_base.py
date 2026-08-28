"""Loads scripts/seed_data/ingredients.csv into the knowledge base.

This starter file has ~40 common allergen sources and additives — enough to
exercise every part of the matching cascade end-to-end. It is a STARTING
POINT, not the 500+ verified entries the proposal commits to (§9.1): growing
it further is a content-research task, tracked separately from the code
(see mobile-backend README "Knowledge base content").

Usage:
    python scripts/seed_knowledge_base.py [path/to/other.csv ...]
Reads DATABASE_URL_DIRECT from the environment. Idempotent — safe to re-run;
existing rows are updated in place (matched by canonical_name / e_number /
(ingredient_id, language_code) as appropriate).
"""

import asyncio
import csv
import os
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.dsn import to_asyncpg_dsn  # noqa: E402

DEFAULT_CSV = os.path.join(os.path.dirname(__file__), "seed_data", "ingredients.csv")


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split("|") if v.strip()]


async def seed_file(conn: asyncpg.Connection, path: str) -> None:
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"{path}: {len(rows)} rows")

    for row in rows:
        async with conn.transaction():
            ingredient_id = await conn.fetchval(
                """
                INSERT INTO kb.ingredients (canonical_name, ingredient_type)
                VALUES ($1, $2)
                ON CONFLICT (canonical_name) DO UPDATE SET ingredient_type = EXCLUDED.ingredient_type
                RETURNING ingredient_id
                """,
                row["canonical_name"],
                row["ingredient_type"],
            )

            for code in _split(row.get("allergen_codes", "")):
                allergen_group_id = await conn.fetchval("SELECT allergen_group_id FROM kb.allergen_groups WHERE code = $1", code)
                if allergen_group_id is None:
                    print(f"  WARNING: unknown allergen code '{code}' for '{row['canonical_name']}' — skipped")
                    continue
                await conn.execute(
                    """
                    INSERT INTO kb.ingredient_allergens (ingredient_id, allergen_group_id, certainty)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (ingredient_id, allergen_group_id) DO UPDATE SET certainty = EXCLUDED.certainty
                    """,
                    ingredient_id,
                    allergen_group_id,
                    row.get("certainty") or "definite",
                )

            e_number = row.get("e_number", "").strip()
            if e_number:
                category_id = await conn.fetchval(
                    "SELECT additive_category_id FROM kb.additive_categories WHERE code = $1", row["additive_category_code"]
                )
                if category_id is None:
                    print(f"  WARNING: unknown additive category '{row['additive_category_code']}' for '{row['canonical_name']}' — skipped")
                else:
                    await conn.execute(
                        """
                        INSERT INTO kb.additive_details (ingredient_id, e_number, additive_category_id, concern_level)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (ingredient_id) DO UPDATE
                            SET e_number = EXCLUDED.e_number,
                                additive_category_id = EXCLUDED.additive_category_id,
                                concern_level = EXCLUDED.concern_level
                        """,
                        ingredient_id,
                        e_number,
                        category_id,
                        int(row.get("concern_level") or 1),
                    )

            for alias in _split(row.get("aliases", "")):
                await conn.execute(
                    """
                    INSERT INTO kb.ingredient_aliases (ingredient_id, alias_text, language_code)
                    VALUES ($1, $2, 'en')
                    ON CONFLICT (normalised_alias, language_code) WHERE is_active DO NOTHING
                    """,
                    ingredient_id,
                    alias,
                )

            explanation = row.get("explanation_en", "").strip()
            if explanation:
                await conn.execute(
                    """
                    INSERT INTO kb.ingredient_translations (ingredient_id, language_code, display_name, explanation, generated_by)
                    VALUES ($1, 'en', $2, $3, 'human')
                    ON CONFLICT (ingredient_id, language_code) DO UPDATE
                        SET display_name = EXCLUDED.display_name, explanation = EXCLUDED.explanation
                    """,
                    ingredient_id,
                    row["canonical_name"],
                    explanation,
                )

    print(f"{path}: done")


async def seed_translations_file(conn: asyncpg.Connection, path: str, language_code: str) -> None:
    """Loads scripts/seed_data/translations_<lang>.csv (canonical_name,
    display_name, explanation) into kb.ingredient_translations. Rows whose
    canonical_name is unknown are skipped with a warning — the files can be
    filled in incrementally."""
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"{path}: {len(rows)} rows ({language_code})")
    seeded = skipped = 0
    for row in rows:
        name = (row.get("canonical_name") or "").strip()
        display = (row.get("display_name") or "").strip()
        if not name or not display:
            continue
        ingredient_id = await conn.fetchval(
            "SELECT ingredient_id FROM kb.ingredients WHERE canonical_name = $1", name
        )
        if ingredient_id is None:
            print(f"  WARNING: no ingredient named '{name}' — translation skipped")
            skipped += 1
            continue
        await conn.execute(
            """
            INSERT INTO kb.ingredient_translations
                (ingredient_id, language_code, display_name, explanation, generated_by)
            VALUES ($1, $2, $3, $4, 'human')
            ON CONFLICT (ingredient_id, language_code) DO UPDATE
                SET display_name = EXCLUDED.display_name,
                    explanation  = EXCLUDED.explanation
            """,
            ingredient_id,
            language_code,
            display,
            (row.get("explanation") or "").strip() or None,
        )
        seeded += 1
    print(f"{path}: done — {seeded} seeded, {skipped} skipped")


async def main() -> None:
    url = os.environ.get("DATABASE_URL_DIRECT")
    if not url:
        print("ERROR: set DATABASE_URL_DIRECT — this must be the DIRECT, non-pooled Neon endpoint.", file=sys.stderr)
        sys.exit(1)
    dsn = to_asyncpg_dsn(url)

    paths = sys.argv[1:] or [DEFAULT_CSV]
    seed_dir = os.path.dirname(DEFAULT_CSV)

    conn = await asyncpg.connect(dsn)
    try:
        for path in paths:
            await seed_file(conn, path)
        # Sinhala / Tamil display_name + explanation, loaded after the
        # English rows so every ingredient_id already exists. Optional —
        # a missing file just means that language stays English.
        for lang in ("si", "ta"):
            tpath = os.path.join(seed_dir, f"translations_{lang}.csv")
            if os.path.exists(tpath):
                await seed_translations_file(conn, tpath, lang)
        # Not CONCURRENTLY — see sql/00_schema.sql SECTION 11: the view's
        # unique index is expression-based, which disqualifies it.
        await conn.execute("REFRESH MATERIALIZED VIEW kb.mv_allergen_lookup")
        print("Refreshed kb.mv_allergen_lookup")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
