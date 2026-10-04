from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import AnnotatedFields, CanonicalIdField, PatternText

from app.kernel.ids import PixelId


@dataclass(frozen=True, slots=True)
class RecordPixelRequestCommand:
    id: Annotated[PixelId, CanonicalIdField(PixelId)]
    code: Annotated[str, PatternText(r"[A-Za-z0-9_-]{32}")]

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
