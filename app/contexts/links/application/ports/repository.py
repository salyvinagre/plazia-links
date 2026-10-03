from typing import Protocol

from shared_identity.canonical_ids import OrganizationId
from shared_kernel.contacts import NormalizedEmail
from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import Principal
from app.contexts.links.application.dto.links import (
    CommandResultDto,
    LinkDto,
    PageDto,
    PoolDto,
    PublicLinkDto,
)
from app.contexts.links.domain.link import LinkDraft, LinkPatch
from app.kernel.ids import LinkId, PoolId


class LinkRepository(Protocol):
    async def replay(
        self, actor: Principal, action: str, key: str, fingerprint: str
    ) -> CommandResultDto | None: ...

    async def remember(
        self, actor: Principal, action: str, key: str, result: LinkDto | PoolDto | None
    ) -> None: ...

    async def list(
        self,
        organization_id: OrganizationId,
        page: int,
        page_size: int,
        pool_id: PoolId | None = None,
    ) -> PageDto[LinkDto]: ...
    async def get(
        self, organization_id: OrganizationId, link_id: LinkId, *, lock: bool = False
    ) -> LinkDto: ...
    async def create(self, organization_id: OrganizationId, draft: LinkDraft) -> LinkDto: ...
    async def update(
        self, organization_id: OrganizationId, link_id: LinkId, patch: LinkPatch
    ) -> LinkDto: ...
    async def delete(self, organization_id: OrganizationId, link_id: LinkId) -> None: ...
    async def delete_many(
        self,
        organization_id: OrganizationId,
        ids: tuple[LinkId, ...],
        pool_id: PoolId | None = None,
        *,
        all: bool = False,
    ) -> tuple[LinkId, ...]: ...
    async def reserve(
        self, organization_id: OrganizationId, name: str | None, codes: tuple[str, ...]
    ) -> PoolDto: ...
    async def get_pool(self, organization_id: OrganizationId, pool_id: PoolId) -> PoolDto: ...
    async def rename_pool(
        self, organization_id: OrganizationId, pool_id: PoolId, name: str | None
    ) -> PoolDto: ...
    async def delete_pool(self, organization_id: OrganizationId, pool_id: PoolId) -> None: ...
    async def pools(
        self, organization_id: OrganizationId, page: int, page_size: int
    ) -> PageDto[PoolDto]: ...
    async def ready_subscriptions(
        self, organization_id: OrganizationId, link_id: LinkId, context: Invocation | None = None
    ) -> None: ...
    async def public(self, short_code: str, *, lock: bool = False) -> PublicLinkDto: ...
    async def subscribe(self, link_id: LinkId, email: NormalizedEmail) -> None: ...
    async def audit(
        self,
        organization_id: OrganizationId,
        action: str,
        resource_ids: tuple[LinkId | PoolId, ...],
        context: Invocation,
    ) -> None: ...
