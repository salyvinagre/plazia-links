"""Disposable local boundary proof. Creates and removes only UUID-labelled test resources."""

import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx2
import psycopg
import yaml
from plazia_tooling.release.postgres import PostgresConfig
from plazia_tooling.release.postgres_environment import PostgresStackEnvironment
from plazia_tooling.repo.private_file import PrivateFile
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
ENGINE = os.getenv("CONTAINER", "podman")
NAME = "plzk-acceptance-" + uuid.uuid4().hex[:10]
LABEL = "plzk.acceptance=" + NAME
PG = (
    "public.ecr.aws/docker/library/postgres@sha256:"
    "77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873"
)
FGA = (
    "ghcr.io/openfga/openfga@sha256:"
    "8543200bf85878c968d73da46c4f0e31ba1f63ed3675b71122f1133b0e9d97eb"
)
MAIL = (
    "ghcr.io/axllent/mailpit@sha256:"
    "98b916bd3c8d61f7633a52d3ea2f58d00620cb01ca57ab59edde68c347a95365"
)
REDIS = (
    "docker.io/library/redis@sha256:"
    "1f09a89a207d794a8c61d9edfc26e7c58427de10ccef7c5d18d638df79a63b85"
)


def command(*args, **kwargs):
    return subprocess.run(
        args, check=True, cwd=ROOT, text=True, capture_output=True, **kwargs
    ).stdout.strip()


def port(name, internal):
    return int(command(ENGINE, "port", name, str(internal) + "/tcp").rsplit(":", 1)[1])


def wait_http(url):
    for _ in range(100):
        try:
            if httpx2.get(url, timeout=1).status_code == 200:
                return
        except httpx2.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError("Test service readiness timed out")


def run():
    owned = []
    print("Acceptance target: disposable " + NAME, flush=True)
    command(ENGINE, "network", "create", "--label", LABEL, NAME)
    credentials = TemporaryDirectory(prefix=NAME)
    try:
        for kind, image, ports, args in (
            (
                "postgres",
                PG,
                [5432],
                ["-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_DB=links"],
            ),
            ("redis", REDIS, [6379], []),
            ("openfga", FGA, [8080], []),
            ("mailpit", MAIL, [1025, 8025], []),
        ):
            name = NAME + "-" + kind
            flags = [
                ENGINE,
                "run",
                "-d",
                "--name",
                name,
                "--label",
                LABEL,
                "--network",
                NAME,
                "--network-alias",
                kind,
            ]
            for internal in ports:
                flags.extend(["-p", f"127.0.0.1::{internal}"])
            flags.extend(args)
            flags.append(image)
            if kind == "openfga":
                flags.extend(["run", "--datastore-engine", "memory", "--playground-enabled=false"])
            command(*flags)
            owned.append(name)
        pgport = port(NAME + "-postgres", 5432)
        owner = f"postgresql://postgres@127.0.0.1:{pgport}/links"
        for _ in range(100):
            try:
                # Probe the mapped TCP endpoint, not initdb's temporary local server.
                with psycopg.connect(owner, connect_timeout=1, autocommit=True) as connection:
                    connection.execute("SELECT 1")
                break
            except psycopg.OperationalError:
                time.sleep(0.1)
        else:
            raise RuntimeError("PostgreSQL did not become ready")
        catalog = yaml.safe_load((ROOT.parent / "plazia/.plazia/delivery.yaml").read_text())
        provider = PostgresConfig.from_mapping(
            catalog["delivery"]["infrastructure"]["capabilities"]["postgres"]["postgres"]
        )
        claim = provider.select(["links"], owner="salyvinagre/plazia-links")[0].scoped(NAME)
        roles = {role.key: role.name for role in claim.roles}
        with psycopg.connect(owner, autocommit=True) as connection:
            for role in claim.roles:
                connection.execute(
                    sql.SQL("CREATE ROLE {} LOGIN {}").format(
                        sql.Identifier(role.name),
                        sql.SQL("INHERIT" if role.inherit else "NOINHERIT"),
                    )
                )
            connection.execute(
                sql.SQL("ALTER DATABASE links OWNER TO {}").format(sql.Identifier(claim.owner_role))
            )
            connection.execute(
                sql.SQL("COMMENT ON DATABASE links IS {}").format(
                    sql.Literal(
                        json.dumps(
                            {
                                "provider": "plazia-postgres-v1",
                                "owner": claim.owner,
                                "environment": claim.environment,
                                "roles": roles,
                            }
                        )
                    )
                )
            )
        flyway = Path(credentials.name) / "flyway-user.toml"
        PrivateFile(flyway).write(
            PostgresStackEnvironment.flyway_configuration(
                f"postgresql://{roles['links_owner']}:fixture@postgres:5432/links",
                roles=roles,
                placeholders={
                    role.placeholder: role.name for role in claim.roles if role.placeholder
                },
            )
        )
        env = {
            **os.environ,
            "POSTGRES_OWNER_TEST_URL": owner,
            "POSTGRES_TEST_URL": owner.replace("postgres@", roles["links_app"] + "@"),
            "POSTGRES_WORKER_TEST_URL": owner.replace("postgres@", roles["links_worker"] + "@"),
            "PLZK_SCHEMA_DATABASE_URL": owner.replace("postgres@", roles["links_owner"] + "@"),
            "PLZK_REDIS_URL": f"redis://127.0.0.1:{port(NAME + '-redis', 6379)}/0",
            "PLZK_FLYWAY_USER_TOML_FILE": str(flyway),
            "FLYWAY_NETWORK_ARGS": "--network " + NAME,
            "CONTAINER": ENGINE,
        }
        # Verify a direct fresh install separately from the populated upgrade.
        with psycopg.connect(owner, autocommit=True) as connection:
            connection.execute(
                sql.SQL("CREATE DATABASE links_fresh OWNER {}").format(
                    sql.Identifier(claim.owner_role)
                )
            )
            marker = connection.execute(
                "SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname='links'"
            ).fetchone()[0]
            connection.execute(
                sql.SQL("COMMENT ON DATABASE links_fresh IS {}").format(sql.Literal(marker))
            )
        fresh = Path(credentials.name) / "flyway-fresh.toml"
        PrivateFile(fresh).write(flyway.read_text().replace("/links", "/links_fresh"))
        subprocess.run(
            ["make", "migrate", "schema-check"],
            cwd=ROOT,
            check=True,
            env=env
            | {
                "PLZK_SCHEMA_DATABASE_URL": env["PLZK_SCHEMA_DATABASE_URL"] + "_fresh",
                "PLZK_FLYWAY_USER_TOML_FILE": str(fresh),
            },
        )
        print("Fresh V5 installation and admission verified.", flush=True)
        # Exercise admission of a real, populated V1 target through the same
        # pinned Flyway invocation as the normal guarded migration.
        subprocess.run(
            ["make", "flyway-migrate"],
            cwd=ROOT,
            env=env | {"FLYWAY_NETWORK_ARGS": "--network " + NAME + " -e FLYWAY_TARGET=1"},
            check=True,
        )
        from shared_identity import OrganizationId

        organization = OrganizationId.new()
        with psycopg.connect(owner) as connection:
            assert connection.execute(
                "SELECT version FROM links_migrations.flyway_schema_history "
                "WHERE type='SQL' ORDER BY installed_rank"
            ).fetchall() == [("1",)]
            connection.execute(
                "INSERT INTO access.organizations (issuer,organization_id,name) "
                "VALUES ('https://identity.example.test',%s,'Upgrade fixture')",
                (organization.uuid,),
            )
            pool = connection.execute(
                "INSERT INTO links.pools (organization_id,name) VALUES (%s,'Preserved pool') "
                "RETURNING id",
                (organization.uuid,),
            ).fetchone()[0]
            link = connection.execute(
                "INSERT INTO links.links (organization_id,pool_id,short_code) "
                "VALUES (%s,%s,'upgrade1') RETURNING id",
                (organization.uuid, pool),
            ).fetchone()[0]
            subscription = connection.execute(
                "INSERT INTO links.subscriptions (organization_id,link_id,email) "
                "VALUES (%s,%s,'upgrade@example.com') RETURNING id",
                (organization.uuid, link),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO platform.activation_emails (organization_id,link_id,subscription_id) "
                "VALUES (%s,%s,%s)",
                (organization.uuid, link, subscription),
            )
        subprocess.run(
            ["make", "flyway-migrate"],
            cwd=ROOT,
            env=env | {"FLYWAY_NETWORK_ARGS": "--network " + NAME + " -e FLYWAY_TARGET=2"},
            check=True,
        )
        subprocess.run(
            ["make", "flyway-migrate"],
            cwd=ROOT,
            env=env | {"FLYWAY_NETWORK_ARGS": "--network " + NAME + " -e FLYWAY_TARGET=4"},
            check=True,
        )
        with psycopg.connect(owner) as connection:
            connection.execute("SELECT links.record_visit(%s,'upgrade1','waiting')", (link,))
        subprocess.run(["make", "migrate"], cwd=ROOT, env=env, check=True)
        with psycopg.connect(owner) as connection:
            assert connection.execute(
                "SELECT name FROM links.pools WHERE id=%s", (pool,)
            ).fetchone() == ("Preserved pool",)
            assert connection.execute(
                "SELECT short_code FROM links.links WHERE id=%s", (link,)
            ).fetchone() == ("upgrade1",)
            assert connection.execute(
                "SELECT waiting_views FROM links.statistics WHERE link_id=%s", (link,)
            ).fetchone() == (1,)
            connection.execute("DELETE FROM links.pools WHERE id=%s", (pool,))
            for table in ("links.links", "links.subscriptions", "platform.activation_emails"):
                assert (
                    connection.execute(
                        f"SELECT count(*) FROM {table} WHERE organization_id=%s",
                        (organization.uuid,),
                    ).fetchone()[0]
                    == 0
                )
            connection.execute(
                "DELETE FROM access.organizations WHERE organization_id=%s", (organization.uuid,)
            )
        print(
            "Populated V1 → V4 → V5 upgrade preserves statistics and deletion chains.", flush=True
        )
        fga = f"http://127.0.0.1:{port(NAME + '-openfga', 8080)}"
        wait_http(fga + "/healthz")
        store = httpx2.post(fga + "/stores", json={"name": NAME})
        store.raise_for_status()
        storeid = store.json()["id"]
        from plazia_authlib.authz.resources import AuthzResources

        modelpath = AuthzResources.package().openfga_model
        # Compile the canonical model using the existing official CLI.
        cli = (
            "docker.io/openfga/cli@sha256:"
            "568b94a978b080d95d5a905719b40feebda3badda1499d331e06950c1be12a17"
        )
        cli = os.getenv("OPENFGA_CLI_IMAGE", cli)
        model = json.loads(
            command(
                ENGINE,
                "run",
                "--rm",
                "-v",
                str(modelpath) + ":/model.fga:ro",
                cli,
                "model",
                "transform",
                "--file",
                "/model.fga",
            )
        )
        response = httpx2.post(fga + f"/stores/{storeid}/authorization-models", json=model)
        response.raise_for_status()
        mail = f"http://127.0.0.1:{port(NAME + '-mailpit', 8025)}"
        wait_http(mail + "/api/v1/messages")
        env.update(
            {
                "PLZK_OPENFGA_URL": fga,
                "PLZK_OPENFGA_STORE_ID": storeid,
                "PLZK_OPENFGA_MODEL_ID": response.json()["authorization_model_id"],
                "SMTP_TEST_PORT": str(port(NAME + "-mailpit", 1025)),
                "MAILPIT_TEST_URL": mail,
                "IDENTITY_E2E": "1",
            }
        )
        subprocess.run(["make", "integration"], cwd=ROOT, env=env, check=True)
    finally:
        credentials.cleanup()
        for name in reversed(owned):
            command(ENGINE, "rm", "-f", name)
        command(ENGINE, "network", "rm", NAME)
        residue = command(
            ENGINE, "ps", "-a", "--filter", "label=" + LABEL, "--format", "{{.Names}}"
        )
        if residue:
            raise RuntimeError("Acceptance resources remain: " + residue)
        print("Acceptance resources removed; residue check empty.", flush=True)


if __name__ == "__main__":
    run()
