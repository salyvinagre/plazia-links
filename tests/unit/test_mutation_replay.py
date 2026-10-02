"""Retries preserve original outcomes, tenant authority and transactional durability."""

from unittest.mock import AsyncMock

import httpx
import pytest

from tests.identity_support import ORG_B


async def test_every_mutation_replays_original_result_and_audit_once(
    identity_client, issuer, identity_db
):
    headers = {"Authorization": "Bearer " + issuer.access(), "Idempotency-Key": "pool-1"}
    first = await identity_client.post("/api/v1/pools", headers=headers, json={"size": 2})
    second = await identity_client.post("/api/v1/pools", headers=headers, json={"size": 2})
    assert first.status_code == second.status_code == 201 and first.json() == second.json()
    assert first.headers["Idempotency-Replayed"] == "false"
    assert second.headers["Idempotency-Replayed"] == "true"
    assert len(identity_db.links) == 2 and len(identity_db.audits) == 1
    assert (await identity_client.post("/api/v1/pools", headers=headers, json={"size": 3})).json()[
        "code"
    ] == "idempotency_conflict"
    link = (await identity_client.get("/api/v1/links", headers=headers)).json()["items"][0]
    path = "/api/v1/links/" + link["id"]
    await identity_client.post(
        "/" + link["short_code"] + "/subscriptions", data={"email": "one@example.com"}
    )
    headers["Idempotency-Key"] = "activation-1"
    first = await identity_client.patch(
        path, headers=headers, json={"destination_url": "https://example.com/ready"}
    )
    second = await identity_client.patch(
        path, headers=headers, json={"destination_url": "https://example.com/ready"}
    )
    assert first.json() == second.json() and len(identity_db.jobs) == 1
    assert len(identity_db.audits) == 2
    headers["Idempotency-Key"] = "delete-1"
    assert (await identity_client.delete(path, headers=headers)).status_code == 204
    replay = await identity_client.delete(path, headers=headers)
    assert replay.status_code == 204 and replay.headers["Idempotency-Replayed"] == "true"
    assert len(identity_db.audits) == 3 and not identity_db.jobs
    headers["Idempotency-Key"] = "create-1"
    data = {"destination_url": "https://example.com/active"}
    one = await identity_client.post("/api/v1/links", headers=headers, json=data)
    two = await identity_client.post("/api/v1/links", headers=headers, json=data)
    assert one.json() == two.json() and len(identity_db.audits) == 4


async def test_replay_rolls_back_with_failed_commit_and_rechecks_authority(
    identity_client, issuer, database, identity_db, authority
):
    headers = {"Authorization": "Bearer " + issuer.access(), "Idempotency-Key": "recover-1"}
    database.commit_failure = True
    assert (
        await identity_client.post("/api/v1/pools", headers=headers, json={"size": 1})
    ).status_code == 500
    assert not identity_db.receipts and not identity_db.pool_rows
    database.commit_failure = False
    assert (
        await identity_client.post("/api/v1/pools", headers=headers, json={"size": 1})
    ).status_code == 201
    authority.allowed = False
    assert (
        await identity_client.post("/api/v1/pools", headers=headers, json={"size": 1})
    ).status_code == 403
    authority.allowed = True
    headers["Authorization"] = "Bearer " + issuer.access(org=ORG_B)
    another = await identity_client.post("/api/v1/pools", headers=headers, json={"size": 1})
    assert another.status_code == 201 and another.headers["Idempotency-Replayed"] == "false"


async def test_missing_or_invalid_key_is_a_context_error(application, issuer):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://127.0.0.1:8000"
    ) as client:
        for value in (None, "with space", "a" * 129):
            headers = {"Authorization": "Bearer " + issuer.access()}
            if value is not None:
                headers["Idempotency-Key"] = value
            response = await client.post("/api/v1/pools", headers=headers, json={"size": 1})
            assert (
                response.status_code == 400 and response.json()["code"] == "invalid_idempotency_key"
            )


@pytest.mark.parametrize("action", ["ReservePoolCommand", "CreateLinkCommand", "DeleteLinkCommand"])
async def test_sql_receipt_restores_original_typed_snapshot(action, issuer):
    import json
    from dataclasses import asdict
    from datetime import UTC, datetime

    from app.contexts.access.domain.principal import Principal
    from app.contexts.links.adapters.repositories.sql.postgres import PostgresLinkRepository
    from app.contexts.links.application.dto.links import LinkDto, PoolDto
    from app.kernel.ids import LinkId, PoolId
    from tests.identity_support import ORG_A
    from tests.unit.test_persistence_boundaries import _Cursor

    actor = Principal(issuer.url, "subject", "client", ORG_A, frozenset(), 1, "token")
    now = datetime.now(UTC)
    result = (
        PoolDto(PoolId.new(), "Launch", 2, now)
        if action == "ReservePoolCommand"
        else LinkDto(LinkId.new(), "code123", "https://example.com", None, None, True, now, now)
        if action == "CreateLinkCommand"
        else None
    )
    snapshot = {"value": json.loads(json.dumps(asdict(result), default=str)) if result else None}
    connection = AsyncMock()
    connection.execute.return_value = _Cursor(row=("digest", snapshot))
    repository = PostgresLinkRepository(connection)
    await repository.remember(actor, action, "key", result)
    replay = await repository.replay(actor, action, "key", "digest")
    assert replay.replayed and replay.value == result
    connection.execute.return_value = _Cursor(row=("digest", None))
    assert await repository.replay(actor, action, "key", "digest") is None
    from app.contexts.links.domain.link import IdempotencyConflictError

    with pytest.raises(IdempotencyConflictError):
        await repository.replay(actor, action, "key", "other")


def test_http_dispatch_uses_shared_context_and_preserves_valid_trace_lineage():
    from shared_kernel import RequestContext
    from starlette.requests import Request

    from app.interfaces.dispatch import request_context

    parent = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
    request = Request(
        {
            "type": "http",
            "headers": [
                (b"traceparent", parent.encode()),
                (b"tracestate", b"vendor=value"),
                (b"x-correlation-id", b"correlation-1"),
            ],
        }
    )
    request.state.request_id = "request-1"
    context = request_context(request)
    assert isinstance(context, RequestContext)
    assert context.traceparent == parent and context.tracestate == "vendor=value"
    assert context.request_id == "request-1" and context.correlation_id == "correlation-1"
