"""Public request capture and organization-scoped read projections."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.contexts.links.contracts import StatisticsUnavailableError
from tests.identity_support import ORG_B, bearer


async def test_counts_span_pages_and_reads_do_not_count(identity_client, issuer):
    headers = bearer(issuer)
    pool = (
        await identity_client.post(
            "/api/v1/pools", headers=headers, json={"size": 25, "name": "Statistics"}
        )
    ).json()
    assert "statistics" not in pool
    links = (
        await identity_client.get(
            "/api/v1/links", headers=headers, params={"pool_id": pool["id"], "limit": 100}
        )
    ).json()["items"]
    code = links[0]["short_code"]
    assert links[0]["statistics"]["redirects"] == 0
    assert links[0]["statistics"]["last_visited_at"] is None
    for _ in range(2):
        assert (await identity_client.get("/" + code)).status_code == 200
    assert (
        await identity_client.post(
            "/" + code + "/subscriptions", data={"email": "visitor@example.com"}
        )
    ).status_code == 200
    for code_index, email in (
        (0, "visitor@example.com"),
        (0, "second@example.com"),
        (1, "visitor@example.com"),
    ):
        assert (
            await identity_client.post(
                "/" + links[code_index]["short_code"] + "/subscriptions", data={"email": email}
            )
        ).status_code == 200
    unvisited = (
        await identity_client.get("/api/v1/links/" + links[1]["id"], headers=headers)
    ).json()
    assert unvisited["statistics"]["subscribers"] == 1
    assert unvisited["statistics"]["last_visited_at"] is None
    key = headers | {"Idempotency-Key": "activate-statistics"}
    activated = await identity_client.patch(
        "/api/v1/links/" + links[0]["id"],
        headers=key,
        json={"destination_url": "https://example.com/ready"},
    )
    assert activated.status_code == 200 and "statistics" not in activated.json()
    for _ in range(3):
        assert (await identity_client.get("/" + code)).status_code == 307
    assert (await identity_client.get("/" + links[-1]["short_code"])).status_code == 200
    for path in ("/api/v1/statistics", "/api/v1/pools/" + pool["id"]):
        value = (await identity_client.get(path, headers=headers)).json()
        stats = value.get("statistics", value)
        assert (stats["redirects"], stats["waiting_views"]) == (3, 3)
        assert stats["subscribers"] == 3
        assert stats["tracked_from"] <= stats["last_visited_at"] <= stats["as_of"]
    page = (
        await identity_client.get("/api/v1/links", headers=headers, params={"pool_id": pool["id"]})
    ).json()
    assert len(page["items"]) == 20 and page["total"] == 25
    assert page["items"][0]["statistics"]["redirects"] == 3
    assert "_links" in page and "next" in page["_links"]
    pools = (await identity_client.get("/api/v1/pools", headers=headers)).json()["items"]
    assert pools[0]["statistics"]["waiting_views"] == 3
    replay = await identity_client.patch(
        "/api/v1/links/" + links[0]["id"],
        headers=key,
        json={"destination_url": "https://example.com/ready"},
    )
    assert replay.json() == activated.json() and replay.headers["Idempotency-Replayed"] == "true"
    assert (await identity_client.get("/api/v1/statistics", headers=headers)).json()[
        "redirects"
    ] == 3
    assert (
        await identity_client.delete("/api/v1/links/" + links[0]["id"], headers=headers)
    ).status_code == 204
    stats = (await identity_client.get("/api/v1/statistics", headers=headers)).json()
    assert (stats["redirects"], stats["waiting_views"]) == (0, 1)
    assert stats["subscribers"] == 1
    assert (
        await identity_client.delete("/api/v1/pools/" + pool["id"], headers=headers)
    ).status_code == 204
    stats = (await identity_client.get("/api/v1/statistics", headers=headers)).json()
    assert (stats["redirects"], stats["waiting_views"]) == (0, 0)
    assert stats["subscribers"] == 0


async def test_statistics_require_authority_and_exclude_other_organizations(
    identity_client,
    issuer,
    authority,
):
    headers = bearer(issuer)
    link = (
        await identity_client.post(
            "/api/v1/links", headers=headers, json={"destination_url": "https://example.com"}
        )
    ).json()
    await identity_client.get("/" + link["short_code"])
    assert (await identity_client.get("/api/v1/statistics")).status_code == 401
    assert (
        await identity_client.get(
            "/api/v1/statistics", headers=bearer(issuer, scope="links:create")
        )
    ).status_code == 403
    other = bearer(issuer, org=ORG_B)
    assert (
        await identity_client.get("/api/v1/links/" + link["id"], headers=other)
    ).status_code == 404
    assert (await identity_client.get("/api/v1/statistics", headers=other)).json()["redirects"] == 0
    authority.allowed = False
    assert (await identity_client.get("/api/v1/statistics", headers=headers)).status_code == 403


@pytest.mark.parametrize("failure", ["write", "timeout", "commit"])
async def test_capture_failure_preserves_response_and_rolls_back(
    identity_client,
    issuer,
    identity_db,
    database,
    monkeypatch,
    failure,
    caplog,
):
    headers = bearer(issuer)
    link = (
        await identity_client.post(
            "/api/v1/links", headers=headers, json={"destination_url": "https://example.com"}
        )
    ).json()
    if failure == "write":
        monkeypatch.setattr(
            identity_db, "record_visit", AsyncMock(side_effect=RuntimeError("private payload"))
        )
    elif failure == "timeout":

        async def blocked(*_):
            await asyncio.sleep(10)

        monkeypatch.setattr(identity_db, "record_visit", blocked)
    else:
        database.commit_failure = True
    response = await identity_client.get("/" + link["short_code"])
    assert response.status_code == 307 and response.headers["location"] == "https://example.com"
    assert "private payload" not in caplog.text
    database.commit_failure = False
    stats = (await identity_client.get("/api/v1/statistics", headers=headers)).json()
    assert stats["redirects"] == 0


async def test_disabled_missing_and_head_requests_do_not_count(identity_client, issuer):
    headers = bearer(issuer)
    link = (
        await identity_client.post(
            "/api/v1/links", headers=headers, json={"destination_url": "https://example.com"}
        )
    ).json()
    assert (await identity_client.head("/" + link["short_code"])).status_code == 405
    assert (await identity_client.get("/" + link["short_code"])).status_code == 307
    await identity_client.patch(
        "/api/v1/links/" + link["id"], headers=headers, json={"is_active": False}
    )
    assert (await identity_client.get("/" + link["short_code"])).status_code == 410
    assert (await identity_client.get("/missing")).status_code == 404
    assert (await identity_client.get("/api/v1/statistics", headers=headers)).json()[
        "redirects"
    ] == 1


async def test_unavailable_statistics_are_not_reported_as_zero(
    identity_client, issuer, identity_db, monkeypatch
):
    monkeypatch.setattr(
        identity_db, "statistics", AsyncMock(side_effect=StatisticsUnavailableError)
    )
    response = await identity_client.get("/api/v1/statistics", headers=bearer(issuer))
    assert response.status_code == 503
    assert response.json()["code"] == "statistics_unavailable"


def test_openapi_statistics_are_reads_with_existing_pagination(application):
    document = application.openapi()
    operation = document["paths"]["/api/v1/statistics"]["get"]
    assert operation["operationId"] == "get_statistics"
    assert operation["security"] == [{"OAuth2AuthorizationCodeBearer": ["links:read"]}]
    assert "post" not in document["paths"]["/api/v1/statistics"]
    assert not any(
        p["name"] in {"organization_id", "offset", "page"} for p in operation.get("parameters", [])
    )
    assert "statistics" not in document["components"]["schemas"]["LinkResponse"]["properties"]
    assert "statistics" in document["components"]["schemas"]["LinkReadResponse"]["properties"]
