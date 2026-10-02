"""Regression tests for the imported baseline, not the future pool feature."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core.schema import expected_schema_heads, verify_schema
from app.services.link_access import verify_folder_workspace
from app.services.workspace_service import verify_workspace_access


def test_migration_history_has_one_head():
    assert len(expected_schema_heads()) == 1


@pytest.mark.asyncio
async def test_schema_check_rejects_an_unmigrated_database(monkeypatch):
    engine = AsyncMock()
    connection = AsyncMock()
    connection.run_sync.return_value = set()
    # AsyncEngine.connect() returns an async context manager, not a coroutine.
    engine.connect = lambda: SimpleAsyncContext(connection)
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        await verify_schema(engine)


class SimpleAsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_api_key_scopes_are_checked_before_owner_privileges(monkeypatch):
    monkeypatch.setattr(
        "app.services.workspace_service.get_workspace",
        AsyncMock(return_value=SimpleNamespace(owner_id="u")),
    )
    user = SimpleNamespace(id="u", _key_workspace_id="a", _key_permissions={"analytics:view"})
    with pytest.raises(HTTPException) as error:
        await verify_workspace_access(AsyncMock(), "a", user, required_permission="links:create")
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_api_key_cannot_access_another_workspace_owned_by_same_user(monkeypatch):
    monkeypatch.setattr(
        "app.services.workspace_service.get_workspace",
        AsyncMock(return_value=SimpleNamespace(owner_id="u")),
    )
    user = SimpleNamespace(id="u", _key_workspace_id="a", _key_permissions=None)
    with pytest.raises(HTTPException) as error:
        await verify_workspace_access(AsyncMock(), "b", user)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_unrestricted_api_key_still_works_in_its_own_workspace(monkeypatch):
    workspace = SimpleNamespace(owner_id="u")
    monkeypatch.setattr(
        "app.services.workspace_service.get_workspace", AsyncMock(return_value=workspace)
    )
    user = SimpleNamespace(id="u", _key_workspace_id="a", _key_permissions=None)
    assert await verify_workspace_access(AsyncMock(), "a", user) is workspace


@pytest.mark.asyncio
async def test_foreign_folder_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "app.services.link_access.get_folder",
        AsyncMock(return_value=SimpleNamespace(workspace_id="b")),
    )
    with pytest.raises(HTTPException) as error:
        await verify_folder_workspace(AsyncMock(), "folder-b", "a")
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_missing_folder_is_rejected(monkeypatch):
    monkeypatch.setattr("app.services.link_access.get_folder", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as error:
        await verify_folder_workspace(AsyncMock(), "missing", "a")
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_clearing_folder_needs_no_lookup(monkeypatch):
    lookup = AsyncMock()
    monkeypatch.setattr("app.services.link_access.get_folder", lookup)
    await verify_folder_workspace(AsyncMock(), None, "a")
    lookup.assert_not_called()
