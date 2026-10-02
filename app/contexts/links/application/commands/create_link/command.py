from dataclasses import dataclass

from shared_kernel.fields import (
    AnnotatedFields,
)

from app.contexts.access.contracts import Principal
from app.contexts.links.domain.link import LinkDraft


@dataclass(frozen=True, slots=True)
class CreateLinkCommand:
    actor: Principal
    draft: LinkDraft

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
