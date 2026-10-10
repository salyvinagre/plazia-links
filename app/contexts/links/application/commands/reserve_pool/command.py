from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import (
    AnnotatedFields,
    IntValue,
    Length,
    Maximum,
    Minimum,
    StringValue,
)

from app.contexts.access.contracts import Principal
from app.contexts.links.domain.link import Entropy, Visibility


@dataclass(frozen=True, slots=True)
class ReservePoolCommand:
    actor: Principal
    size: Annotated[int, IntValue(), Minimum(1), Maximum(100)]
    name: Annotated[str | None, StringValue(), Length(maximum=200)] = None
    entropy: Entropy | None = None
    visibility: Visibility | None = None

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
