import uuid

from pydantic import BaseModel


class AllergenGroupOut(BaseModel):
    """One row of `GET /allergen-groups`.

    Reference data the mobile app pulls once so it can turn its local
    allergen picks (lowercase ids like `tree_nut`, see
    mobile-frontend/lib/data/allergen_catalog.dart) into the server's
    `allergen_group_id` UUIDs when it pushes a profile up on login
    (unblocks profile push-sync -> authoritative per-profile flagging).

    `display_name` / `description` come from kb.allergen_group_translations
    for the requested language; both are null until that table is seeded.
    """

    allergen_group_id: uuid.UUID
    code: str
    is_major: bool
    icon_code: str
    display_order: int
    is_active: bool
    display_name: str | None = None
    description: str | None = None
