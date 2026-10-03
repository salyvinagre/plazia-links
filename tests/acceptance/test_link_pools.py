import asyncio

import pytest
from pytest_bdd import given, scenarios, then, when

from tests.identity_support import bearer

scenarios("features/link_pools.feature")


@pytest.fixture
def flow(identity_client, issuer, identity_db):
    return {
        "client": identity_client,
        "headers": bearer(issuer),
        "repository": identity_db,
    }


@given("an organization has reserved a link without a destination")
def reserve(flow):
    async def operation():
        client = flow["client"]
        pool = await client.post(
            "/api/v1/pools", headers=flow["headers"], json={"size": 2, "name": "Launch"}
        )
        assert pool.status_code == 201, pool.text
        rows = await client.get(
            "/api/v1/links", params={"pool_id": pool.json()["id"]}, headers=flow["headers"]
        )
        assert len(rows.json()["items"]) == 2
        flow["link"] = rows.json()["items"][0]
        waiting = await client.get("/" + flow["link"]["short_code"])
        assert waiting.status_code == 200 and "Notify me" in waiting.text

    asyncio.run(operation())


@when("a visitor subscribes with an email address")
def subscribe(flow):
    asyncio.run(_subscribe(flow))


async def _subscribe(flow):
    result = await flow["client"].post(
        "/" + flow["link"]["short_code"] + "/subscriptions", data={"email": "Visitor@Example.com"}
    )
    assert result.status_code == 200 and "on the list" in result.text
    assert flow["repository"].public_locked


@when("a visitor submits the same email address twice")
def duplicate(flow):
    asyncio.run(_subscribe(flow))
    asyncio.run(_subscribe(flow))


@when("the organization registers a valid destination")
def activate(flow):
    async def operation():
        result = await flow["client"].patch(
            "/api/v1/links/" + flow["link"]["id"],
            headers=flow["headers"],
            json={"destination_url": "https://example.com/launch"},
        )
        assert result.status_code == 200, result.text

    asyncio.run(operation())


@then("the original short link redirects to that destination")
def redirect(flow):
    result = asyncio.run(flow["client"].get("/" + flow["link"]["short_code"]))
    assert result.status_code == 307 and result.headers["location"] == "https://example.com/launch"


@then("one durable activation email is waiting for delivery")
def queued(flow):
    assert len(flow["repository"].jobs) == 1
