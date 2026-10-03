"""Pure declarations on the shared environment model; never load runtime values."""

import json

from plazia_tooling.release.env_model import (
    EnvClass,
    EnvConsumer,
    EnvProducer,
    EnvRegistry,
    EnvSurface,
    EnvVariable,
)
from pydantic import SecretStr

from app.platform.settings import IdentitySettings, Settings

_REQUIRED = frozenset(
    {
        "PLZL_WORKER_DATABASE_URL",
        "PLZL_OPENFGA_URL",
        "PLZL_OPENFGA_STORE_ID",
        "PLZL_OPENFGA_MODEL_ID",
        "PLZL_IDENTITY_ISSUER",
        "PLZL_IDENTITY_AUDIENCE",
        "PLZL_IDENTITY_CLIENT_ID",
        "PLZL_IDENTITY_CLIENT_SECRET",
    }
)


def build_registry() -> EnvRegistry:
    variables = []
    for model, section in ((Settings, "app"), (IdentitySettings, "identity")):
        for name, field in model.model_fields.items():
            selector = str(model.model_config["env_prefix"]) + name.upper()
            secret = field.annotation is SecretStr
            required = selector in _REQUIRED
            default = field.default
            variables.append(
                EnvVariable(
                    name=selector,
                    env_class=EnvClass.REQUIRED if required else EnvClass.OVERRIDABLE,
                    purpose=field.description or f"{section}: {name.replace('_', ' ')}.",
                    producer=EnvProducer.SECRETS if secret else EnvProducer.TOML_CONFIG,
                    consumer=EnvConsumer.SETTINGS_FIELD,
                    surface=EnvSurface.OPERATOR,
                    toml_counterpart=None if secret else f"{section}.{name}",
                    default=None
                    if secret or required
                    else (default if isinstance(default, str) else json.dumps(default)),
                    secret=secret,
                    file_supported=secret,
                )
            )
    variables.append(
        EnvVariable(
            name="PLZL_CONFIG_FILE",
            env_class=EnvClass.OVERRIDABLE,
            purpose="Optional non-secret TOML settings file for app and identity.",
            producer=EnvProducer.TOML_CONFIG,
            consumer=EnvConsumer.SETTINGS_FIELD,
            surface=EnvSurface.OPERATOR,
        )
    )
    for name, purpose in (
        ("CONFIG_PATH", "Host path of the non-secret Compose TOML configuration."),
        ("APP_DATABASE_URL_PATH", "Host file containing the API-role PostgreSQL DSN."),
        ("WORKER_DATABASE_URL_PATH", "Host file containing the worker-role PostgreSQL DSN."),
        ("REDIS_URL_PATH", "Host file containing the Redis credential URL."),
        ("IDENTITY_CLIENT_SECRET_PATH", "Host file containing the OAuth client secret."),
        ("SMTP_PASSWORD_PATH", "Host file containing the SMTP password."),
    ):
        variables.append(
            EnvVariable(
                name="PLZL_" + name,
                env_class=EnvClass.REQUIRED,
                purpose=purpose,
                producer=EnvProducer.SECRETS,
                consumer=EnvConsumer.COMPOSE,
                surface=EnvSurface.OPERATOR,
            )
        )
    variables.append(
        EnvVariable(
            name="PLZL_IMAGE",
            env_class=EnvClass.OVERRIDABLE,
            purpose="Immutable runtime image selected for Compose deployment.",
            producer=EnvProducer.RELEASE_PIPELINE,
            consumer=EnvConsumer.COMPOSE,
            surface=EnvSurface.OPERATOR,
            default="plazia-links:local",
        )
    )
    variables.append(
        EnvVariable(
            name="PLZL_SHARED_SOURCE_TOKEN",
            env_class=EnvClass.REQUIRED,
            purpose="CI credential for the private shared-source checkout.",
            producer=EnvProducer.SECRETS,
            consumer=EnvConsumer.RELEASE_ENV,
            surface=EnvSurface.INTERNAL,
            secret=True,
        )
    )
    for name in ("URL", "USER", "PASSWORD"):
        variables.append(
            EnvVariable(
                name="FLYWAY_" + name,
                env_class=EnvClass.REQUIRED,
                purpose=f"Owner Flyway {name.lower()} for the explicit migration job.",
                producer=EnvProducer.SECRETS,
                consumer=EnvConsumer.COMPOSE,
                surface=EnvSurface.OPERATOR,
                secret=True,
            )
        )
    return EnvRegistry(variables=tuple(variables))
