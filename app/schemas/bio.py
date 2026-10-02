from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.link import _validate_url_scheme


class BioLinkCreate(BaseModel):
    link_id: str
    title: str = Field(..., min_length=1, max_length=200)
    url: str
    position: int = 0
    is_active: bool = True

    _validate_url = field_validator("url")(_validate_url_scheme)


class BioLinkUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = None
    position: int | None = None
    is_active: bool | None = None

    _validate_url = field_validator("url")(_validate_url_scheme)


class BioLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    bio_page_id: str
    link_id: str
    title: str
    url: str
    position: int
    is_active: bool
    created_at: datetime


class BioPageCreate(BaseModel):
    slug: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-z0-9-]+$")
    title: str = Field(..., min_length=1, max_length=100)
    bio: str | None = None
    avatar_url: str | None = None
    theme: str = "midnight"


class BioPageUpdate(BaseModel):
    slug: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=100)
    bio: str | None = None
    avatar_url: str | None = None
    theme: str | None = None
    is_published: bool | None = None


class BioPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    slug: str
    title: str
    bio: str | None
    avatar_url: str | None
    theme: str
    is_published: bool
    created_at: datetime
    updated_at: datetime
    links: list[BioLinkResponse] = []


class BioPagePublicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str
    bio: str | None
    avatar_url: str | None
    theme: str
    links: list[BioLinkResponse] = []
