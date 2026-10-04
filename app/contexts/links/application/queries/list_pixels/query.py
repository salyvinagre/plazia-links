from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import AnnotatedFields, IntValue, Maximum, Minimum

from app.contexts.access.contracts import Principal


@dataclass(frozen=True, slots=True)
class ListPixelsQuery:
    actor: Principal
    page: Annotated[int, IntValue(), Minimum(1)] = 1
    page_size: Annotated[int, IntValue(), Minimum(1), Maximum(100)] = 20

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
