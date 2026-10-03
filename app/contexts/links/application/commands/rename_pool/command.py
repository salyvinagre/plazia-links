from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import AnnotatedFields, CanonicalIdField, Length, StringValue

from app.contexts.access.contracts import Principal
from app.kernel.ids import PoolId


@dataclass(frozen=True, slots=True)
class RenamePoolCommand:
    actor: Principal
    pool_id: Annotated[PoolId, CanonicalIdField(PoolId)]
    name: Annotated[str | None, StringValue(), Length(maximum=200)]

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
