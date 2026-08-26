import pytest

pytestmark = pytest.mark.asyncio


async def _register(client, email: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery", "display_name": email.split("@")[0]},
    )
    assert resp.status_code == 201
    return resp.json()


def _auth_headers(auth_body: dict) -> dict:
    return {"Authorization": f"Bearer {auth_body['tokens']['access_token']}"}


async def test_guest_scan_matches_seeded_ingredient(client):
    resp = await client.post(
        "/api/v1/scans",
        json={
            "raw_ocr_text": "Ingredients: Soy lecithin, water.",
            "ingredients": ["Soy lecithin", "water"],
            "ocr_confidence": 92.5,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["total_parsed"] == 2
    # "Soy lecithin" resolves exactly; "water" isn't in the seed data and
    # should surface as unmatched, not crash the request.
    matched_names = {f["canonical_name"] for f in body["findings"]}
    assert "Soy lecithin" in matched_names
    assert body["unmatched"] == 1


async def test_scan_against_someone_elses_profile_is_rejected(client):
    owner = await _register(client, "owner@example.com")
    intruder = await _register(client, "intruder@example.com")

    profile_resp = await client.post(
        "/api/v1/profiles", json={"profile_name": "Owner's profile", "allergens": []}, headers=_auth_headers(owner)
    )
    assert profile_resp.status_code == 201
    profile_id = profile_resp.json()["profile_id"]

    resp = await client.post(
        "/api/v1/scans",
        json={"profile_id": profile_id, "raw_ocr_text": "x", "ingredients": ["water"], "ocr_confidence": 90},
        headers=_auth_headers(intruder),
    )
    assert resp.status_code == 403


async def test_profile_allergen_triggers_is_profile_match(client, raw_conn):
    user = await _register(client, "allergic@example.com")

    milk_group = await raw_conn.fetchrow("SELECT allergen_group_id FROM kb.allergen_groups WHERE code = 'MILK'")

    profile_resp = await client.post(
        "/api/v1/profiles",
        json={"profile_name": "Milk allergy", "allergens": [{"allergen_group_id": str(milk_group["allergen_group_id"]), "severity": "severe"}]},
        headers=_auth_headers(user),
    )
    profile_id = profile_resp.json()["profile_id"]

    scan_resp = await client.post(
        "/api/v1/scans",
        json={
            "profile_id": profile_id,
            "raw_ocr_text": "Ingredients: Whey powder.",
            "ingredients": ["Whey powder"],
            "ocr_confidence": 95,
        },
        headers=_auth_headers(user),
    )
    assert scan_resp.status_code == 201
    findings = scan_resp.json()["findings"]
    assert any(f["canonical_name"] == "Whey powder" and f["is_profile_match"] for f in findings)
    # Tier 1 (personal allergen matches) must sort before anything else.
    assert findings[0]["tier"] == 1


async def test_scan_history_is_private_to_the_owner(client):
    user_a = await _register(client, "history-a@example.com")
    user_b = await _register(client, "history-b@example.com")

    await client.post(
        "/api/v1/scans",
        json={"raw_ocr_text": "x", "ingredients": ["water"], "ocr_confidence": 90},
        headers=_auth_headers(user_a),
    )

    a_history = await client.get("/api/v1/scans", headers=_auth_headers(user_a))
    b_history = await client.get("/api/v1/scans", headers=_auth_headers(user_b))
    assert len(a_history.json()) == 1
    assert len(b_history.json()) == 0
