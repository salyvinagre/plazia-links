from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import (
    AnnotatedFields,
    CanonicalIdField,
)

from app.contexts.access.contracts import Principal
from app.kernel.ids import LinkId


@dataclass(frozen=True, slots=True)
class GetLinkQuery:
    actor: Principal
    link_id: Annotated[LinkId, CanonicalIdField(LinkId)]

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
