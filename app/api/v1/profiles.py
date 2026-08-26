import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.core.db import get_db
from app.models.domain import profile_additives, profile_allergens, profiles
from app.models.kb import allergen_groups
from app.schemas.profile import ProfileCreate, ProfileOut, ProfileUpdate

router = APIRouter(prefix="/profiles", tags=["profiles"])


async def _load_profile(db: AsyncSession, profile_id: uuid.UUID) -> ProfileOut:
    row = (await db.execute(select(profiles).where(profiles.c.profile_id == profile_id))).one()

    allergen_rows = await db.execute(
        select(profile_allergens.c.allergen_group_id, allergen_groups.c.code, profile_allergens.c.severity)
        .select_from(profile_allergens.join(allergen_groups, profile_allergens.c.allergen_group_id == allergen_groups.c.allergen_group_id))
        .where(profile_allergens.c.profile_id == profile_id)
    )
    additive_rows = await db.execute(select(profile_additives.c.ingredient_id).where(profile_additives.c.profile_id == profile_id))

    return ProfileOut(
        profile_id=row.profile_id,
        profile_name=row.profile_name,
        is_default=row.is_default,
        allergens=[{"allergen_group_id": r.allergen_group_id, "code": r.code, "severity": r.severity} for r in allergen_rows.all()],
        additive_ingredient_ids=[r.ingredient_id for r in additive_rows.all()],
    )


async def _get_owned_or_404(db: AsyncSession, profile_id: uuid.UUID, user_id: uuid.UUID) -> None:
    row = (await db.execute(select(profiles.c.profile_id).where(profiles.c.profile_id == profile_id, profiles.c.user_id == user_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")


@router.get("", response_model=list[ProfileOut])
async def list_profiles(current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[ProfileOut]:
    rows = await db.execute(select(profiles.c.profile_id).where(profiles.c.user_id == current.user_id))
    return [await _load_profile(db, r.profile_id) for r in rows.all()]


@router.post("", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
async def create_profile(
    body: ProfileCreate,
    # Client-generated ID: the mobile app already creates profiles offline
    # with a local UUID (see mobile-frontend/lib/models/user_profile.dart).
    # Accepting that same ID here means no remapping is needed when a guest
    # profile is synced up after login.
    profile_id: uuid.UUID | None = None,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileOut:
    new_id = profile_id or uuid.uuid4()
    await db.execute(
        insert(profiles).values(profile_id=new_id, user_id=current.user_id, profile_name=body.profile_name, is_default=body.is_default)
    )
    for allergen in body.allergens:
        await db.execute(
            insert(profile_allergens).values(profile_id=new_id, allergen_group_id=allergen.allergen_group_id, severity=allergen.severity)
        )
    for ingredient_id in body.additive_ingredient_ids:
        await db.execute(insert(profile_additives).values(profile_id=new_id, ingredient_id=ingredient_id))
    await db.commit()
    return await _load_profile(db, new_id)


@router.patch("/{profile_id}", response_model=ProfileOut)
async def update_profile(
    profile_id: uuid.UUID, body: ProfileUpdate, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ProfileOut:
    await _get_owned_or_404(db, profile_id, current.user_id)
    changes = body.model_dump(exclude_unset=True)
    if changes:
        await db.execute(update(profiles).where(profiles.c.profile_id == profile_id).values(**changes))
        await db.commit()
    return await _load_profile(db, profile_id)


@router.put("/{profile_id}/allergens", response_model=ProfileOut)
async def replace_allergens(
    profile_id: uuid.UUID, body: list[dict], current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ProfileOut:
    """Body: [{"allergen_group_id": "...", "severity": "moderate"}, ...] —
    a full replace, matching how the Flutter ProfileEditorSheet submits the
    whole allergen selection at once rather than diffing."""
    await _get_owned_or_404(db, profile_id, current.user_id)
    await db.execute(delete(profile_allergens).where(profile_allergens.c.profile_id == profile_id))
    for item in body:
        await db.execute(
            insert(profile_allergens).values(
                profile_id=profile_id, allergen_group_id=item["allergen_group_id"], severity=item.get("severity", "moderate")
            )
        )
    await db.commit()
    return await _load_profile(db, profile_id)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> None:
    await _get_owned_or_404(db, profile_id, current.user_id)
    await db.execute(delete(profiles).where(profiles.c.profile_id == profile_id))
    await db.commit()
    return None
