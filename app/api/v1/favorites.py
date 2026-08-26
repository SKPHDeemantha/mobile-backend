import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.core.db import get_db
from app.models.domain import brands, favourites, products

router = APIRouter(prefix="/favorites", tags=["favorites"])


class FavoriteCreate(BaseModel):
    product_id: uuid.UUID
    note: str | None = Field(default=None, max_length=300)


class FavoriteOut(BaseModel):
    product_id: uuid.UUID
    product_name: str
    brand_name: str | None
    note: str | None


@router.get("", response_model=list[FavoriteOut])
async def list_favorites(current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[FavoriteOut]:
    result = await db.execute(
        select(favourites.c.product_id, products.c.product_name, brands.c.name.label("brand_name"), favourites.c.note)
        .select_from(favourites.join(products, favourites.c.product_id == products.c.product_id).outerjoin(brands, products.c.brand_id == brands.c.brand_id))
        .where(favourites.c.user_id == current.user_id)
        .order_by(favourites.c.saved_at.desc())
    )
    return [FavoriteOut(**row._mapping) for row in result.all()]


@router.put("", response_model=FavoriteOut, status_code=status.HTTP_201_CREATED)
async def add_favorite(body: FavoriteCreate, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> FavoriteOut:
    product_row = (await db.execute(select(products.c.product_id).where(products.c.product_id == body.product_id))).first()
    if product_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")

    await db.execute(
        pg_insert(favourites)
        .values(user_id=current.user_id, product_id=body.product_id, note=body.note)
        .on_conflict_do_update(index_elements=["user_id", "product_id"], set_={"note": body.note})
    )
    await db.commit()

    row = (
        await db.execute(
            select(favourites.c.product_id, products.c.product_name, brands.c.name.label("brand_name"), favourites.c.note)
            .select_from(favourites.join(products, favourites.c.product_id == products.c.product_id).outerjoin(brands, products.c.brand_id == brands.c.brand_id))
            .where(favourites.c.user_id == current.user_id, favourites.c.product_id == body.product_id)
        )
    ).one()
    return FavoriteOut(**row._mapping)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(product_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> None:
    await db.execute(delete(favourites).where(favourites.c.user_id == current.user_id, favourites.c.product_id == product_id))
    await db.commit()
    return None
