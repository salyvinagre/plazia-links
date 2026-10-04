from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import AnnotatedFields, CanonicalIdField

from app.contexts.access.contracts import Principal
from app.kernel.ids import PixelId


@dataclass(frozen=True, slots=True)
class GetPixelQuery:
    actor: Principal
    id: Annotated[PixelId, CanonicalIdField(PixelId)]

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
