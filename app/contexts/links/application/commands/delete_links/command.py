from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import AnnotatedFields, CanonicalIdField, Length, TupleCoerce

from app.contexts.access.contracts import Principal
from app.kernel.ids import LinkId, PoolId


@dataclass(frozen=True, slots=True)
class DeleteLinksCommand:
    actor: Principal
    ids: Annotated[tuple[LinkId, ...], TupleCoerce(), Length(minimum=1, maximum=100)]
    pool_id: Annotated[PoolId | None, CanonicalIdField(PoolId)] = None

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("Select each link only once")
