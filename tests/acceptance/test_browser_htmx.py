import json

import pytest

from tests.acceptance.test_identity_links import bearer, sign_in


@pytest.mark.asyncio
async def test_htmx_without_a_session_restarts_login_with_full_navigation(identity_client):
    native = await identity_client.get("/dashboard/links")
    assert native.status_code == 303
    assert native.headers["location"] == "/login"

    enhanced = await identity_client.get("/dashboard/links", headers={"HX-Request": "true"})
    assert enhanced.status_code == 200
    assert enhanced.headers["HX-Redirect"] == "/login"
    assert enhanced.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_htmx_invalid_forms_preserve_the_get_url(identity_client, issuer, ephemeral):
    client = identity_client
    await sign_in(client)
    state = json.loads(await ephemeral.get("session", client.cookies.get("plazia_links_session")))
    created = await client.post(
        "/api/v1/links",
        headers=bearer(issuer),
        json={"destination_url": "https://example.com/page", "short_code": "existing"},
    )
    link_id = created.json()["id"]
    data = {"destination_url": "https://localhost/page", "csrf_token": state["csrf_token"]}
    for path in ("/dashboard/links", f"/dashboard/links/{link_id}"):
        response = await client.post(path, data=data, headers={"HX-Request": "true"})
        assert response.status_code == 422
        assert response.headers["HX-Push-Url"] == "false"
        assert 'value="https://localhost/page"' in response.text
        assert 'role="alert"' in response.text
    conflict = await client.post(
        "/dashboard/links",
        data={**data, "destination_url": "https://example.com/other", "short_code": "existing"},
        headers={"HX-Request": "true"},
    )
    assert conflict.status_code == 409
    assert conflict.headers["HX-Push-Url"] == "false"


@pytest.mark.asyncio
@pytest.mark.parametrize("filtered", [True, False])
async def test_deleting_a_link_preserves_the_pool_filter(
    identity_client, issuer, ephemeral, filtered
):
    client = identity_client
    await sign_in(client)
    state = json.loads(await ephemeral.get("session", client.cookies.get("plazia_links_session")))
    headers = bearer(issuer)
    pool = await client.post("/api/v1/pools", headers=headers, json={"size": 2, "name": "Launch"})
    pool_id = pool.json()["id"]
    rows = await client.get("/api/v1/links", headers=headers, params={"pool_id": pool_id})
    deleted, remaining = rows.json()["items"]
    outside = await client.post(
        "/api/v1/links",
        headers=headers,
        json={"short_code": "outside", "destination_url": "https://example.com/other"},
    )
    assert outside.status_code == 201
    suffix = f"?pool_id={pool_id}" if filtered else ""
    location = "/dashboard/links" + suffix
    action = f"/dashboard/links/{deleted['id']}/delete" + suffix
    before = await client.get(location)
    assert f'action="{action}"' in before.text
    response = await client.post(
        action,
        data={"csrf_token": state["csrf_token"]},
        headers={"HX-Request": "true"} if filtered else {},
    )
    assert response.status_code == 303
    assert response.headers["location"] == location
    after = await client.get(response.headers["location"])
    assert after.status_code == 200
    assert f"/{deleted['short_code']}" not in after.text
    assert f"/{remaining['short_code']}" in after.text
    assert ("/outside" in after.text) is (not filtered)
