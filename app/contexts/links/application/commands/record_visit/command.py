from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import AnnotatedFields, CanonicalIdField, ClosedText, Length, StringValue

from app.contexts.links.application.dto.statistics import VisitOutcome
from app.contexts.links.domain.link import PublicCode
from app.kernel.ids import LinkId


@dataclass(frozen=True, slots=True)
class RecordVisitCommand:
    link_id: Annotated[LinkId, CanonicalIdField(LinkId)]
    code: Annotated[str, StringValue(), Length(minimum=3, maximum=10)]
    outcome: Annotated[VisitOutcome, ClosedText(("redirect", "waiting"))]

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
        PublicCode(self.code)
