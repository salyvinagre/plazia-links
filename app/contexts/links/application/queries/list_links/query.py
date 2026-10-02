from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import (
    AnnotatedFields,
    CanonicalIdField,
    IntValue,
    Maximum,
    Minimum,
)

from app.contexts.access.contracts import Principal
from app.kernel.ids import PoolId


@dataclass(frozen=True, slots=True)
class ListLinksQuery:
    actor: Principal
    page: Annotated[int, IntValue(), Minimum(1)] = 1
    page_size: Annotated[int, IntValue(), Minimum(1), Maximum(100)] = 20
    pool_id: Annotated[PoolId | None, CanonicalIdField(PoolId)] = None

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
