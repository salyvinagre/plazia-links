"""Deterministic port adapters for fast acceptance; PostgreSQL behavior has separate proof."""

import copy
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime

from shared_identity import OrganizationId
from shared_messaging.unit_of_work import BaseCommandUnitOfWork

from app.contexts.access.application.dto.organization import OrganizationDto
from app.contexts.access.application.policies.organization import OrganizationAccess
from app.contexts.links.application.dto.links import (
    CommandResultDto,
    LinkDto,
    PageDto,
    PoolDto,
    PublicLinkDto,
)
from app.contexts.links.domain.link import LinkConflictError, LinkDraft, LinkNotFoundError
from app.kernel.ids import LinkId, PoolId
from app.platform.database import Scope
from tests.identity_support import ORG_A, ORG_B


class MemoryRepository:
    def __init__(self, issuer):
        self.bindings = {
            OrganizationId(org): OrganizationDto(OrganizationId(org), "Test organization", True)
            for org in (ORG_A, ORG_B)
        }
        self.issuer = issuer
        self.links = {}
        self.owners = {}
        self.pool_rows = {}
        self.subscriptions = set()
        self.jobs = set()
        self.audits = []
        self.public_locked = False
        self.receipts = {}

    async def replay(self, actor, action, key, fingerprint):
        from app.contexts.links.domain.link import IdempotencyConflictError

        identity = (actor.organization_id, actor.issuer, actor.subject, action, key)
        if identity not in self.receipts:
            self.receipts[identity] = (fingerprint, None)
        previous, result = self.receipts[identity]
        if fingerprint != previous:
            raise IdempotencyConflictError
        return CommandResultDto(result.value, True) if result is not None else None

    async def remember(self, actor, action, key, result):
        identity = (actor.organization_id, actor.issuer, actor.subject, action, key)
        self.receipts[identity] = (self.receipts[identity][0], CommandResultDto(result))

    async def find(self, issuer, organization_id):
        return self.bindings.get(organization_id) if issuer == self.issuer else None

    async def bind(self, issuer, organization_id, name):
        self.bindings[organization_id] = OrganizationDto(organization_id, name, True)

    async def disable(self, issuer, organization_id):
        self.bindings[organization_id] = replace(self.bindings[organization_id], is_active=False)

    async def list(self, organization_id, page, page_size, pool_id=None):
        rows = [
            row
            for id, row in self.links.items()
            if self.owners[id] == organization_id and (pool_id is None or row.pool_id == pool_id)
        ]
        return PageDto(
            tuple(rows[(page - 1) * page_size : page * page_size]), len(rows), page, page_size
        )

    async def get(self, organization_id, link_id, *, lock=False):
        if self.owners.get(link_id) != organization_id:
            raise LinkNotFoundError
        return self.links[link_id]

    async def create(self, organization_id, draft):
        if any(row.short_code == draft.short_code for row in self.links.values()):
            raise LinkConflictError
        now = datetime.now(UTC)
        id = LinkId.new()
        row = LinkDto(
            id,
            draft.short_code,
            draft.destination_url,
            draft.title,
            draft.notes,
            True,
            now,
            now,
            draft.pool_id,
        )
        self.links[id], self.owners[id] = row, organization_id
        return row

    async def update(self, organization_id, link_id, patch):
        previous = await self.get(organization_id, link_id)
        row = replace(
            previous,
            **{name: getattr(patch, name) for name in patch.fields},
            updated_at=datetime.now(UTC),
        )
        self.links[link_id] = row
        return row

    async def delete(self, organization_id, link_id):
        await self.get(organization_id, link_id)
        del self.links[link_id], self.owners[link_id]
        self.subscriptions = {pair for pair in self.subscriptions if pair[0] != link_id}
        self.jobs = {pair for pair in self.jobs if pair[0] != link_id}

    async def reserve(self, organization_id, name, codes):
        pool = PoolDto(PoolId.new(), name, len(codes), datetime.now(UTC))
        self.pool_rows[pool.id] = (organization_id, pool)
        for code in codes:
            await self.create(organization_id, LinkDraft(None, short_code=code, pool_id=pool.id))
        return pool

    async def get_pool(self, organization_id, pool_id):
        entry = self.pool_rows.get(pool_id)
        if entry is None or entry[0] != organization_id:
            raise LinkNotFoundError
        return entry[1]

    async def pools(self, organization_id, page, page_size):
        rows = [p for org, p in self.pool_rows.values() if org == organization_id]
        return PageDto(
            tuple(rows[(page - 1) * page_size : page * page_size]), len(rows), page, page_size
        )

    async def public(self, short_code, *, lock=False):
        self.public_locked = lock
        for row in self.links.values():
            if row.short_code == short_code:
                return PublicLinkDto(row.id, row.short_code, row.destination_url, row.is_active)
        raise LinkNotFoundError

    async def subscribe(self, link_id, email):
        self.subscriptions.add((link_id, str(email)))

    async def ready_subscriptions(self, organization_id, link_id, context=None):
        self.jobs.update(pair for pair in self.subscriptions if pair[0] == link_id)

    async def audit(self, organization_id, action, resource_id, context):
        self.audits.append((organization_id, action, resource_id, context))


class MemoryDatabase:
    def __init__(self, repository):
        self.repository = repository
        self.scope_count = 0
        self.commit_failure = False

    @asynccontextmanager
    async def scope(self, organization_id=None, *, readonly=True):
        self.scope_count += 1
        yield Scope(self.repository, self.repository, OrganizationAccess(self.repository))


class MemoryUow(BaseCommandUnitOfWork):
    def __init__(self, database):
        super().__init__(
            scope=Scope(
                database.repository, database.repository, OrganizationAccess(database.repository)
            )
        )
        self.database = database

    async def _enter(self):
        self.snapshot = copy.deepcopy(self.database.repository.__dict__)

    async def _commit(self):
        if self.database.commit_failure:
            raise RuntimeError("Fixture commit failure")

    async def _rollback(self):
        self.database.repository.__dict__.update(self.snapshot)


class MemoryUowFactory:
    def __init__(self, database):
        self.database = database

    async def start(self, envelope):
        return MemoryUow(self.database)


class FixtureAuthority:
    def __init__(self):
        self.allowed = True
        self.calls = []

    async def require(self, attempt):
        from app.contexts.access.contracts import AccessDeniedError

        attempt.actor.require(attempt.permission)
        self.calls.append(attempt)
        if not self.allowed:
            raise AccessDeniedError("organization_authority")
