from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.ingredient import IngredientSearchResult

router = APIRouter(prefix="/search", tags=["search"])

# Manual ingredient lookup (proposal FR-11): typeahead over canonical names
# AND curated aliases, trigram-ranked so OCR-style typos still surface a
# result. Deliberately a standalone query rather than kb.fn_match_ingredient
# — that function is tuned to return the single best allergen match for a
# scan; this one is tuned to return several browsable candidates for a
# human typing into a search box.
_SEARCH_SQL = text(
    """
    SELECT
        i.ingredient_id,
        i.canonical_name::text AS canonical_name,
        tr.display_name,
        tr.explanation,
        i.ingredient_type::text AS ingredient_type,
        COALESCE(array_agg(DISTINCT ag.code) FILTER (WHERE ag.code IS NOT NULL), ARRAY[]::text[]) AS allergen_codes,
        ad.e_number,
        ac.name AS additive_category,
        GREATEST(
            similarity(i.normalised_name, kb.normalise_text(:q)),
            COALESCE(MAX(similarity(a.normalised_alias, kb.normalise_text(:q))), 0)
        ) AS similarity
    FROM kb.ingredients i
    LEFT JOIN kb.ingredient_aliases a
           ON a.ingredient_id = i.ingredient_id AND a.is_active
    LEFT JOIN kb.ingredient_allergens ia ON ia.ingredient_id = i.ingredient_id
    LEFT JOIN kb.allergen_groups ag ON ag.allergen_group_id = ia.allergen_group_id
    LEFT JOIN kb.additive_details ad ON ad.ingredient_id = i.ingredient_id
    LEFT JOIN kb.additive_categories ac ON ac.additive_category_id = ad.additive_category_id
    LEFT JOIN kb.ingredient_translations tr
           ON tr.ingredient_id = i.ingredient_id AND tr.language_code = :language
    WHERE i.is_active
      AND (
            i.normalised_name % kb.normalise_text(:q)
         OR a.normalised_alias % kb.normalise_text(:q)
      )
    GROUP BY i.ingredient_id, i.canonical_name, tr.display_name, tr.explanation,
             i.ingredient_type, ad.e_number, ac.name
    ORDER BY similarity DESC
    LIMIT :limit
    """
)


@router.get("", response_model=list[IngredientSearchResult])
async def search_ingredients(
    q: str = Query(min_length=2, max_length=200),
    language: str = Query(default="en", max_length=5),
    limit: int = Query(default=20, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[IngredientSearchResult]:
    result = await db.execute(_SEARCH_SQL, {"q": q, "language": language, "limit": limit})
    return [IngredientSearchResult(**row) for row in result.mappings().all()]
