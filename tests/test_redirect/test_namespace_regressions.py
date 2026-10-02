import pytest

from app.models.domain import CustomDomain
from app.models.link import Link


@pytest.mark.asyncio
async def test_unknown_domain_cannot_resolve_global_code(client, db_session, test_workspace_id):
    db_session.add(
        Link(
            short_code="ns-unknown",
            destination_url="https://example.com",
            workspace_id=test_workspace_id,
        )
    )
    await db_session.flush()
    response = await client.get("http://unknown.example/ns-unknown", follow_redirects=False)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_verified_domain_cannot_resolve_another_workspaces_code(
    client, db_session, test_workspace_id, test_user_id
):
    from app.schemas.workspace import WorkspaceCreate
    from app.services.workspace_service import create_workspace

    other = await create_workspace(
        db_session, WorkspaceCreate(name="Other", slug="other-ns"), test_user_id
    )
    db_session.add(
        CustomDomain(
            workspace_id=test_workspace_id,
            domain="owned.example",
            verification_code="x",
            is_verified=True,
        )
    )
    db_session.add(
        Link(short_code="ns-other", destination_url="https://example.com", workspace_id=other.id)
    )
    await db_session.flush()
    response = await client.get("http://owned.example/ns-other", follow_redirects=False)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stale_cache_cannot_bypass_disabled_link(
    client, db_session, test_workspace_id, mock_redis
):
    mock_redis.get.return_value = "https://previous.example"
    db_session.add(
        Link(
            short_code="ns-disabled",
            destination_url="https://example.com",
            workspace_id=test_workspace_id,
            is_active=False,
        )
    )
    await db_session.flush()
    response = await client.get("/ns-disabled", follow_redirects=False)
    assert response.status_code == 410
