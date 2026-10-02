"""The Links v1 resource identity and route base advance together."""

from typing import ClassVar
from urllib.parse import urlsplit


class ApiContract:
    path: ClassVar[str] = "/api/v1"

    @classmethod
    def validate_base(cls, value: str) -> None:
        parsed = urlsplit(value)
        if (
            value != value.strip()
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path != cls.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Identity audience must be the canonical HTTPS /api/v1 base")
        _ = parsed.port

    @classmethod
    def resource(cls, collection: str, identifier: object | None = None) -> str:
        return f"{cls.path}/{collection}" + (f"/{identifier}" if identifier is not None else "")
