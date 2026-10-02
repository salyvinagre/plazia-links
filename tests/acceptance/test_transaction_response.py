"""Management responses must not acknowledge a write before its transaction commits."""

import asyncio
from datetime import UTC, datetime
from time import time
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import IdentitySettings
from app.contexts.access.contracts import BrowserSession, Principal
from app.contexts.links.contracts import LinkView
from app.core.identity import api_principal, browser_session
from app.main import create_app
from app.platform.access import AccessRuntime
from tests.identity_support import MemoryState

CASES = [
    ("POST", "/api/v1/links", "json", {"destination_url": "https://example.com"}, 201),
    ("PATCH", "/api/v1/links/link", "json", {"notes": "updated"}, 200),
    ("DELETE", "/api/v1/links/link", "json", None, 204),
    (
        "POST",
        "/dashboard/links",
        "data",
        {"destination_url": "https://example.com", "csrf_token": "csrf-proof"},
        303,
    ),
    (
        "POST",
        "/dashboard/links/link",
        "data",
        {
            "destination_url": "https://example.com/updated",
            "is_active": "on",
            "csrf_token": "csrf-proof",
        },
        303,
    ),
    ("POST", "/dashboard/links/link/delete", "data", {"csrf_token": "csrf-proof"}, 303),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,encoding,payload,success_status", CASES)
@pytest.mark.parametrize("commit_fails", [False, True], ids=["commit", "rollback"])
async def test_management_transaction_finishes_before_response(
    monkeypatch, method, path, encoding, payload, success_status, commit_fails
):
    events = []
    session = AsyncMock()
    session.__aenter__.return_value = session

    async def commit():
        # Deliberately yield: neither connection speed nor browser timing may mask the race.
        await asyncio.sleep(0.01)
        if commit_fails:
            events.append("commit-failed")
            raise RuntimeError("simulated commit failure")
        events.append("committed")

    async def rollback():
        events.append("rolled-back")

    session.commit.side_effect = commit
    session.rollback.side_effect = rollback
    monkeypatch.setattr("app.core.dependencies.get_session_factory", lambda: lambda: session)

    config = IdentitySettings(
        _env_file=None,
        issuer="https://issuer.example",
        audience="https://links.example/api",
        client_id="browser",
        client_secret="test-client-secret",
        public_base_url="https://links.example",
    )
    principal = Principal(
        config.issuer,
        "subject",
        config.client_id,
        f"org_{uuid7()}",
        frozenset({"read:links", "create:links", "update:links", "delete:links"}),
        int(time()) + 300,
        "token-id",
    )
    browser = BrowserSession(principal, "csrf-proof", int(time()) + 300)
    application = create_app(
        auth_mode="identity", access=AccessRuntime.build(config, MemoryState())
    )

    async def authenticated_principal():
        return principal

    async def authenticated_session():
        return browser

    application.dependency_overrides[api_principal] = authenticated_principal
    application.dependency_overrides[browser_session] = authenticated_session
    manager = AsyncMock()
    link = LinkView(
        "link",
        "code1234",
        "https://example.com",
        None,
        None,
        True,
        datetime.now(UTC),
        datetime.now(UTC),
    )
    manager.create.return_value = link
    manager.update.return_value = link
    monkeypatch.setattr("app.api.managed_links.link_management", lambda db, actor: manager)
    monkeypatch.setattr("app.routes.identity.link_management", lambda db, actor: manager)

    async def observed_app(scope, receive, send):
        async def observed_send(message):
            if message["type"] == "http.response.start":
                events.append("response-start")
            await send(message)

        await application(scope, receive, observed_send)

    async with AsyncClient(
        transport=ASGITransport(app=observed_app, raise_app_exceptions=False),
        base_url=config.public_base_url,
    ) as client:
        kwargs = {encoding: payload} if payload is not None else {}
        response = await client.request(method, path, **kwargs)

    if commit_fails:
        assert response.status_code == 500
        assert events == ["commit-failed", "rolled-back", "response-start"]
        assert "location" not in response.headers
    else:
        assert response.status_code == success_status, response.text
        assert events == ["committed", "response-start"]
        session.rollback.assert_not_awaited()
    session.commit.assert_awaited_once()
