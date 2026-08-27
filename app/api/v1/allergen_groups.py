from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.kb import allergen_group_translations, allergen_groups
from app.schemas.allergen import AllergenGroupOut

router = APIRouter(prefix="/allergen-groups", tags=["allergen-groups"])


@router.get("", response_model=list[AllergenGroupOut])
async def list_allergen_groups(
    language: str = Query(default="en", max_length=5, description="Language for display_name / description"),
    include_inactive: bool = Query(default=False, description="Also return groups with is_active = false"),
    db: AsyncSession = Depends(get_db),
) -> list[AllergenGroupOut]:
    """Public reference list of the 9 major allergen groups plus the extra
    sensitivities (GLUTEN / SULPHITE / MUSTARD), seeded by sql/00_schema.sql
    SECTION 5.2. No auth: the app needs this before/around login to map its
    local allergen picks (allergen_catalog.dart ids, e.g. `tree_nut` ->
    `TREE_NUT`) onto the returned `allergen_group_id`s and build a
    server-side profile via POST /profiles."""
    tr = allergen_group_translations
    query = (
        select(
            allergen_groups.c.allergen_group_id,
            allergen_groups.c.code,
            allergen_groups.c.is_major,
            allergen_groups.c.icon_code,
            allergen_groups.c.display_order,
            allergen_groups.c.is_active,
            tr.c.display_name,
            tr.c.description,
        )
        .select_from(
            allergen_groups.outerjoin(
                tr,
                (tr.c.allergen_group_id == allergen_groups.c.allergen_group_id) & (tr.c.language_code == language),
            )
        )
        .order_by(allergen_groups.c.display_order, allergen_groups.c.code)
    )
    if not include_inactive:
        query = query.where(allergen_groups.c.is_active.is_(True))
    result = await db.execute(query)
    return [AllergenGroupOut(**row._mapping) for row in result.all()]
