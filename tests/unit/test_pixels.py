"""Pixels belong to email deliveries, independently of link activation and clicks."""

import asyncio
import struct
from unittest.mock import AsyncMock, Mock

import pytest

from app.contexts.links.contracts import PixelCode, PixelDraft
from tests.identity_support import ORG_A, ORG_B, bearer


@pytest.mark.parametrize("exhausted", [False, True])
async def test_code_collisions_retry_without_audit_or_receipt_duplication(
    identity_client, issuer, identity_db, monkeypatch, exhausted
):
    monkeypatch.setattr(PixelCode, "generate", Mock(return_value="a" * 32))
    assert (
        await identity_client.post("/api/v1/pixels", headers=bearer(issuer), json={})
    ).status_code == 201
    generator = Mock(side_effect=["a" * 32] * (5 if exhausted else 1) + ["b" * 32])
    monkeypatch.setattr(PixelCode, "generate", generator)
    headers = bearer(issuer) | {"Idempotency-Key": "collision-case"}
    response = await identity_client.post("/api/v1/pixels", headers=headers, json={})
    assert response.status_code == (409 if exhausted else 201)
    assert generator.call_count == (5 if exhausted else 2)
    assert len(identity_db.audits) == len(identity_db.pixel_rows) == (1 if exhausted else 2)
    monkeypatch.setattr(PixelCode, "generate", Mock(return_value="c" * 32))
    retried = await identity_client.post("/api/v1/pixels", headers=headers, json={})
    assert retried.status_code == 201
    assert retried.headers.get("Idempotency-Replayed", "false") == str(not exhausted).lower()


async def test_delivery_statistics_and_replay(identity_client, issuer, identity_db):
    headers = bearer(issuer) | {"Idempotency-Key": "delivery-1842"}
    created = await identity_client.post(
        "/api/v1/pixels", headers=headers, json={"reference": " delivery-1842 "}
    )
    assert created.status_code == 201
    value = created.json()
    path = "/api/v1/pixels/" + value["id"]
    assert value["id"].startswith("lpx_") and created.headers["Location"] == path
    assert value["reference"] == "delivery-1842" and "statistics" not in value
    assert (await identity_client.get(path, headers=headers)).json()["statistics"]["requests"] == 0
    head = await identity_client.head(value["image_url"])
    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-type"] == "image/gif" and int(head.headers["content-length"]) > 0
    for _ in range(3):
        image = await identity_client.get(value["image_url"])
        assert image.status_code == 200 and image.headers["content-type"] == "image/gif"
        assert image.content[:6] == b"GIF89a" and struct.unpack("<HH", image.content[6:10]) == (
            1,
            1,
        )
        assert image.headers["cache-control"] == "no-store"
        assert not any(name in image.headers for name in ("etag", "set-cookie", "location"))
    read = (await identity_client.get(path, headers=headers)).json()
    stats = read["statistics"]
    assert stats["requests"] == 3
    assert (
        read["created_at"]
        <= stats["first_requested_at"]
        <= stats["last_requested_at"]
        <= stats["as_of"]
    )
    replay = await identity_client.post(
        "/api/v1/pixels", headers=headers, json={"reference": " delivery-1842 "}
    )
    assert replay.json() == value and replay.headers["Idempotency-Replayed"] == "true"
    assert len(identity_db.audits) == 1
    conflict = await identity_client.post(
        "/api/v1/pixels", headers=headers, json={"reference": "different"}
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "idempotency_conflict"
    # An image request never creates a link or increments redirect/waiting statistics.
    totals = (await identity_client.get("/api/v1/statistics", headers=headers)).json()
    assert totals["redirects"] == totals["waiting_views"] == 0
    deleted = await identity_client.delete(path, headers=headers)
    assert deleted.status_code == 204
    assert (await identity_client.delete(path, headers=headers)).headers[
        "Idempotency-Replayed"
    ] == "true"
    assert (await identity_client.get(value["image_url"])).status_code == 404
    assert (await identity_client.get(path, headers=headers)).status_code == 404
    assert len(identity_db.audits) == 2
    # Creation replay retains its original result even after deletion.
    assert (
        await identity_client.post(
            "/api/v1/pixels", headers=headers, json={"reference": " delivery-1842 "}
        )
    ).json() == value


async def test_scope_pagination_and_read_authority(identity_client, issuer, authority):
    headers = bearer(issuer)
    items = []
    for index in range(3):
        items.append(
            (
                await identity_client.post(
                    "/api/v1/pixels", headers=headers, json={"reference": f"delivery-{index}"}
                )
            ).json()
        )
    page = (await identity_client.get("/api/v1/pixels?limit=2", headers=headers)).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert page["items"][0]["id"] == items[-1]["id"]
    next_page = (await identity_client.get(page["_links"]["next"]["href"], headers=headers)).json()
    assert len(next_page["items"]) == 1 and "next" not in next_page["_links"]
    path = "/api/v1/pixels/" + items[0]["id"]
    other = bearer(issuer, org=ORG_B)
    assert (await identity_client.get("/api/v1/pixels", headers=other)).json()["total"] == 0
    assert (await identity_client.get(path, headers=other)).status_code == 404
    assert (await identity_client.delete(path, headers=other)).status_code == 404
    assert (
        await identity_client.get(page["_links"]["next"]["href"], headers=other)
    ).status_code == 400
    assert (await identity_client.get(path)).status_code == 401
    assert (
        await identity_client.get(path, headers=bearer(issuer, scope="links:create"))
    ).status_code == 403
    assert (
        await identity_client.post(
            "/api/v1/pixels", headers=bearer(issuer, scope="links:read"), json={}
        )
    ).status_code == 403
    authority.allowed = False
    assert (await identity_client.get(path, headers=headers)).status_code == 403
    # Public delivery is independent of bearer credentials.
    assert (await identity_client.get(items[0]["image_url"])).status_code == 200


@pytest.mark.parametrize("failure", ["write", "timeout", "commit"])
async def test_capture_failure_keeps_image_and_rolls_back(
    identity_client, issuer, database, monkeypatch, failure, caplog
):
    headers = bearer(issuer)
    pixel = (await identity_client.post("/api/v1/pixels", headers=headers, json={})).json()
    if failure == "write":
        monkeypatch.setattr(
            database.pixels, "record", AsyncMock(side_effect=RuntimeError("private recipient"))
        )
    elif failure == "timeout":

        async def blocked(*_):
            await asyncio.sleep(10)

        monkeypatch.setattr(database.pixels, "record", blocked)
    else:
        database.commit_failure = True
    response = await identity_client.get(pixel["image_url"])
    assert response.status_code == 200 and response.content.startswith(b"GIF89a")
    assert "private recipient" not in caplog.text
    database.commit_failure = False
    assert (await identity_client.get("/api/v1/pixels/" + pixel["id"], headers=headers)).json()[
        "statistics"
    ]["requests"] == 0


async def test_contract_validation_host_and_replay_revocation(identity_client, issuer, identity_db):
    headers = bearer(issuer) | {"Idempotency-Key": "revoked-pixel"}
    assert (
        await identity_client.post("/api/v1/pixels", headers=headers, json={"reference": "x" * 201})
    ).status_code == 422
    assert (
        await identity_client.post(
            "/api/v1/pixels", headers=headers, json={"organization_id": ORG_B}
        )
    ).status_code == 422
    created = (await identity_client.post("/api/v1/pixels", headers=headers, json={})).json()
    assert created["reference"] is None
    assert (
        await identity_client.get(created["image_url"], headers={"Host": "other.example"})
    ).status_code == 404
    assert (await identity_client.get("/pixels/" + "a" * 32 + ".gif")).status_code == 404
    from dataclasses import replace

    from shared_identity import OrganizationId

    org = OrganizationId(ORG_A)
    identity_db.bindings[org] = replace(identity_db.bindings[org], is_active=False)
    assert (
        await identity_client.post("/api/v1/pixels", headers=headers, json={})
    ).status_code == 403


def test_normalized_domain_inputs_and_openapi(application):
    assert PixelDraft("  delivery-1  ").reference == "delivery-1"
    assert PixelDraft("  ").reference is None
    assert len(PixelCode.generate()) == 32
    with pytest.raises(ValueError):
        PixelDraft("x" * 201)
    with pytest.raises(ValueError):
        PixelCode("short")
    document = application.openapi()
    for path in ("/api/v1/pixels", "/api/v1/pixels/{pixel_id}"):
        assert path in document["paths"]
        for operation in document["paths"][path].values():
            assert operation["security"]
            assert not any(
                p["name"] in {"page", "offset", "organization_id"}
                for p in operation.get("parameters", [])
            )
    assert "statistics" not in document["components"]["schemas"]["PixelResponse"]["properties"]
    assert "statistics" in document["components"]["schemas"]["PixelReadResponse"]["properties"]
    assert not any(path.startswith("/pixels/") for path in document["paths"])
