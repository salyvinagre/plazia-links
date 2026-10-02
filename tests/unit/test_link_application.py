"""Use-case policies are tested through ports, without HTTP, SQL or Redis."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.contexts.access.contracts import AccessDeniedError, Principal, WorkspaceView
from app.contexts.links.application.management import LinkManagement
from app.contexts.links.application.models import LinkPage, LinkView
from app.contexts.links.domain.link import (
    Destination,
    InvalidLinkError,
    LinkConflictError,
    LinkDraft,
    LinkPatch,
    PublicCode,
)


def principal(scopes=frozenset({"read:links", "create:links", "update:links", "delete:links"})):
    return Principal(
        "https://issuer.example", "user", "client", "org-fixture", scopes, 9999999999, "id"
    )


def view():
    return LinkView(
        "link",
        "code1234",
        "https://example.com",
        None,
        None,
        True,
        datetime.now(UTC),
        datetime.now(UTC),
    )


@pytest.fixture
def service():
    resolver, repository, audit = AsyncMock(), AsyncMock(), AsyncMock()
    resolver.resolve.return_value = WorkspaceView("workspace", "Tenant")
    repository.create.return_value = view()
    repository.update.return_value = view()
    repository.list.return_value = LinkPage([], 0, 1, 20, False)
    return LinkManagement(principal(), resolver, repository, audit), resolver, repository, audit


@pytest.mark.asyncio
async def test_scope_denial_never_resolves_tenant_or_touches_storage(service):
    manager, resolver, repository, audit = service
    manager.principal = principal(frozenset())
    with pytest.raises(AccessDeniedError):
        await manager.create(LinkDraft("https://example.com"))
    resolver.resolve.assert_not_awaited()
    repository.create.assert_not_awaited()
    audit.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_binding_is_rechecked_for_each_operation(service):
    manager, resolver, repository, _ = service
    await manager.list()
    resolver.resolve.side_effect = AccessDeniedError("unbound_organization")
    with pytest.raises(AccessDeniedError):
        await manager.create(LinkDraft("https://example.com"))
    assert resolver.resolve.await_count == 2
    repository.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_automatic_allocation_retries_then_audits_once(service, monkeypatch):
    manager, _, repository, audit = service
    monkeypatch.setattr(PublicCode, "generate", classmethod(lambda cls: "code1234"))
    repository.create.side_effect = [LinkConflictError, view()]
    result = await manager.create(LinkDraft("https://example.com"))
    assert result.id == "link"
    assert repository.create.await_count == 2
    audit.record.assert_awaited_once_with("create", "workspace", "link", manager.principal)


@pytest.mark.asyncio
async def test_allocation_retries_are_bounded(service):
    manager, _, repository, audit = service
    repository.create.side_effect = LinkConflictError
    with pytest.raises(LinkConflictError):
        await manager.create(LinkDraft("https://example.com"))
    assert repository.create.await_count == 5
    audit.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_custom_code_is_never_silently_replaced(service):
    manager, _, repository, audit = service
    repository.create.side_effect = LinkConflictError
    with pytest.raises(LinkConflictError):
        await manager.create(LinkDraft("https://example.com", short_code="custom123"))
    assert repository.create.await_count == 1
    audit.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_mutations_and_audit_receive_the_same_bound_workspace(service):
    manager, _, repository, audit = service
    patch = LinkPatch(frozenset({"notes"}), notes="a note")
    await manager.update("link", patch)
    repository.update.assert_awaited_once_with("workspace", "link", patch)
    audit.record.assert_awaited_once_with("update", "workspace", "link", manager.principal)
    await manager.delete("link")
    repository.delete.assert_awaited_once_with("workspace", "link")
    assert audit.record.await_args.args[:3] == ("delete", "workspace", "link")


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "ftp://example.com",
        "/relative",
        "https://user:pass@example.com",
        "https://@example.com",
        "https://example.com/a\u00a0b",
        "https://localhost",
        "https://127.0.0.1",
        "http://2130706433",
        "https://example.com\\bad",
        "https://example.com/white space",
        "https://example.com:bad",
        "https://example.com/\n",
    ],
)
def test_destination_invariants_apply_without_a_transport(value):
    with pytest.raises(InvalidLinkError):
        LinkDraft(value)


def test_destination_preserves_meaningful_url_components():
    value = "https://example.com/path?q=value#section"
    assert Destination(value).value == value


@pytest.mark.parametrize("code", ["api", "REGISTER", "dashboard", "bad/code", "x", "x" * 11])
def test_public_code_validation_is_owned_by_domain(code):
    with pytest.raises(InvalidLinkError):
        LinkDraft("https://example.com", short_code=code)


def test_generated_codes_skip_reserved_names(monkeypatch):
    letters = iter("registercode1234")
    monkeypatch.setattr(
        "app.contexts.links.domain.link.secrets.choice", lambda alphabet: next(letters)
    )
    assert PublicCode.generate() == "code1234"


@pytest.mark.parametrize(
    "fields, values",
    [
        (frozenset(), {}),
        (frozenset({"workspace_id"}), {}),
        (frozenset({"destination_url"}), {}),
        (frozenset({"is_active"}), {"is_active": None}),
        (frozenset({"title"}), {"title": "x" * 201}),
        (frozenset({"notes"}), {"notes": "x" * 4001}),
    ],
)
def test_patch_cannot_bypass_invariants(fields, values):
    with pytest.raises(InvalidLinkError):
        LinkPatch(fields, **values)


def test_partial_update_keeps_explicit_null_distinct_from_absence():
    patch = LinkPatch(frozenset({"notes"}), notes=None)
    assert patch.fields == frozenset({"notes"})
    assert replace(patch, notes="changed").notes == "changed"
