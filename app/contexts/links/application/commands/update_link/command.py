from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import (
    AnnotatedFields,
    CanonicalIdField,
)

from app.contexts.access.contracts import Principal
from app.contexts.links.domain.link import LinkPatch
from app.kernel.ids import LinkId


@dataclass(frozen=True, slots=True)
class UpdateLinkCommand:
    actor: Principal
    link_id: Annotated[LinkId, CanonicalIdField(LinkId)]
    patch: LinkPatch

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
