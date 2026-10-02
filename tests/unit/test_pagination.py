"""Shared navigation tokens remain tied to the authenticated collection query."""

import pytest
from shared_http import PageTokenCodec, PageTokenError

from app.interfaces.api.schemas.links import Pagination
from tests.identity_support import ORG_B


async def test_forward_navigation_is_bounded_and_scope_bound(identity_client, issuer):
    headers = {"Authorization": "Bearer " + issuer.access()}
    for name in ("First", "Second", "Third"):
        assert (
            await identity_client.post(
                "/api/v1/pools", headers=headers, json={"size": 2, "name": name}
            )
        ).status_code == 201
    first = (await identity_client.get("/api/v1/pools?limit=2", headers=headers)).json()
    assert len(first["items"]) == 2 and first["total"] == 3
    assert first["_links"]["self"]["href"] == "/api/v1/pools?limit=2"
    next_url = first["_links"]["next"]["href"]
    last = (await identity_client.get(next_url, headers=headers)).json()
    assert len(last["items"]) == 1 and "next" not in last["_links"]
    assert last["_links"]["first"]["href"] == "/api/v1/pools?limit=2"
    assert not {item["id"] for item in first["items"]} & {item["id"] for item in last["items"]}
    assert (
        await identity_client.get(
            next_url, headers={"Authorization": "Bearer " + issuer.access(org=ORG_B)}
        )
    ).status_code == 422
    assert (
        await identity_client.get(next_url.replace("limit=2", "limit=3"), headers=headers)
    ).status_code == 422
    assert (
        await identity_client.get(next_url.replace("/pools", "/links"), headers=headers)
    ).status_code == 422
    for params in ({"token": "!!!"}, {"page": 1}, {"limit": 101}):
        assert (
            await identity_client.get("/api/v1/pools", params=params, headers=headers)
        ).status_code == 422
    pool = first["items"][0]["id"]
    rows = (
        await identity_client.get(
            "/api/v1/links", headers=headers, params={"pool_id": pool, "limit": 1}
        )
    ).json()
    continuation = rows["_links"]["next"]["href"]
    assert len((await identity_client.get(continuation, headers=headers)).json()["items"]) == 1
    assert (
        await identity_client.get(
            continuation.replace(pool, first["items"][1]["id"]), headers=headers
        )
    ).status_code == 422


def test_invalid_shared_token_position_cannot_select_unbounded_offset(issuer):
    from app.contexts.access.domain.principal import Principal
    from tests.identity_support import ORG_A

    actor = Principal(issuer.url, "user", "client", ORG_A, frozenset(), 1, "token")
    for position in ("0", "-1", "100001", "abc", "٣"):
        token = PageTokenCodec.encode(
            kind="pools", bindings=Pagination().bindings(actor), position=(position,)
        )
        with pytest.raises(PageTokenError):
            Pagination(token=token).page(actor, "pools")
