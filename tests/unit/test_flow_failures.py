"""User-visible failure contracts at the shared dispatch boundary."""

from unittest.mock import AsyncMock

import pytest

from app.contexts.links.domain.link import LinkConflictError, PublicCode
from tests.identity_support import ORG_B


def auth(issuer, **kwargs):
    return {"Authorization": "Bearer " + issuer.access(**kwargs)}


async def reserved(client, issuer):
    pool = await client.post("/api/v1/pools", headers=auth(issuer), json={"size": 1})
    assert pool.status_code == 201, pool.text
    result = await client.get(
        "/api/v1/links", headers=auth(issuer), params={"pool_id": pool.json()["id"]}
    )
    return pool.json(), result.json()["items"][0]


async def test_failed_commit_never_acknowledges_or_leaves_pool_rows(
    identity_client, issuer, database, identity_db
):
    database.commit_failure = True
    result = await identity_client.post("/api/v1/pools", headers=auth(issuer), json={"size": 3})
    assert result.status_code == 500
    assert identity_db.pool_rows == {} and identity_db.links == {} and identity_db.audits == []


async def test_authority_denial_precedes_all_repository_reads(
    identity_client, issuer, authority, database
):
    authority.allowed = False
    before = database.scope_count
    assert (await identity_client.get("/api/v1/links", headers=auth(issuer))).status_code == 403
    assert database.scope_count == before


async def test_pool_ownership_cannot_be_selected_or_enumerated(identity_client, issuer):
    pool, link = await reserved(identity_client, issuer)
    assert (
        await identity_client.get(
            "/api/v1/links", headers=auth(issuer, org=ORG_B), params={"pool_id": pool["id"]}
        )
    ).status_code == 404
    assert (
        await identity_client.post(
            "/api/v1/pools", headers=auth(issuer), json={"size": 1, "organization_id": ORG_B}
        )
    ).status_code == 422
    assert (await identity_client.get("/api/v1/pools", headers=auth(issuer))).json()["total"] == 1


@pytest.mark.parametrize("size", [0, 101, True, "2", 1.5])
async def test_pool_size_is_strict_and_bounded(identity_client, issuer, size):
    assert (
        await identity_client.post("/api/v1/pools", headers=auth(issuer), json={"size": size})
    ).status_code == 422


async def test_activation_failure_rolls_back_destination_jobs_and_audit(
    identity_client, issuer, database, identity_db
):
    pool, link = await reserved(identity_client, issuer)
    await identity_client.post(
        "/" + link["short_code"] + "/subscriptions", data={"email": "one@example.com"}
    )
    count = len(identity_db.audits)
    database.commit_failure = True
    response = await identity_client.patch(
        "/api/v1/links/" + link["id"],
        headers=auth(issuer),
        json={"destination_url": "https://example.com/ready"},
    )
    assert response.status_code == 500
    assert len(identity_db.audits) == count and not identity_db.jobs
    assert "coming soon" in (await identity_client.get("/" + link["short_code"])).text


async def test_activation_retries_and_later_edits_queue_only_once(
    identity_client, issuer, identity_db
):
    pool, link = await reserved(identity_client, issuer)
    for email in ("One@EXAMPLE.com", "One@example.com", "two@example.com"):
        assert (
            await identity_client.post(
                "/" + link["short_code"] + "/subscriptions", data={"email": email}
            )
        ).status_code == 200
    for target in ("ready", "edit"):
        result = await identity_client.patch(
            "/api/v1/links/" + link["id"],
            headers=auth(issuer),
            json={"destination_url": "https://example.com/" + target},
        )
        assert result.status_code == 200, result.text
    assert len(identity_db.jobs) == 2
    late = await identity_client.post(
        "/" + link["short_code"] + "/subscriptions", data={"email": "late@example.com"}
    )
    assert "This link is ready" in late.text and len(identity_db.subscriptions) == 2


async def test_disabled_link_requires_enabling_before_activation(identity_client, issuer):
    pool, link = await reserved(identity_client, issuer)
    path = "/api/v1/links/" + link["id"]
    assert (
        await identity_client.patch(path, headers=auth(issuer), json={"is_active": False})
    ).status_code == 200
    assert (await identity_client.get("/" + link["short_code"])).status_code == 410
    assert (
        await identity_client.post(
            "/" + link["short_code"] + "/subscriptions", data={"email": "one@example.com"}
        )
    ).status_code == 410
    assert (
        await identity_client.patch(
            path, headers=auth(issuer), json={"destination_url": "https://example.com/ready"}
        )
    ).status_code == 422
    assert (
        await identity_client.patch(
            path,
            headers=auth(issuer),
            json={"destination_url": "https://example.com/ready", "is_active": True},
        )
    ).status_code == 200


async def test_delete_cancels_subscriptions_and_jobs(identity_client, issuer, identity_db):
    pool, link = await reserved(identity_client, issuer)
    await identity_client.post(
        "/" + link["short_code"] + "/subscriptions", data={"email": "one@example.com"}
    )
    await identity_client.patch(
        "/api/v1/links/" + link["id"],
        headers=auth(issuer),
        json={"destination_url": "https://example.com/ready"},
    )
    assert (
        await identity_client.delete("/api/v1/links/" + link["id"], headers=auth(issuer))
    ).status_code == 204
    assert not identity_db.jobs and not identity_db.subscriptions
    assert (await identity_client.get("/" + link["short_code"])).status_code == 404


async def test_anonymous_origin_email_and_host_validation(identity_client, issuer):
    _, link = await reserved(identity_client, issuer)
    path = "/" + link["short_code"] + "/subscriptions"
    assert (await identity_client.post(path, data={"email": "bad"})).status_code == 422
    assert (
        await identity_client.post(
            path, data={"email": "one@example.com"}, headers={"Origin": "https://evil.test"}
        )
    ).status_code == 403
    assert (
        await identity_client.get("/" + link["short_code"], headers={"Host": "foreign.test"})
    ).status_code == 404


async def test_generated_code_retry_is_bounded_and_atomic(
    identity_client, issuer, identity_db, monkeypatch
):
    monkeypatch.setattr(PublicCode, "generate", lambda: "collision")
    identity_db.reserve = reserve = AsyncMock(side_effect=LinkConflictError)
    result = await identity_client.post("/api/v1/pools", headers=auth(issuer), json={"size": 1})
    assert result.status_code == 409 and reserve.await_count == 5
    assert not identity_db.pool_rows


async def test_create_code_retry_and_exhaustion(identity_client, issuer, identity_db):
    create = identity_db.create
    identity_db.create = create_mock = AsyncMock(side_effect=[LinkConflictError, LinkConflictError])
    result = await identity_client.post(
        "/api/v1/links",
        headers=auth(issuer),
        json={"destination_url": "https://example.com", "short_code": "custom"},
    )
    assert result.status_code == 409 and create_mock.await_count == 1
    identity_db.create = create_mock = AsyncMock(side_effect=LinkConflictError)
    result = await identity_client.post(
        "/api/v1/links", headers=auth(issuer), json={"destination_url": "https://example.com"}
    )
    assert result.status_code == 409 and create_mock.await_count == 5
    identity_db.create = create
