from dataclasses import dataclass

from shared_kernel.fields import (
    AnnotatedFields,
)

from app.contexts.access.contracts import Principal
from app.contexts.links.domain.link import InvalidLinkError, LinkDraft, Visibility


@dataclass(frozen=True, slots=True)
class CreateLinkCommand:
    actor: Principal
    draft: LinkDraft

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
        if self.draft.short_code and (
            self.draft.entropy is not None or self.draft.visibility is Visibility.workload_private
        ):
            raise InvalidLinkError("Custom short_code and generated entropy are mutually exclusive")
