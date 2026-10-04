from dataclasses import dataclass

from app.contexts.access.contracts import Principal
from app.contexts.links.domain.pixel import PixelDraft


@dataclass(frozen=True, slots=True)
class CreatePixelCommand:
    actor: Principal
    draft: PixelDraft
