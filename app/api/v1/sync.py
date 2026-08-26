from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.models.kb import mv_allergen_lookup
from app.schemas.ingredient import KnowledgeBaseRow

router = APIRouter(tags=["sync"])
settings = get_settings()


@router.get("/sync/knowledge-base", response_model=list[KnowledgeBaseRow])
async def sync_knowledge_base(
    after_ingredient_id: str | None = Query(default=None, description="Opaque pagination cursor from the previous page's last row"),
    limit: int = Query(default=2000, le=5000),
    db: AsyncSession = Depends(get_db),
) -> list[KnowledgeBaseRow]:
    """Feeds the Flutter app's local `kb_cache` SQLite table (hybrid offline
    plan). kb.mv_allergen_lookup is a materialized view — cheap to page
    through repeatedly, refreshed periodically by /internal/maintenance/
    refresh-lookup rather than recomputed on every request."""
    query = select(mv_allergen_lookup).order_by(mv_allergen_lookup.c.ingredient_id).limit(limit)
    if after_ingredient_id:
        query = query.where(mv_allergen_lookup.c.ingredient_id > after_ingredient_id)
    result = await db.execute(query)
    return [KnowledgeBaseRow(**row._mapping) for row in result.all()]


@router.post("/internal/maintenance/refresh-lookup", status_code=status.HTTP_204_NO_CONTENT)
async def refresh_lookup(
    x_maintenance_key: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Neon's pg_cron can only schedule jobs from the 'postgres' database
    (see sql/00_schema.sql SECTION 12), so this project's cron job instead
    lives in GitHub Actions and calls this endpoint on a schedule. Protected
    by a shared secret, not JWT — there is no human user on the other end."""
    if not settings.maintenance_api_key or x_maintenance_key != settings.maintenance_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid maintenance key")
    await db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY kb.mv_allergen_lookup"))
    await db.commit()
    return None
