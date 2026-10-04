from typing import Protocol

from shared_identity import OrganizationId

from app.contexts.links.application.dto.links import PageDto
from app.contexts.links.application.dto.pixels import PixelDto, PixelReadDto
from app.contexts.links.domain.pixel import PixelDraft
from app.kernel.ids import PixelId


class PixelRepository(Protocol):
    async def create(
        self, organization_id: OrganizationId, draft: PixelDraft, code: str
    ) -> PixelDto: ...
    async def get(self, organization_id: OrganizationId, id: PixelId) -> PixelReadDto: ...
    async def list(
        self, organization_id: OrganizationId, page: int, page_size: int
    ) -> PageDto[PixelReadDto]: ...
    async def delete(self, organization_id: OrganizationId, id: PixelId) -> None: ...
    async def public(self, code: str) -> PixelId: ...
    async def record(self, id: PixelId, code: str) -> None: ...
