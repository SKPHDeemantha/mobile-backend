import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_optional_user
from app.core.db import get_db
from app.models.domain import brands, product_label_versions, products, profiles, scan_ingredients, scan_matches, scans
from app.schemas.scan import ProductIn, ScanCreate, ScanListItemOut, ScanSummaryOut
from app.services.embeddings import maybe_embed
from app.services.matching import log_unrecognised_term, match_ingredient, scan_summary

router = APIRouter(prefix="/scans", tags=["scans"])


async def _get_or_create_product(db: AsyncSession, product_in: ProductIn, raw_text: str) -> uuid.UUID:
    brand_id = None
    if product_in.brand_name:
        result = await db.execute(
            pg_insert(brands)
            .values(brand_id=uuid.uuid4(), name=product_in.brand_name)
            .on_conflict_do_update(index_elements=["name"], set_={"name": product_in.brand_name})
            .returning(brands.c.brand_id)
        )
        brand_id = result.scalar_one()

    if product_in.barcode:
        result = await db.execute(
            pg_insert(products)
            .values(
                product_id=uuid.uuid4(),
                product_name=product_in.product_name,
                brand_id=brand_id,
                barcode=product_in.barcode,
            )
            .on_conflict_do_update(index_elements=["barcode"], set_={"product_name": product_in.product_name})
            .returning(products.c.product_id)
        )
        product_id = result.scalar_one()
    else:
        product_id = uuid.uuid4()
        await db.execute(
            insert(products).values(product_id=product_id, product_name=product_in.product_name, brand_id=brand_id)
        )

    # Reformulation tracking (proposal §6.3, product_label_versions). Relies
    # on the DB's generated text_hash + its own unique index — we never
    # write text_hash ourselves.
    await db.execute(
        pg_insert(product_label_versions)
        .values(label_version_id=uuid.uuid4(), product_id=product_id, raw_text=raw_text)
        .on_conflict_do_nothing(index_elements=["product_id", "text_hash"])
    )
    return product_id


@router.post("", response_model=ScanSummaryOut, status_code=status.HTTP_201_CREATED)
async def create_scan(
    body: ScanCreate,
    current: CurrentUser | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> ScanSummaryOut:
    try:
        body.validate_enums()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    if body.profile_id is not None:
        if current is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Log in to scan against a saved profile, or omit profile_id for a guest scan")
        owned = await db.execute(
            select(profiles.c.profile_id).where(profiles.c.profile_id == body.profile_id, profiles.c.user_id == current.user_id)
        )
        if owned.first() is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "That profile does not belong to the current user")

    product_id = await _get_or_create_product(db, body.product, body.raw_ocr_text) if body.product else None

    scan_id = uuid.uuid4()
    await db.execute(
        insert(scans).values(
            scan_id=scan_id,
            user_id=current.user_id if current else None,
            profile_id=body.profile_id,
            product_id=product_id,
            raw_ocr_text=body.raw_ocr_text,
            ocr_confidence=Decimal(str(round(body.ocr_confidence, 2))),
            ocr_engine=body.ocr_engine,
            device_platform=body.device_platform,
            status="processing",
        )
    )

    for index, ingredient_text in enumerate(body.ingredients):
        scan_ingredient_id = uuid.uuid4()
        await db.execute(
            insert(scan_ingredients).values(
                scan_ingredient_id=scan_ingredient_id,
                scan_id=scan_id,
                position_index=index,
                detected_text=ingredient_text[:300],
            )
        )

        embedding = maybe_embed(ingredient_text)
        matches = await match_ingredient(db, ingredient_text, embedding=embedding)

        if not matches:
            await log_unrecognised_term(db, ingredient_text)
            continue

        for match in matches:
            # is_profile_match is set by app.fn_flag_profile_match() — a
            # BEFORE INSERT trigger on app.scan_matches — never computed here.
            await db.execute(
                insert(scan_matches).values(
                    match_id=uuid.uuid4(),
                    scan_ingredient_id=scan_ingredient_id,
                    ingredient_id=match["ingredient_id"],
                    match_method=match["match_method"],
                    match_score=Decimal(str(round(float(match["match_score"]), 4))),
                )
            )

    await db.execute(update(scans).where(scans.c.scan_id == scan_id).values(status="completed"))
    await db.commit()

    summary = await scan_summary(db, scan_id)
    return ScanSummaryOut(**summary)


@router.get("", response_model=list[ScanListItemOut])
async def list_scans(
    limit: int = 50,
    offset: int = 0,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ScanListItemOut]:
    result = await db.execute(
        select(scans.c.scan_id, scans.c.scanned_at, scans.c.status, scans.c.ocr_confidence)
        .where(scans.c.user_id == current.user_id)
        .order_by(desc(scans.c.scanned_at))
        .limit(limit)
        .offset(offset)
    )
    return [ScanListItemOut(**row._mapping) for row in result.all()]


@router.get("/{scan_id}", response_model=ScanSummaryOut)
async def get_scan(scan_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> ScanSummaryOut:
    owned = await db.execute(select(scans.c.scan_id).where(scans.c.scan_id == scan_id, scans.c.user_id == current.user_id))
    if owned.first() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    summary = await scan_summary(db, scan_id)
    return ScanSummaryOut(**summary)
