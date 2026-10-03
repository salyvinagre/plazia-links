"""Exercise Links declarations through the shared release projection contracts."""

from pathlib import Path

import pytest
import yaml
from plazia_tooling.release.config import ReleaseConfig
from plazia_tooling.release.configuration import (
    ReleaseConfiguration,
    ReleaseConfigurationProjection,
)
from plazia_tooling.release.secrets import ReleaseSecretProjection

from app.platform.settings import IdentitySettings, PublicSettings, Settings, WorkerSettings

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("override", [False, True])
def test_smtp_configuration_survives_release_projection(monkeypatch, tmp_path, override):
    from plazia_tooling.release.plans import ReleaseExpansion

    config = tmp_path / "smtp.toml"
    config.write_text('[worker]\nsmtp_user="configured-user"\nsmtp_port=465\nsmtp_security="tls"\n')
    config.chmod(0o600)
    monkeypatch.setenv("PLZK_CONFIG_FILE", str(config))
    fields = {"SMTP_USER": "override-user", "SMTP_PORT": "2525", "SMTP_SECURITY": "plain"}
    environment = {"PLZK_WORKER_" + key: value for key, value in fields.items()} if override else {}
    bindings = yaml.safe_load((ROOT / "ops/containers/compose.release.yaml").read_text())
    for key in fields:
        selector = "PLZK_WORKER_" + key
        monkeypatch.delenv(selector, raising=False)
        value = bindings["services"]["worker"]["environment"][selector]
        resolved = (
            ReleaseExpansion.text(value, env=environment)
            if value is not None
            else environment.get(selector)
        )
        if resolved is not None:
            monkeypatch.setenv(selector, resolved)
    settings = WorkerSettings()
    assert (settings.smtp_user, settings.smtp_port, settings.smtp_security) == (
        ("override-user", 2525, "plain") if override else ("configured-user", 465, "tls")
    )


@pytest.mark.parametrize("port", ["invalid", "65536", "-1"])
def test_public_origins_reject_invalid_ports(port):
    with pytest.raises(ValueError):
        PublicSettings(public_base_url=f"https://links.example:{port}").validate_public_origin(
            production=True
        )


@pytest.mark.parametrize("environment", ["dev", "pr-42", "staging", "production"])
def test_ordered_deployment_projection_is_consumed_by_each_runtime(
    monkeypatch, tmp_path, environment
):
    config = ReleaseConfig.from_repo(ROOT)
    selected = config.resolve(environment=environment, env={})
    configurations = ReleaseConfiguration.from_sequence(
        selected.release.values["configuration"],
        env={},
        label="Links configuration",
        stack_services=selected.release.values["stack"]["services"],
    )
    projection = ReleaseConfigurationProjection.materialize(
        repo_root=ROOT,
        plan=environment,
        configurations=configurations,
        directory=tmp_path,
    )
    config_file = projection.resolved[0].path
    monkeypatch.setenv("PLZK_CONFIG_FILE", str(config_file))
    expected = "production" if environment == "production" else "preview"
    assert Settings().environment == WorkerSettings().environment == expected
    assert not IdentitySettings().allow_insecure_loopback
    assert WorkerSettings().smtp_security == "starttls"
    assert config_file.stat().st_mode & 0o077 == 0
    assert not selected.enabled
    assert not config.resolve(environment=environment, destination="remote", env={}).enabled


@pytest.mark.parametrize("environment", ["pr-42", "production"])
def test_public_routing_and_process_origins_share_the_retained_environment(environment):
    from plazia_tooling.release.plans import ReleaseExpansion

    config = ReleaseConfig.from_repo(ROOT)
    selected = config.resolve(environment=environment, env={})
    expected = "links.liberalia.net" if environment == "production" else "links-pr-42.liberalia.net"
    assert selected.application_host == expected
    assert selected.application_origin == "https://" + expected
    context = config.context_env(selected)
    stack = ReleaseExpansion.string_mapping(
        selected.release.values["stack"]["env"], env=context, label="Links stack"
    )
    assert stack["PLZK_IDENTITY_PUBLIC_BASE_URL"] == selected.application_origin
    assert stack["PLZK_IDENTITY_AUDIENCE"] == selected.application_origin + "/api/v1"
    web = selected.release.values["resources"]["web"]
    assert ReleaseExpansion.text(web["public"]["routes"][0]["hosts"][0], env=context) == expected
    assert web["ingress"] == {
        "service": "api",
        "scheme": "http",
        "port": 8000,
        "readiness": {"path": "/health", "status": 200},
    }


def test_provider_claim_keeps_owner_api_worker_credentials_distinct():
    from plazia_tooling.delivery.application.commands.ensure_dependency import DependencyConfig
    from plazia_tooling.release.postgres import PostgresConfig

    root = yaml.safe_load((ROOT.parent / "plazia/.plazia/delivery.yaml").read_text())
    provider = PostgresConfig.from_mapping(
        root["delivery"]["infrastructure"]["capabilities"]["postgres"]["postgres"]
    )
    claim = provider.select(["links"], owner="salyvinagre/plazia-links")[0]
    first, second = (claim.scoped(name) for name in ("pr-42", "production"))
    assert {role.name for role in first.roles}.isdisjoint(role.name for role in second.roles)
    assert len({role.secret for role in first.roles}) == 3
    for role in first.roles:
        assert role.create == role.inherit == (role.key == "links_owner")
    assert {role.placeholder for role in claim.roles} == {None, "appRole", "workerRole"}
    declared = yaml.safe_load((ROOT / ".plazia/delivery.yaml").read_text())
    dependency = declared["delivery"]["dependencies"]["plazia-postgres-links"]
    assert set(dependency["secret_outputs"].values()) == set(claim.secret_outputs)
    selected = ReleaseConfig.from_repo(ROOT).resolve(environment="pr-42", env={})
    assert selected.release.values["dependencies"] == ["plazia-postgres-links"]
    parsed = DependencyConfig.from_mapping("plazia-postgres-links", dependency, repo_root=ROOT)
    assert parsed.infrastructure is not None
    provision = parsed.infrastructure.resolve(release_environment="pr-42", label="Links PostgreSQL")
    assert provision.selection.environment == "preview"
    assert provision.claims[0].owner == "salyvinagre/plazia-links"


def test_shared_secret_projection_mounts_credentials_only_into_their_consumers(tmp_path):
    selected = ReleaseConfig.from_repo(ROOT).resolve(environment="dev", env={})
    values = selected.release.values
    projection = ReleaseSecretProjection.materialize(
        repo_root=tmp_path,
        plan="dev",
        selectors=(*selected.required_secrets, *selected.optional_secrets),
        environment={
            name: "fixture-value"
            for name in (*selected.required_secrets, *selected.optional_secrets)
        },
        attachments=values["secret_attachments"],
        environment_attachments=values.get("secret_environment"),
    )
    payload = yaml.safe_load(projection.compose_file.read_text())["services"]
    api = payload["api"]["environment"]
    worker = payload["worker"]["environment"]
    assert api["PLZK_DATABASE_URL_FILE"].endswith("plzk_database_url")
    assert worker["PLZK_WORKER_DATABASE_URL_FILE"].endswith("plzk_worker_database_url")
    assert "PLZK_SCHEMA_DATABASE_URL_FILE" not in api | worker
    assert "PLZK_IDENTITY_CLIENT_SECRET_FILE" not in worker
    assert "PLZK_WORKER_DATABASE_URL_FILE" not in api
    for service in ("schema-prepare", "schema-finish"):
        assert set(payload[service]["environment"]) == {"PLZK_SCHEMA_DATABASE_URL_FILE"}
    for secret in projection.secrets:
        assert secret.path.stat().st_mode & 0o077 == 0


def test_release_topology_keeps_worker_and_owner_off_public_ingress():
    from plazia_tooling.release.remote_compose import ReleaseRemoteComposeArtifact

    topology = yaml.safe_load((ROOT / "ops/containers/compose.release.yaml").read_text())
    services = topology["services"]
    assert set(services["api"]["networks"]) == {"postgres", "plazia-edge", "plazia-services"}
    assert set(services["worker"]["networks"]) == {"postgres", "plazia-services"}
    for name in ("schema-prepare", "schema-migrate", "schema-finish"):
        assert services[name]["networks"] == ["postgres"]
    worker = services["worker"]["environment"]
    assert set(worker) == {
        "PLZK_WORKER_SMTP_HOST",
        "PLZK_WORKER_SMTP_FROM",
        "PLZK_WORKER_SMTP_USER",
        "PLZK_WORKER_SMTP_PORT",
        "PLZK_WORKER_SMTP_SECURITY",
    }
    assert all(value["external"] for value in topology["networks"].values())
    base = yaml.safe_load((ROOT / "ops/containers/compose.yaml").read_text())
    assert "/health" in base["services"]["api"]["healthcheck"]["test"][-1]
    assert base["services"]["worker"]["healthcheck"]["disable"]
    assert "ports" not in base["services"]["api"]
    assert (
        base["services"]["api"]["depends_on"]["schema-finish"]["condition"]
        == "service_completed_successfully"
    )
    remote = ReleaseConfig.from_repo(ROOT).resolve(
        environment="pr-42", destination="remote", env={}
    )
    assert remote.release.values["stack"]["env"]["PLZK_FLYWAY_PROJECT"] == "./flyway"
    (artifact,) = ReleaseRemoteComposeArtifact.from_sequence(
        remote.release.values["artifacts"], env={}, deploy_dir="/retained/links", label="Links SQL"
    )
    assert artifact.target == "/retained/links/flyway"
    assert artifact.source_path(ROOT).joinpath("migrations/V2__pool_management.sql").is_file()
