from datetime import UTC, datetime

import pytest

from app.models.webhook import Webhook
from app.schemas.webhook import WebhookResponse


def test_webhook_serialization_does_not_erase_signing_secret():
    webhook = Webhook(
        id="w",
        workspace_id="a",
        name="test",
        url="https://example.com",
        events="click.created",
        is_active=True,
        max_retries=5,
        created_at=datetime.now(UTC),
        secret="must-survive",
    )
    result = WebhookResponse.model_validate(webhook)
    assert result.has_secret is True
    assert "secret" not in result.model_dump()
    assert webhook.secret == "must-survive"
    assert WebhookResponse.model_validate(webhook).has_secret is True


@pytest.mark.asyncio
async def test_link_list_openapi_has_typed_items(client):
    schema = (await client.get("/openapi.json")).json()
    response = schema["paths"]["/api/v1/links"]["get"]["responses"]["200"]
    ref = response["content"]["application/json"]["schema"]["$ref"]
    page = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    assert page["properties"]["items"]["items"]["$ref"].endswith("/LinkResponse")


@pytest.mark.asyncio
async def test_domain_delete_checks_parent_workspace(auth_client):
    import uuid

    async def workspace():
        result = await auth_client.post(
            "/api/v1/workspaces", json={"name": "test", "slug": uuid.uuid4().hex[:8]}
        )
        assert result.status_code == 201
        return result.json()["id"]

    a, b = await workspace(), await workspace()
    created = await auth_client.post(
        f"/api/v1/workspaces/{b}/domains", json={"domain": f"{uuid.uuid4().hex}.example.com"}
    )
    assert created.status_code == 201
    domain_id = created.json()["id"]
    wrong_parent = await auth_client.delete(f"/api/v1/workspaces/{a}/domains/{domain_id}")
    assert wrong_parent.status_code == 404
    listing = await auth_client.get(f"/api/v1/workspaces/{b}/domains")
    assert any(item["id"] == domain_id for item in listing.json()["items"])


@pytest.mark.asyncio
async def test_domain_verification_checks_parent_workspace(auth_client):
    import uuid

    ids = []
    for _ in range(2):
        result = await auth_client.post(
            "/api/v1/workspaces", json={"name": "test", "slug": uuid.uuid4().hex[:8]}
        )
        ids.append(result.json()["id"])
    a, b = ids
    created = await auth_client.post(
        f"/api/v1/workspaces/{b}/domains", json={"domain": f"{uuid.uuid4().hex}.example.com"}
    )
    data = created.json()
    result = await auth_client.post(
        f"/api/v1/workspaces/{a}/domains/{data['id']}/verify",
        json={"verification_code": data["verification_code"]},
    )
    assert result.status_code == 404
