"""Intentional, bounded JSON contracts for the Identity-backed link API."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contexts.links.contracts import Destination, LinkDraft, LinkPatch, PublicCode


class CreateLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_url: str = Field(min_length=1, max_length=8192)
    title: str | None = Field(None, max_length=200)
    short_code: str | None = Field(None, min_length=3, max_length=10, pattern=r"^[A-Za-z0-9_-]+$")
    notes: str | None = Field(None, max_length=4000)

    @field_validator("destination_url")
    @classmethod
    def destination(cls, value: str) -> str:
        return Destination(value).value

    @field_validator("short_code")
    @classmethod
    def public_code(cls, value: str | None) -> str | None:
        return PublicCode(value).value if value is not None else None

    def draft(self) -> LinkDraft:
        return LinkDraft(self.destination_url, self.title, self.short_code, self.notes)


class UpdateLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_url: str | None = Field(None, min_length=1, max_length=8192)
    title: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=4000)
    is_active: bool | None = None

    @model_validator(mode="after")
    def supplied_values(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        for field in ("destination_url", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        if self.destination_url is not None:
            CreateLinkRequest.destination(self.destination_url)
        return self

    def patch(self) -> LinkPatch:
        return LinkPatch(
            frozenset(self.model_fields_set),
            self.destination_url,
            self.title,
            self.notes,
            self.is_active,
        )


class ManagedLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    short_code: str
    short_url: str
    destination_url: str
    title: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ManagedLinkPage(BaseModel):
    items: list[ManagedLinkResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
