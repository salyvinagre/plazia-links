from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import AnnotatedFields, BoolValue, CanonicalIdField, Length, TupleCoerce

from app.contexts.access.contracts import Principal
from app.kernel.ids import LinkId, PoolId


@dataclass(frozen=True, slots=True)
class DeleteLinksCommand:
    actor: Principal
    ids: Annotated[tuple[LinkId, ...], TupleCoerce(), Length(maximum=100)] = ()
    pool_id: Annotated[PoolId | None, CanonicalIdField(PoolId)] = None
    all: Annotated[bool, BoolValue()] = False

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
        if self.all == bool(self.ids):
            raise ValueError("Select explicit links or all matching links")
        if any(not isinstance(id, LinkId) for id in self.ids):
            raise ValueError("Select canonical link identifiers")
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("Select each link only once")
