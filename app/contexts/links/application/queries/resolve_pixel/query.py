from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import AnnotatedFields, PatternText


@dataclass(frozen=True, slots=True)
class ResolvePixelQuery:
    code: Annotated[str, PatternText(r"[A-Za-z0-9_-]{32}")]

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
