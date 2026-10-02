"""Link input invariants. No HTTP schemas, storage or environment dependencies."""

import ipaddress
import re
import secrets
import string
from dataclasses import dataclass
from typing import ClassVar
from urllib.parse import urlsplit


class InvalidLinkError(ValueError):
    """A command violates the link contract."""


class LinkNotFoundError(Exception):
    """No link is visible in the caller's workspace."""


class LinkConflictError(Exception):
    """The requested public code is already allocated."""


@dataclass(frozen=True)
class Destination:
    value: str

    def __post_init__(self) -> None:
        value = self.value
        if (
            not 1 <= len(value) <= 8192
            or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value)
            or "\\" in value
        ):
            raise InvalidLinkError("Destination must be an HTTP(S) URL without whitespace")
        try:
            parsed = urlsplit(value)
            _ = parsed.port
        except ValueError as exc:
            raise InvalidLinkError("Invalid destination URL") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise InvalidLinkError("Destination must be an absolute HTTP(S) URL without user info")
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith(".localhost") or "%" in host:
            raise InvalidLinkError("Private destination is not allowed")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            # Non-canonical numeric IPv4 spellings are ambiguous to browsers.
            if re.fullmatch(
                r"(?:0[xX][0-9a-fA-F]+|[0-9]+)(?:\.(?:0[xX][0-9a-fA-F]+|[0-9]+))*", host
            ):
                raise InvalidLinkError("Ambiguous IP destination is not allowed") from None
        else:
            documentation = any(
                address in ipaddress.ip_network(net)
                for net in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
            )
            if not documentation and (not address.is_global or address.is_multicast):
                raise InvalidLinkError("Private destination is not allowed")
        # Only lexical checks: registration never fetches the destination or resolves its DNS.


@dataclass(frozen=True)
class PublicCode:
    value: str
    RESERVED: ClassVar[frozenset[str]] = frozenset(
        {
            "api",
            "auth",
            "login",
            "logout",
            "dashboard",
            "health",
            "static",
            "docs",
            "redoc",
            "register",
            "signed-out",
        }
    )

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{3,10}", self.value)
            or self.value.lower() in self.RESERVED
        ):
            raise InvalidLinkError("Short code is invalid or reserved")

    @classmethod
    def generate(cls) -> str:
        while True:
            candidate = "".join(
                secrets.choice(string.ascii_letters + string.digits) for _ in range(8)
            )
            if candidate.lower() not in cls.RESERVED:
                return candidate


@dataclass(frozen=True)
class LinkDraft:
    destination_url: str
    title: str | None = None
    short_code: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        Destination(self.destination_url)
        if self.short_code is not None:
            PublicCode(self.short_code)
        if self.title is not None and len(self.title) > 200:
            raise InvalidLinkError("Title must contain at most 200 characters")
        if self.notes is not None and len(self.notes) > 4000:
            raise InvalidLinkError("Notes must contain at most 4000 characters")


@dataclass(frozen=True)
class LinkPatch:
    fields: frozenset[str]
    destination_url: str | None = None
    title: str | None = None
    notes: str | None = None
    is_active: bool | None = None

    def __post_init__(self) -> None:
        if not self.fields or not self.fields <= {"destination_url", "title", "notes", "is_active"}:
            raise InvalidLinkError("Only explicit, editable link fields may be patched")
        if "destination_url" in self.fields:
            if self.destination_url is None:
                raise InvalidLinkError("Destination cannot be null")
            Destination(self.destination_url)
        if "is_active" in self.fields and type(self.is_active) is not bool:
            raise InvalidLinkError("Active state must be a boolean")
        if "title" in self.fields and self.title is not None and len(self.title) > 200:
            raise InvalidLinkError("Title must contain at most 200 characters")
        if "notes" in self.fields and self.notes is not None and len(self.notes) > 4000:
            raise InvalidLinkError("Notes must contain at most 4000 characters")
