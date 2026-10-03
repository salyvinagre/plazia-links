from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import AnnotatedFields, CanonicalIdField

from app.contexts.access.contracts import Principal
from app.kernel.ids import PoolId


@dataclass(frozen=True, slots=True)
class GetPoolQuery:
    actor: Principal
    pool_id: Annotated[PoolId, CanonicalIdField(PoolId)]

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
