from dataclasses import dataclass
from typing import Annotated

from shared_kernel.contacts import NormalizedEmail
from shared_kernel.fields import (
    AnnotatedFields,
    Length,
    StringValue,
    TextValueField,
)

from app.contexts.links.domain.link import PublicCode


@dataclass(frozen=True, slots=True)
class SubscribeLinkCommand:
    short_code: Annotated[str, StringValue(), Length(minimum=3, maximum=10)]
    email: Annotated[NormalizedEmail, TextValueField(NormalizedEmail)]

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
        PublicCode(self.short_code)
