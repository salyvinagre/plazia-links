"""An email delivery reference and an unguessable public image locator."""

import secrets
from dataclasses import dataclass
from typing import Annotated

from shared_kernel.fields import AnnotatedFields, BlankAsNoneText, Length, PatternText


class PixelNotFoundError(Exception):
    """No pixel is available in the selected scope."""


class PixelConflictError(Exception):
    """A generated pixel identity could not be allocated."""


@dataclass(frozen=True, slots=True)
class PixelCode:
    value: Annotated[str, PatternText(r"[A-Za-z0-9_-]{32}")]

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)

    @staticmethod
    def generate() -> str:
        return secrets.token_urlsafe(24)


@dataclass(frozen=True, slots=True)
class PixelDraft:
    reference: Annotated[str | None, BlankAsNoneText(), Length(maximum=200)] = None

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
