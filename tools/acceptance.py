"""Disposable local boundary proof. Creates and removes only UUID-labelled test resources."""

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[1]
ENGINE = os.getenv("CONTAINER", "podman")
NAME = "plzl-acceptance-" + uuid.uuid4().hex[:10]
LABEL = "plzl.acceptance=" + NAME
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
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError("Test service readiness timed out")


def run():
    owned = []
    print("Acceptance target: disposable " + NAME, flush=True)
    command(ENGINE, "network", "create", "--label", LABEL, NAME)
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
        command(
            ENGINE,
            "exec",
            NAME + "-postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            "links",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "CREATE ROLE links_app LOGIN; CREATE ROLE links_worker LOGIN;",
        )
        env = {
            **os.environ,
            "POSTGRES_OWNER_TEST_URL": owner,
            "POSTGRES_TEST_URL": owner.replace("postgres@", "links_app@"),
            "POSTGRES_WORKER_TEST_URL": owner.replace("postgres@", "links_worker@"),
            "PLZL_DATABASE_URL": owner,
            "PLZL_REDIS_URL": f"redis://127.0.0.1:{port(NAME + '-redis', 6379)}/0",
            "FLYWAY_URL": "jdbc:postgresql://postgres:5432/links",
            "FLYWAY_USER": "postgres",
            "FLYWAY_NETWORK_ARGS": "--network " + NAME,
            "CONTAINER": ENGINE,
        }
        subprocess.run(["make", "migrate"], cwd=ROOT, env=env, check=True)
        fga = f"http://127.0.0.1:{port(NAME + '-openfga', 8080)}"
        wait_http(fga + "/healthz")
        store = httpx.post(fga + "/stores", json={"name": NAME})
        store.raise_for_status()
        storeid = store.json()["id"]
        from shared_authz.resources import AuthzResources

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
        response = httpx.post(fga + f"/stores/{storeid}/authorization-models", json=model)
        response.raise_for_status()
        mail = f"http://127.0.0.1:{port(NAME + '-mailpit', 8025)}"
        wait_http(mail + "/api/v1/messages")
        env.update(
            {
                "PLZL_OPENFGA_URL": fga,
                "PLZL_OPENFGA_STORE_ID": storeid,
                "PLZL_OPENFGA_MODEL_ID": response.json()["authorization_model_id"],
                "SMTP_TEST_PORT": str(port(NAME + "-mailpit", 1025)),
                "MAILPIT_TEST_URL": mail,
                "IDENTITY_E2E": "1",
            }
        )
        subprocess.run(["make", "integration"], cwd=ROOT, env=env, check=True)
    finally:
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
