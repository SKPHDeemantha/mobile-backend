"""GET /allergen-groups — the reference list the mobile app uses to map its
local allergen picks onto server `allergen_group_id`s before pushing a
profile up. Groups come from sql/00_schema.sql SECTION 5.2 seed."""

import pytest

pytestmark = pytest.mark.asyncio

MAJOR_NINE = {"PEANUT", "TREE_NUT", "MILK", "EGG", "SOY", "WHEAT", "FISH", "SHELLFISH", "SESAME"}
SENSITIVITIES = {"GLUTEN", "SULPHITE", "MUSTARD"}


async def test_lists_all_seeded_groups_without_auth(client):
    resp = await client.get("/api/v1/allergen-groups")
    assert resp.status_code == 200
    body = resp.json()

    codes = {g["code"] for g in body}
    assert MAJOR_NINE <= codes
    assert SENSITIVITIES <= codes

    # returned in display_order (the SECTION 5.2 seed order)
    orders = [g["display_order"] for g in body]
    assert orders == sorted(orders)


async def test_group_shape_is_usable_for_profile_mapping(client):
    resp = await client.get("/api/v1/allergen-groups")
    peanut = next(g for g in resp.json() if g["code"] == "PEANUT")

    # the app does: allergen_catalog.dart id 'peanut' -> 'PEANUT' -> this UUID
    assert peanut["allergen_group_id"]
    assert peanut["is_major"] is True
    assert peanut["display_order"] == 1
    # kb.allergen_group_translations is unseeded for now
    assert peanut["display_name"] is None


async def test_include_inactive_flag_is_accepted(client):
    resp = await client.get("/api/v1/allergen-groups", params={"include_inactive": "true"})
    assert resp.status_code == 200
    assert {g["code"] for g in resp.json()} >= MAJOR_NINE
