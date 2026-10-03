"""Process-owned settings with one shared, secret-aware source contract."""

from ipaddress import IPv4Address, IPv6Address
from typing import ClassVar, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from shared_kernel.fields import HttpOrigin
from shared_settings import RuntimeSettingsSources

from app.kernel.api import ApiContract


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PLZK_", env_file=".env", extra="ignore", secrets_dir="/run/secrets"
    )
    section: ClassVar[str] = "app"

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
            name: str(cls.model_config["env_prefix"]) + name.upper()
            for name, field in cls.model_fields.items()
            if field.annotation is SecretStr
        }
        return RuntimeSettingsSources(
            selector="PLZK_CONFIG",
            secret_selectors=secrets,
            environment_fields=frozenset(cls.model_fields).difference(secrets),
            forbidden_toml_paths=FORBIDDEN_TOML_PATHS,
            toml_section=(cls.section,),
        ).settings_sources(
            settings_cls=settings_cls,
            init_settings=init_settings,
            env_settings=env_settings,
            dotenv_settings=dotenv_settings,
            file_secret_settings=file_secret_settings,
        )


class ServiceSettings(RuntimeSettings):
    database_url: SecretStr = Field(default=SecretStr(""), exclude=True, repr=False)
    environment: str = "development"
    telemetry_export_driver: Literal["noop", "otel"] = "noop"
    telemetry_otlp_endpoint: str = ""
    telemetry_otlp_timeout_seconds: float = Field(default=5, gt=0, le=30)
    telemetry_metric_export_interval_millis: int = Field(default=10000, ge=1000)

    def validate_runtime(self) -> None:
        if not self.database_url.get_secret_value().startswith(("postgresql://", "postgres://")):
            raise ValueError("A PostgreSQL runtime URL is required")


class Settings(ServiceSettings):
    deployment_mode: Literal["container", "serverless"] = "container"
    redis_url: SecretStr = Field(
        default=SecretStr("redis://localhost:6379/0"), exclude=True, repr=False
    )
    rate_limit_enabled: bool = True
    trusted_proxy_ips: tuple[IPv4Address | IPv6Address, ...] = ()
    openfga_url: str = ""
    openfga_store_id: SecretStr = Field(default=SecretStr(""), exclude=True, repr=False)
    openfga_model_id: SecretStr = Field(default=SecretStr(""), exclude=True, repr=False)


class WorkerSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="PLZK_WORKER_")
    section: ClassVar[str] = "worker"
    smtp_host: str = "localhost"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: SecretStr = Field(default=SecretStr(""), exclude=True, repr=False)
    smtp_from: str = "no-reply@example.com"
    smtp_from_name: str = "Plazia Links"
    smtp_security: Literal["starttls", "tls", "plain"] = "starttls"
    smtp_timeout: float = Field(default=10, gt=0, le=60)
    interval: float = Field(default=5, ge=0.1, le=3600)

    def validate_runtime(self) -> None:
        super().validate_runtime()
        if self.environment in {"production", "prod"} and self.smtp_security == "plain":
            raise ValueError("Production SMTP requires TLS")


class OwnerSettings(RuntimeSettings):
    model_config = SettingsConfigDict(env_prefix="PLZK_SCHEMA_")
    section: ClassVar[str] = "owner"
    database_url: SecretStr = Field(default=SecretStr(""), exclude=True, repr=False)


class PublicSettings(RuntimeSettings):
    model_config = SettingsConfigDict(env_prefix="PLZK_IDENTITY_")
    section: ClassVar[str] = "identity"
    issuer: str = ""
    public_base_url: str = "http://localhost:8000"
    allow_insecure_loopback: bool = False

    def validate_public_origin(self, *, production: bool) -> None:
        self._validate_origins((self.public_base_url,), production=production)

    def _validate_origins(self, urls: tuple[str, ...], *, production: bool) -> None:
        from urllib.parse import urlsplit

        for url in urls:
            parsed = urlsplit(HttpOrigin().normalize(url, "Identity endpoint"))
            if parsed.scheme != "https" and (
                production
                or not self.allow_insecure_loopback
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            ):
                raise ValueError("Identity endpoints require HTTPS")


class IdentitySettings(PublicSettings):
    audience: str = ""
    client_id: str = ""
    client_secret: SecretStr = Field(default=SecretStr(""), exclude=True, repr=False)
    session_ttl: int = 900

    @property
    def authorization_endpoint(self) -> str:
        return self.issuer.rstrip("/") + "/oauth2/auth"

    @property
    def token_endpoint(self) -> str:
        return self.issuer.rstrip("/") + "/oauth2/token"

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


FORBIDDEN_TOML_PATHS = tuple(
    f"{model.section}.{name}"
    for model in (Settings, WorkerSettings, OwnerSettings, IdentitySettings)
    for name, field in model.model_fields.items()
    if field.annotation is SecretStr
)
