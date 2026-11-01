"""Pure declarations on the shared environment model; never load runtime values."""

import json

from plazia_tooling.release.env_model import (
    EnvCategory,
    EnvClass,
    EnvConsumer,
    EnvProducer,
    EnvRegistry,
    EnvSurface,
    EnvVariable,
)
from plazia_tooling.release.stack_environment import RegistryOnlyStackEnvironment
from pydantic import SecretStr

from app.platform.settings import IdentitySettings, OwnerSettings, Settings, WorkerSettings

_GENERATED = frozenset(
    {
        "PLZK_IDENTITY_ISSUER",
        "PLZK_IDENTITY_AUDIENCE",
        "PLZK_IDENTITY_CLIENT_ID",
        "PLZK_IDENTITY_CLIENT_SECRET",
    }
)
_PROVIDED = frozenset({"PLZK_OPENFGA_URL", "PLZK_OPENFGA_STORE_ID", "PLZK_OPENFGA_MODEL_ID"})
_REQUIRED = frozenset(
    {
        "PLZK_WORKER_DATABASE_URL",
        "PLZK_WORKER_SMTP_HOST",
        "PLZK_WORKER_SMTP_FROM",
        "PLZK_DATABASE_URL",
        "PLZK_REDIS_URL",
        "PLZK_SCHEMA_DATABASE_URL",
        "PLZK_OPENFGA_URL",
        "PLZK_OPENFGA_STORE_ID",
        "PLZK_OPENFGA_MODEL_ID",
    }
)


def build_registry() -> EnvRegistry:
    variables = []
    for model in (Settings, WorkerSettings, IdentitySettings, OwnerSettings):
        for name, field in model.model_fields.items():
            selector = str(model.model_config["env_prefix"]) + name.upper()
            secret = field.annotation is SecretStr
            generated = selector in _GENERATED
            required = selector in _REQUIRED
            default = field.default
            variables.append(
                EnvVariable(
                    name=selector,
                    env_class=EnvClass.GENERATED
                    if generated
                    else EnvClass.REQUIRED
                    if required
                    else EnvClass.OVERRIDABLE,
                    purpose=field.description or f"{model.section}: {name.replace('_', ' ')}.",
                    producer=EnvProducer.BOOTSTRAP
                    if generated
                    else EnvProducer.RELEASE_PIPELINE
                    if selector in _PROVIDED
                    else EnvProducer.SECRETS
                    if secret
                    else EnvProducer.TOML_CONFIG,
                    consumer=EnvConsumer.SETTINGS_FIELD,
                    surface=EnvSurface.INTERNAL
                    if generated or selector in _PROVIDED
                    else EnvSurface.OPERATOR,
                    toml_counterpart=None if secret or generated else f"{model.section}.{name}",
                    default=None
                    if secret or required or generated
                    else (default if isinstance(default, str) else json.dumps(default)),
                    secret=secret,
                    file_supported=secret,
                )
            )
    return EnvRegistry(
        variables=tuple(variables)
        + (
            EnvVariable(
                name="PLZK_IDENTITY_OWNER_EMAIL",
                env_class=EnvClass.REQUIRED,
                purpose="Existing Plazia business owner used by Identity's enrollment session.",
                producer=EnvProducer.RELEASE_PIPELINE,
                consumer=EnvConsumer.RELEASE_ENV,
                surface=EnvSurface.OPERATOR,
            ),
            EnvVariable(
                name="PLZK_FLYWAY_PROJECT",
                env_class=EnvClass.OVERRIDABLE,
                purpose="SQL artifact directory selected for the owner schema job.",
                producer=EnvProducer.RELEASE_PIPELINE,
                consumer=EnvConsumer.COMPOSE,
                surface=EnvSurface.INTERNAL,
                default="../../app/platform/persistence/sql",
            ),
            EnvVariable(
                name="PLZK_CONFIG_FILE",
                env_class=EnvClass.OVERRIDABLE,
                purpose="Deployment-owned TOML projection for API, worker and Identity settings.",
                producer=EnvProducer.TOML_CONFIG,
                consumer=EnvConsumer.SETTINGS_FIELD,
                surface=EnvSurface.OPERATOR,
                default="",
            ),
            EnvVariable(
                name="PLZK_FLYWAY_USER_TOML",
                env_class=EnvClass.REQUIRED,
                purpose="Owner-only Flyway connection document for the schema migration job.",
                producer=EnvProducer.SECRETS,
                consumer=EnvConsumer.COMPOSE,
                surface=EnvSurface.OPERATOR,
                secret=True,
                file_supported=True,
            ),
            EnvVariable(
                name="PLZK_IMAGE",
                env_class=EnvClass.OVERRIDABLE,
                purpose="Links runtime image selected for Compose deployment.",
                producer=EnvProducer.RELEASE_PIPELINE,
                consumer=EnvConsumer.COMPOSE,
                surface=EnvSurface.OPERATOR,
                default="plazia-links:local",
            ),
            EnvVariable(
                name="PLZK_SHARED_SOURCE_TOKEN",
                env_class=EnvClass.REQUIRED,
                purpose="CI credential for the private shared-source checkout.",
                producer=EnvProducer.SECRETS,
                consumer=EnvConsumer.RELEASE_ENV,
                surface=EnvSurface.INTERNAL,
                category=EnvCategory.DEVOPS,
                secret=True,
            ),
        )
    )


class LinksEnvironment(RegistryOnlyStackEnvironment):
    """Expose release metadata; Identity's hooks issue the generated bindings."""

    registry = EnvRegistry(
        variables=tuple(
            variable
            for variable in build_registry().variables
            if variable.category is EnvCategory.DOMAIN
        )
    )
