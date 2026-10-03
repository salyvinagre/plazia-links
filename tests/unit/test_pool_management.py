"""Organization-scoped pool lifecycle and explicit, atomic link selections."""

import pytest

from app.kernel.ids import LinkId
from tests.acceptance.test_identity_links import bearer
from tests.identity_support import ORG_B


async def pool_with_links(client, headers, name="Launch", size=3):
    response = await client.post(
        "/api/v1/pools", headers=headers, json={"name": name, "size": size}
    )
    assert response.status_code == 201
    pool = response.json()
    assert response.headers["Location"] == f"/api/v1/pools/{pool['id']}"
    rows = await client.get("/api/v1/links", headers=headers, params={"pool_id": pool["id"]})
    return pool, rows.json()["items"]


async def test_link_state_requires_a_json_boolean(identity_client, issuer):
    headers = bearer(issuer)
    _, rows = await pool_with_links(identity_client, headers, size=1)
    path = f"/api/v1/links/{rows[0]['id']}"
    for value in ("false", "yes", 0, 1):
        response = await identity_client.patch(path, headers=headers, json={"is_active": value})
        assert response.status_code == 422
    assert (await identity_client.get(path, headers=headers)).json()["is_active"] is True
    assert (await identity_client.patch(path, headers=headers, json={"is_active": False})).json()[
        "is_active"
    ] is False


def test_link_selection_command_requires_one_explicit_mode(issuer):
    from app.contexts.access.contracts import Principal
    from app.contexts.links.contracts import DeleteLinksCommand
    from app.kernel.ids import PoolId
    from tests.identity_support import ORG_A

    actor = Principal(issuer.url, "user", "client", ORG_A, frozenset(), 1, "token")
    for ids, all in (((PoolId.new(),), False), ((), False), ((LinkId.new(),), True), ((), "true")):
        with pytest.raises(ValueError):
            DeleteLinksCommand(actor, ids, all=all)


async def test_rename_preserves_links_and_replays_original_name(
    identity_client, issuer, identity_db
):
    headers = bearer(issuer)
    pool, rows = await pool_with_links(identity_client, headers)
    path = f"/api/v1/pools/{pool['id']}"
    rename = {**headers, "Idempotency-Key": "rename-once"}
    first = await identity_client.patch(path, headers=rename, json={"name": "Renamed"})
    assert first.status_code == 200 and first.json()["name"] == "Renamed"
    assert first.json()["size"] == 3
    assert (
        await identity_client.patch(path, headers=headers, json={"name": "Later"})
    ).status_code == 200
    replay = await identity_client.patch(path, headers=rename, json={"name": "Renamed"})
    assert replay.json() == first.json() and replay.headers["Idempotency-Replayed"] == "true"
    assert (await identity_client.get(path, headers=headers)).json()["name"] == "Later"
    assert (
        await identity_client.patch(path, headers=rename, json={"name": "Conflict"})
    ).status_code == 409
    assert set(identity_db.links) == {LinkId(row["id"]) for row in rows}
    cleared = await identity_client.patch(path, headers=headers, json={"name": None})
    assert cleared.status_code == 200 and not cleared.json().get("name")


@pytest.mark.parametrize(
    "payload", [{}, {"name": "x" * 201}, {"name": 1}, {"name": "Ok", "size": 2}]
)
async def test_rename_rejects_invalid_or_unrelated_fields(identity_client, issuer, payload):
    headers = bearer(issuer)
    pool, _ = await pool_with_links(identity_client, headers)
    path = f"/api/v1/pools/{pool['id']}"
    assert (await identity_client.patch(path, headers=headers, json=payload)).status_code == 422
    assert (await identity_client.get(path, headers=headers)).json()["name"] == "Launch"


async def test_delete_pool_cancels_children_and_replays_without_touching_other_pools(
    identity_client, issuer, identity_db
):
    headers = bearer(issuer)
    pool, rows = await pool_with_links(identity_client, headers)
    other, remaining = await pool_with_links(identity_client, headers, "Keep", 1)
    for row in rows[:2]:
        await identity_client.post(
            f"/{row['short_code']}/subscriptions", data={"email": "one@example.com"}
        )
    await identity_client.patch(
        f"/api/v1/links/{rows[0]['id']}",
        headers=headers,
        json={"destination_url": "https://example.com/ready"},
    )
    assert identity_db.subscriptions and identity_db.jobs
    path = f"/api/v1/pools/{pool['id']}"
    deleting = {**headers, "Idempotency-Key": "delete-pool"}
    assert (await identity_client.delete(path, headers=deleting)).status_code == 204
    audit_count = len(identity_db.audits)
    replay = await identity_client.delete(path, headers=deleting)
    assert replay.status_code == 204 and replay.headers["Idempotency-Replayed"] == "true"
    assert len(identity_db.audits) == audit_count
    assert not identity_db.subscriptions and not identity_db.jobs
    assert (await identity_client.get(path, headers=headers)).status_code == 404
    assert (await identity_client.get(f"/api/v1/pools/{other['id']}", headers=headers)).json()[
        "size"
    ] == 1
    assert set(identity_db.links) == {LinkId(remaining[0]["id"])}
    for row in rows:
        assert (await identity_client.get(f"/{row['short_code']}")).status_code == 404


async def test_pool_authority_and_organization_isolation(identity_client, issuer):
    headers = bearer(issuer)
    pool, rows = await pool_with_links(identity_client, headers)
    path = f"/api/v1/pools/{pool['id']}"
    foreign = bearer(issuer, org=ORG_B)
    assert (await identity_client.get(path, headers=foreign)).status_code == 404
    assert (
        await identity_client.patch(path, headers=foreign, json={"name": "Foreign"})
    ).status_code == 404
    assert (await identity_client.delete(path, headers=foreign)).status_code == 404
    reader = bearer(issuer, scopes="links:read")
    assert (
        await identity_client.patch(path, headers=reader, json={"name": "Denied"})
    ).status_code == 403
    assert (await identity_client.delete(path, headers=reader)).status_code == 403
    assert (
        await identity_client.delete(
            "/api/v1/links", headers=reader, params={"ids": [rows[0]["id"]]}
        )
    ).status_code == 403
    assert (
        await identity_client.delete("/api/v1/links", headers=reader, params={"all": "true"})
    ).status_code == 403
    assert (
        await identity_client.delete(
            "/api/v1/links", headers=foreign, params={"all": "true", "pool_id": pool["id"]}
        )
    ).status_code == 404
    assert (await identity_client.get(path, headers=headers)).json()["size"] == 3


async def test_bulk_delete_is_explicit_and_preserves_pool_filter_and_unselected_links(
    identity_client, issuer, identity_db
):
    headers = bearer(issuer)
    pool, rows = await pool_with_links(identity_client, headers)
    selected = {"ids": [row["id"] for row in rows[:2]], "pool_id": pool["id"]}
    deleting = {**headers, "Idempotency-Key": "selection"}
    assert (
        await identity_client.delete("/api/v1/links", headers=deleting, params=selected)
    ).status_code == 204
    replay = await identity_client.delete("/api/v1/links", headers=deleting, params=selected)
    assert replay.status_code == 204 and replay.headers["Idempotency-Replayed"] == "true"
    assert set(identity_db.links) == {LinkId(rows[2]["id"])}
    assert (await identity_client.get(f"/api/v1/pools/{pool['id']}", headers=headers)).json()[
        "size"
    ] == 1
    assert len([event for event in identity_db.audits if event[1] == "delete"]) == 2


async def test_bulk_delete_rolls_back_stale_foreign_and_wrong_pool_selections(
    identity_client, issuer, identity_db, database
):
    headers = bearer(issuer)
    pool, rows = await pool_with_links(identity_client, headers)
    foreign, other = await pool_with_links(identity_client, bearer(issuer, org=ORG_B))
    local, outside = await pool_with_links(identity_client, headers)
    for id, pool_id in (
        (other[0]["id"], None),
        (str(LinkId.new()), None),
        (outside[0]["id"], pool["id"]),
    ):
        before = set(identity_db.links), len(identity_db.audits), len(identity_db.receipts)
        params = {"ids": [rows[0]["id"], id]}
        if pool_id:
            params["pool_id"] = pool_id
        assert (
            await identity_client.delete("/api/v1/links", headers=headers, params=params)
        ).status_code == 404
        assert before == (
            set(identity_db.links),
            len(identity_db.audits),
            len(identity_db.receipts),
        )
    database.commit_failure = True
    for params in ({"ids": [rows[0]["id"]]}, {"all": "true", "pool_id": pool["id"]}):
        before = set(identity_db.links), len(identity_db.audits), len(identity_db.receipts)
        assert (
            await identity_client.delete("/api/v1/links", headers=headers, params=params)
        ).status_code == 500
        assert before == (
            set(identity_db.links),
            len(identity_db.audits),
            len(identity_db.receipts),
        )


@pytest.mark.parametrize(
    "params",
    [
        {"ids": []},
        {"ids": ["invalid"]},
        {"ids": [str(LinkId.new())] * 2},
        {"ids": [str(LinkId.new())] * 101},
        {"all": "true", "ids": [str(LinkId.new())]},
        {"all": "false"},
        {"all": "invalid"},
    ],
)
async def test_bulk_delete_rejects_unbounded_or_ambiguous_selections(
    identity_client, issuer, params
):
    assert (
        await identity_client.delete("/api/v1/links", headers=bearer(issuer), params=params)
    ).status_code == 422


@pytest.mark.parametrize("filtered", [True, False])
async def test_delete_all_spans_pages_preserves_pools_and_replays_without_deleting_new_links(
    identity_client, issuer, identity_db, filtered
):
    client, headers = identity_client, bearer(issuer)
    pool, rows = await pool_with_links(client, headers, size=100)
    other, _ = await pool_with_links(client, headers, "Keep", 100)
    foreign, _ = await pool_with_links(client, bearer(issuer, org=ORG_B))
    await client.post(
        "/api/v1/links", headers=headers, json={"destination_url": "https://example.com/standalone"}
    )
    await client.post(f"/{rows[0]['short_code']}/subscriptions", data={"email": "one@example.com"})
    await client.patch(
        f"/api/v1/links/{rows[0]['id']}",
        headers=headers,
        json={"destination_url": "https://example.com/active"},
    )
    params = {"all": "true", **({"pool_id": pool["id"]} if filtered else {})}
    deleting = {**headers, "Idempotency-Key": "all-links"}
    assert (
        await client.delete("/api/v1/links", headers=deleting, params=params)
    ).status_code == 204
    assert (await client.get("/api/v1/links", headers=headers)).json()["total"] == (
        101 if filtered else 0
    )
    assert (await client.get(f"/api/v1/pools/{pool['id']}", headers=headers)).json()["size"] == 0
    assert (await client.get(f"/api/v1/pools/{other['id']}", headers=headers)).json()["size"] == (
        100 if filtered else 0
    )
    assert (
        await client.get(f"/api/v1/pools/{foreign['id']}", headers=bearer(issuer, org=ORG_B))
    ).json()["size"] == 3
    assert not identity_db.subscriptions and not identity_db.jobs
    audits = len([event for event in identity_db.audits if event[1] == "delete"])
    assert audits == (100 if filtered else 201)
    created = await client.post(
        "/api/v1/links", headers=headers, json={"destination_url": "https://example.com/new"}
    )
    replay = await client.delete("/api/v1/links", headers=deleting, params=params)
    assert replay.status_code == 204 and replay.headers["Idempotency-Replayed"] == "true"
    assert (
        await client.get(f"/api/v1/links/{created.json()['id']}", headers=headers)
    ).status_code == 200
    assert len([event for event in identity_db.audits if event[1] == "delete"]) == audits
    conflict = await client.delete(
        "/api/v1/links", headers=deleting, params={"ids": [created.json()["id"]]}
    )
    assert conflict.status_code == 409


async def test_openapi_pool_and_selection_contract(identity_client):
    schema = (await identity_client.get("/openapi.json")).json()
    for path, methods in {
        "/api/v1/pools/{pool_id}": {
            "get": "links:read",
            "patch": "links:update",
            "delete": "links:delete",
        },
        "/api/v1/links": {"delete": "links:delete"},
    }.items():
        for method, scope in methods.items():
            operation = schema["paths"][path][method]
            assert operation["security"] == [{"OAuth2AuthorizationCodeBearer": [scope]}]
            assert not any(
                parameter["name"] in {"org", "organization_id", "offset", "page"}
                for parameter in operation["parameters"]
            )
            if method != "get":
                assert any(
                    parameter["name"] == "Idempotency-Key" and parameter["required"]
                    for parameter in operation["parameters"]
                )
                assert (
                    "204" in operation["responses"]
                    if method == "delete"
                    else "200" in operation["responses"]
                )
    bulk = schema["paths"]["/api/v1/links"]["delete"]
    ids = next(parameter for parameter in bulk["parameters"] if parameter["name"] == "ids")
    items = next(option for option in ids["schema"]["anyOf"] if option["type"] == "array")
    assert ids["in"] == "query" and items["maxItems"] == 100 and items["minItems"] == 1
    assert not ids["required"]
    all_links = next(parameter for parameter in bulk["parameters"] if parameter["name"] == "all")
    assert all_links["in"] == "query" and all_links["schema"]["default"] is False
    assert "requestBody" not in bulk
    assert items["items"]["minLength"] == items["items"]["maxLength"] == 36
    for name in ("LinkResponse", "PoolResponse"):
        fields = schema["components"]["schemas"][name]["properties"]
        assert fields["id"]["minLength"] == fields["id"]["maxLength"] == 36
        assert fields["created_at"]["format"] == "date-time"
    rename = schema["components"]["schemas"]["RenamePoolRequest"]
    assert rename["additionalProperties"] is False and rename["required"] == ["name"]
