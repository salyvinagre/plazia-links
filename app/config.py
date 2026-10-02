from typing import Literal
from warnings import warn

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = "development"
    deployment_mode: Literal["container", "serverless"] = "container"
    sentry_dsn: str = ""
    auth_mode: Literal["identity", "legacy"] = "identity"
    database_url: str = "sqlite+aiosqlite:///./zly.db"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "change-me-in-production"
    jwt_secret: str = "change-me-in-production"
    cors_origins: str = "http://localhost:8000"
    default_domain: str = "localhost:8000"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7
    rate_limit_enabled: bool = True
    rate_limit_redirect: int = 100
    rate_limit_api: int = 60
    rate_limit_auth: int = 10
    rate_limit_tracking: int = 60
    rate_limit_window: int = 60
    max_upload_size_mb: int = 50
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@zly.ai"
    smtp_from_name: str = "Zly"
    domain_verify_prefix: str = "zly-verify"
    click_retention_days: int = 365
    data_retention_enabled: bool = True
    google_client_id: str = ""
    google_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    oauth_redirect_url: str = "http://localhost:8000/api/v1/auth/oauth/callback"
    secure_cookies: bool = True

    def validate_runtime_profile(self, mode: Literal["identity", "legacy"] | None = None) -> None:
        production = self.environment.lower() in {"production", "prod"}
        if self.deployment_mode == "serverless":
            if (mode or self.auth_mode) != "identity":
                raise RuntimeError("Serverless deployment requires Identity authentication")
            if not self.database_url.startswith("postgresql+asyncpg://"):
                raise RuntimeError("Serverless deployment requires an external PostgreSQL database")
            if production:
                from urllib.parse import parse_qs, urlsplit

                ssl = parse_qs(urlsplit(self.database_url).query).get("ssl", [])
                if ssl != ["verify-full"]:
                    raise RuntimeError("Serverless PostgreSQL requires ssl=verify-full")
                if not self.redis_url.startswith("rediss://"):
                    raise RuntimeError("Serverless Redis requires TLS (rediss://)")
        if production and (mode or self.auth_mode) == "legacy":
            raise RuntimeError("Legacy authentication is forbidden in production")
        if production and (
            self.secret_key == "change-me-in-production"
            or self.secret_key.startswith("REPLACE_")
            or len(self.secret_key) < 32
        ):
            raise RuntimeError("Production SECRET_KEY must contain at least 32 random characters")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def base_url(self) -> str:
        domain = self.default_domain
        if "://" in domain:
            return domain.rstrip("/")
        return f"https://{domain}"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

if settings.secret_key == "change-me-in-production":
    warn(
        "SECRET_KEY is still the default value 'change-me-in-production'. "
        "Set a strong SECRET_KEY in production (at least 32 bytes).",
        stacklevel=2,
    )

if settings.auth_mode == "legacy" and settings.jwt_secret == "change-me-in-production":
    warn(
        "JWT secret is still the default value 'change-me-in-production'. "
        "Set a strong JWT_SECRET in production (at least 32 bytes).",
        stacklevel=2,
    )


class IdentitySettings(BaseSettings):
    """Deployment-owned trust configuration; never populated from a request/token."""

    issuer: str = ""
    audience: str = ""
    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    public_base_url: str = "http://localhost:8000"
    allow_insecure_loopback: bool = False
    session_ttl: int = 900

    model_config = {
        "env_prefix": "IDENTITY_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def authorization_endpoint(self) -> str:
        return self.issuer.rstrip("/") + "/oauth2/auth"

    @property
    def token_endpoint(self) -> str:
        return self.issuer.rstrip("/") + "/oauth2/token"

    @property
    def jwks_uri(self) -> str:
        return self.issuer.rstrip("/") + "/.well-known/jwks"

    @property
    def redirect_uri(self) -> str:
        return self.public_base_url.rstrip("/") + "/auth/callback"

    @property
    def secure(self) -> bool:
        return self.public_base_url.startswith("https://")

    @property
    def session_cookie(self) -> str:
        return "__Host-plazia-links" if self.secure else "plazia_links_session"

    @property
    def login_cookie(self) -> str:
        return "__Host-plazia-login" if self.secure else "plazia_links_login"

    def validate_deployment(self, *, production: bool) -> None:
        from urllib.parse import urlsplit

        if (
            not self.issuer
            or not self.audience
            or not self.client_id
            or not self.client_secret.get_secret_value()
        ):
            raise ValueError(
                "Identity issuer, audience and confidential browser client are required"
            )
        if production and self.client_secret.get_secret_value().startswith("REPLACE_"):
            raise ValueError("Replace the example Identity client secret before deployment")
        if self.audience == self.client_id:
            raise ValueError("Identity API audience and browser client ID must be distinct")
        if not 60 <= self.session_ttl <= 3600:
            raise ValueError("Identity session TTL must be between 60 and 3600 seconds")
        for url in (self.issuer, self.public_base_url):
            parsed = urlsplit(url)
            if (
                not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in ("", "/")
            ):
                raise ValueError("Identity issuer and public base URL must be origin URLs")
            if parsed.scheme != "https":
                local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                if (
                    production
                    or not self.allow_insecure_loopback
                    or not local
                    or parsed.scheme != "http"
                ):
                    raise ValueError(
                        "Identity endpoints require HTTPS (loopback-only development exception)"
                    )
        resource = urlsplit(self.audience)
        if (
            resource.scheme != "https"
            or not resource.hostname
            or resource.username
            or resource.password
            or resource.fragment
        ):
            raise ValueError("Identity API resource must be an absolute HTTPS URI")
