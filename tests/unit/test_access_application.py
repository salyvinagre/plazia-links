"""Access orchestration runs against typed ports, independently of protocol adapters."""

import time
from dataclasses import replace
from unittest.mock import AsyncMock, Mock
from uuid import uuid7

import pytest

from app.contexts.access.application.browser import BrowserAuth
from app.contexts.access.application.models import (
    LoginAttempt,
    TokenPair,
    WorkspaceBinding,
    WorkspaceView,
)
from app.contexts.access.application.workspaces import WorkspaceAccess, WorkspaceProvisioning
from app.contexts.access.domain.principal import BrowserSession, InvalidCredentialsError, Principal


@pytest.fixture
def browser():
    client = Mock()
    client.authorization_url.return_value = "https://issuer.example/authorize"
    client.redeem = AsyncMock(return_value=TokenPair("access-token", "id-token"))
    verifier, store = AsyncMock(), AsyncMock()
    principal = Principal(
        "https://issuer.example",
        "subject",
        "client",
        f"org_{uuid7()}",
        frozenset({"read:links"}),
        int(time.time()) + 600,
        "token-id",
    )
    verifier.access_token.return_value = principal
    verifier.id_token.return_value = int(time.time()) + 500
    store.take_attempt.return_value = LoginAttempt("pkce-verifier", "nonce", int(time.time()) + 60)
    return BrowserAuth("client", 300, client, verifier, store), client, verifier, store


@pytest.mark.asyncio
async def test_login_attempt_is_browser_bound_and_stored_as_a_typed_value(browser):
    auth, client, _, store = browser
    url, handle = await auth.begin()
    assert url.startswith("https://")
    key, attempt, ttl = store.put_attempt.await_args.args
    assert key.startswith(handle + ":") and len(handle) >= 32
    assert isinstance(attempt, LoginAttempt) and len(attempt.verifier) == 64
    assert ttl == 600
    assert client.authorization_url.call_args.args[0] == attempt.verifier


@pytest.mark.asyncio
async def test_session_lifetime_is_bounded_by_tokens_and_application_policy(browser):
    auth, client, verifier, _ = browser
    result = await auth.complete("h" * 32, "s" * 32, "authorization-code")
    assert result.expires_at <= int(time.time()) + 300
    assert result.expires_at <= verifier.id_token.return_value
    assert len(result.csrf_token) >= 32
    client.redeem.assert_awaited_once_with("authorization-code", "pkce-verifier")


@pytest.mark.asyncio
async def test_consumed_login_attempt_cannot_be_redeemed_twice(browser):
    auth, client, _, store = browser
    attempt = store.take_attempt.return_value
    store.take_attempt.side_effect = [attempt, None]
    await auth.complete("h" * 32, "s" * 32, "authorization-code")
    with pytest.raises(InvalidCredentialsError):
        await auth.complete("h" * 32, "s" * 32, "authorization-code")
    assert client.redeem.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", [{"confirmation_jkt": "bound-key"}, {"client_id": "another-client"}]
)
async def test_browser_policy_rejects_sender_bound_or_foreign_client_tokens(browser, change):
    auth, _, verifier, _ = browser
    verifier.access_token.return_value = replace(verifier.access_token.return_value, **change)
    with pytest.raises(InvalidCredentialsError):
        await auth.complete("h" * 32, "s" * 32, "code")
    verifier.id_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_session_is_removed_before_rejection(browser):
    auth, _, verifier, store = browser
    store.get_session.return_value = BrowserSession(verifier.access_token.return_value, "csrf", 1)
    with pytest.raises(InvalidCredentialsError):
        await auth.session("h" * 32)
    store.remove_session.assert_awaited_once_with("h" * 32)


@pytest.mark.asyncio
async def test_provisioning_idempotence_is_an_application_rule():
    bindings = AsyncMock()
    organization = f"org_{uuid7()}"
    bindings.find.return_value = WorkspaceBinding(WorkspaceView("workspace", "Name"), False)
    operator = WorkspaceProvisioning(bindings, "https://issuer.example")
    assert await operator.bind(organization, "Updated display name") == "workspace"
    bindings.set_active.assert_awaited_once_with("https://issuer.example", organization, True)
    bindings.create_workspace.assert_not_awaited()
    with pytest.raises(ValueError, match="different workspace"):
        await operator.bind(organization, "Name", "other-workspace")


@pytest.mark.asyncio
async def test_workspace_resolution_returns_a_view_not_an_orm_model():
    bindings = AsyncMock()
    expected = WorkspaceView("workspace", "Name")
    bindings.find.return_value = WorkspaceBinding(expected, True)
    principal = Principal(
        "https://issuer.example", "subject", "client", "organization", frozenset(), 100, "t"
    )
    assert await WorkspaceAccess(bindings).resolve(principal) == expected
