"""Exercises kb.fn_match_ingredient directly over SQL — the matching cascade
is safety-critical logic that lives in the database (sql/00_schema.sql
SECTION 9.1), so it deserves tests that don't go through the API layer at
all. Uses the seed rows already inserted by sql/00_schema.sql SECTION 13
(Soy lecithin, Whey powder, Casein, Monosodium glutamate, Tartrazine)."""

import pytest


async def _match(raw_conn, text: str):
    rows = await raw_conn.fetch(
        "SELECT * FROM kb.fn_match_ingredient(p_raw_text := $1)",
        text,
    )
    return [dict(r) for r in rows]


async def test_exact_match(raw_conn):
    results = await _match(raw_conn, "Soy lecithin")
    assert results[0]["match_method"] == "exact"
    assert results[0]["match_score"] == pytest.approx(1.0)


async def test_alias_match(raw_conn):
    # 'lecithin' is a curated alias of 'Soy lecithin' (seeded in 00_schema.sql).
    results = await _match(raw_conn, "lecithin")
    assert results[0]["match_method"] == "alias"
    assert results[0]["canonical_name"] == "Soy lecithin"


async def test_fuzzy_match_tolerates_ocr_typo(raw_conn):
    # 'whey solids' is a curated alias of 'Whey powder'; a one-character OCR
    # slip (here a dropped 'i': "whey solds") should still resolve via
    # trigram similarity rather than returning nothing. NB the fuzzy stage
    # deliberately stops at p_fuzzy_threshold=0.45 — mangling both words at
    # once ("why solds", sim 0.375) is meant to miss, so an allergen check
    # never fires on a wild guess.
    results = await _match(raw_conn, "whey solds")
    assert results, "expected at least one fuzzy match for a near-miss spelling"
    assert results[0]["match_method"] in ("fuzzy", "alias", "exact")


async def test_unmatched_ingredient_returns_nothing(raw_conn):
    results = await _match(raw_conn, "completely fictional ingredient xyz123")
    assert results == []


async def test_unrecognised_term_is_logged_and_deduplicated(raw_conn):
    term = "totally novel mystery compound"
    await raw_conn.execute("SELECT kb.fn_log_unrecognised_term($1)", term)
    await raw_conn.execute("SELECT kb.fn_log_unrecognised_term($1)", term)

    row = await raw_conn.fetchrow(
        "SELECT occurrence_count FROM kb.unrecognised_terms WHERE sample_raw_text = $1",
        term,
    )
    assert row["occurrence_count"] == 2
