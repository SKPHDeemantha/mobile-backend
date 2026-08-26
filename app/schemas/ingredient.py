import uuid

from pydantic import BaseModel


class IngredientSearchResult(BaseModel):
    ingredient_id: uuid.UUID
    canonical_name: str
    display_name: str | None
    explanation: str | None
    ingredient_type: str
    allergen_codes: list[str]
    e_number: str | None
    additive_category: str | None
    similarity: float


class KnowledgeBaseRow(BaseModel):
    """One row of the offline sync payload the Flutter app caches into its
    local `kb_cache` SQLite table (kb.mv_allergen_lookup)."""

    ingredient_id: uuid.UUID
    normalised_name: str
    ingredient_type: str
    allergen_code: str | None
    certainty: str | None
    e_number: str | None
    additive_category_code: str | None
