"""One canonical settings construction path per concern, using shared sources."""

from ipaddress import IPv4Address, IPv6Address
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from shared_settings import RuntimeSettingsSources

from app.kernel.api import ApiContract


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLZL_", env_file=".env", extra="ignore")
    environment: str = "development"
    deployment_mode: Literal["container", "serverless"] = "container"
    database_url: SecretStr = SecretStr("postgresql://links_app@127.0.0.1:5432/links")
    worker_database_url: SecretStr = SecretStr("")
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    rate_limit_enabled: bool = True
    trusted_proxy_ips: tuple[IPv4Address | IPv6Address, ...] = ()
    smtp_host: str = "localhost"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "no-reply@example.com"
    smtp_from_name: str = "Plazia Links"
    smtp_security: Literal["starttls", "tls", "plain"] = "starttls"
    smtp_timeout: float = Field(default=10, gt=0, le=60)
    worker_interval: float = Field(default=5, ge=0.1, le=3600)
    openfga_url: str = ""
    openfga_store_id: str = ""
    openfga_model_id: str = ""
    telemetry_export_driver: Literal["noop", "otel"] = "noop"
    telemetry_otlp_endpoint: str = ""
    telemetry_otlp_timeout_seconds: float = Field(default=5, gt=0, le=30)
    telemetry_metric_export_interval_millis: int = Field(default=10000, ge=1000)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        secrets = {
            "database_url": "PLZL_DATABASE_URL",
            "worker_database_url": "PLZL_WORKER_DATABASE_URL",
            "redis_url": "PLZL_REDIS_URL",
            "smtp_password": "PLZL_SMTP_PASSWORD",
        }
        return RuntimeSettingsSources(
            selector="PLZL_CONFIG",
            secret_selectors=secrets,
            environment_fields=frozenset(cls.model_fields).difference(secrets),
            forbidden_toml_paths=tuple(f"app.{name}" for name in secrets),
            toml_section=("app",),
        ).settings_sources(
            settings_cls=settings_cls,
            init_settings=init_settings,
            env_settings=env_settings,
            dotenv_settings=dotenv_settings,
            file_secret_settings=file_secret_settings,
        )

    def validate_runtime(self) -> None:
        if not self.database_url.get_secret_value().startswith(("postgresql://", "postgres://")):
            raise ValueError("A PostgreSQL runtime URL is required")
        if self.environment in {"production", "prod"} and self.smtp_security == "plain":
            raise ValueError("Production SMTP requires TLS")


class IdentitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLZL_IDENTITY_", env_file=".env", extra="ignore")
    issuer: str = ""
    audience: str = ""
    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    public_base_url: str = "http://localhost:8000"
    allow_insecure_loopback: bool = False
    session_ttl: int = 900

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return RuntimeSettingsSources(
            selector="PLZL_CONFIG",
            secret_selectors={"client_secret": "PLZL_IDENTITY_CLIENT_SECRET"},
            environment_fields=frozenset(cls.model_fields).difference({"client_secret"}),
            forbidden_toml_paths=("identity.client_secret",),
            toml_section=("identity",),
        ).settings_sources(
            settings_cls=settings_cls,
            init_settings=init_settings,
            env_settings=env_settings,
            dotenv_settings=dotenv_settings,
            file_secret_settings=file_secret_settings,
        )

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

        if (
            not self.issuer
            or not self.audience
            or not self.client_id
            or not self.client_secret.get_secret_value()
        ):
            raise ValueError(
                "Identity issuer, audience and confidential browser client are required"
            )
        if self.audience == self.client_id or not 60 <= self.session_ttl <= 3600:
            raise ValueError("Distinct API audience and bounded session lifetime are required")
        self._validate_origins((self.issuer, self.public_base_url), production=production)
        ApiContract.validate_base(self.audience)

    def validate_public_origin(self, *, production: bool) -> None:
        self._validate_origins((self.public_base_url,), production=production)

    def _validate_origins(self, urls: tuple[str, ...], *, production: bool) -> None:
        from urllib.parse import urlsplit

        for url in urls:
            parsed = urlsplit(url)
            if (
                not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in ("", "/")
            ):
                raise ValueError("Identity endpoints must be origins")
            if parsed.scheme != "https":
                if (
                    production
                    or not self.allow_insecure_loopback
                    or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                    or parsed.scheme != "http"
                ):
                    raise ValueError("Identity endpoints require HTTPS")
