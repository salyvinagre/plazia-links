"""Real Chromium + local OAuth issuer + PostgreSQL 18 + Redis.

Set IDENTITY_E2E=1 and POSTGRES_TEST_URL only for a dedicated migrated test DB.
The issuer is a fixture, not a live Plazia Identity deployment.
"""

import asyncio
import faulthandler
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid7

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.identity import WorkspaceIdentityBinding
from tests.identity_support import ORG_A, LocalIssuer

pytestmark = pytest.mark.skipif(os.getenv("IDENTITY_E2E") != "1", reason="IDENTITY_E2E not enabled")


@pytest.fixture(scope="module")
def live_application(tmp_path_factory):
    from playwright.sync_api import sync_playwright

    faulthandler.enable()
    postgres = os.environ["POSTGRES_TEST_URL"]
    assert postgres.startswith("postgresql+asyncpg://")
    root = Path(__file__).resolve().parents[2]
    issuer = LocalIssuer()
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "AUTH_MODE": "identity",
        "ENVIRONMENT": "test",
        "DATABASE_URL": postgres,
        "IDENTITY_ISSUER": issuer.url,
        "IDENTITY_AUDIENCE": "https://links.example.test/api",
        "IDENTITY_CLIENT_ID": issuer.client_id,
        "IDENTITY_CLIENT_SECRET": issuer.client_secret,
        "IDENTITY_PUBLIC_BASE_URL": base,
        "IDENTITY_ALLOW_INSECURE_LOOPBACK": "true",
        "DEFAULT_DOMAIN": base,
        "RATE_LIMIT_ENABLED": "false",
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli",
            "bind-organization",
            ORG_A,
            "--name",
            "Browser test tenant",
        ],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    log_path = tmp_path_factory.mktemp("browser") / "server.log"
    with log_path.open("w+") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(150):
                if process.poll() is not None:
                    raise AssertionError(log_path.read_text())
                try:
                    if httpx.get(base + "/health", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Application did not become ready: " + log_path.read_text())
            print("Identity E2E: application is ready; starting Chromium", flush=True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    args=["--host-resolver-rules=MAP content.example.test 127.0.0.1"],
                    timeout=30000,
                )
                try:
                    yield base, issuer, browser
                finally:
                    browser.close()
        finally:
            process.terminate()
            process.wait(timeout=10)
            issuer.close()
            print("Application log:\n" + log_path.read_text())


@pytest.fixture
def signed_in_page(live_application):
    base, issuer, browser = live_application
    context = browser.new_context()
    context.set_default_timeout(10000)
    context.set_default_navigation_timeout(15000)
    page = context.new_page()
    page.goto(base + "/login")
    page.wait_for_url(base + "/dashboard/links")
    yield page, context, base, issuer
    context.close()


def test_sign_in_create_edit_redirect_and_revoke_session(signed_in_page):
    page, context, base, issuer = signed_in_page
    from playwright.sync_api import expect

    code = "e" + uuid7().hex[-8:]
    # A real local destination behind a controlled DNS name, not an API route mock.
    target = issuer.url.replace("127.0.0.1", "content.example.test") + "/content"
    expect(page.get_by_role("heading", name="Links", exact=True)).to_be_visible()
    page.get_by_role("link", name="Create link", exact=True).click()
    page.get_by_label("Destination URL").fill(target + "?before=1")
    page.get_by_label("Title", exact=False).fill("Browser workflow " + code)
    page.get_by_label("Short code", exact=False).fill(code)
    page.get_by_role("button", name="Create link", exact=True).click()
    row = page.get_by_role("row").filter(has_text="Browser workflow " + code)
    expect(row).to_be_visible()
    row.get_by_role("link", name="Edit", exact=True).click()
    page.get_by_label("Destination URL").fill(target + "?after=1")
    page.get_by_role("button", name="Save changes").click()
    row = page.get_by_role("row").filter(has_text="Browser workflow " + code)
    expect(row).to_contain_text("after=1")
    visitor = context.new_page()
    visitor.goto(base + "/" + code)
    expect(visitor.get_by_role("heading", name="Linked content")).to_be_visible()
    assert visitor.url == target + "?after=1"
    visitor.close()
    cookies = context.cookies(base)
    session = next(cookie for cookie in cookies if cookie["name"] == "plazia_links_session")
    assert session["httpOnly"] and "." not in session["value"]
    assert (
        page.evaluate("Object.keys(localStorage).length + Object.keys(sessionStorage).length") == 0
    )
    # Cookies alone never authenticate the management API.
    assert context.request.get(base + "/api/v1/links").status == 401
    page.get_by_role("button", name="Sign out").click()
    expect(page.get_by_role("heading", name="Signed out of Plazia Links")).to_be_visible()
    # Reusing the old browser handle cannot restore a revoked server-side session.
    replay = httpx.get(
        base + "/dashboard/links",
        cookies={session["name"]: session["value"]},
        follow_redirects=False,
    )
    assert replay.status_code == 303 and replay.headers["location"] == "/login"
    assert issuer.token_requests[-1]["code_verifier"]


def test_browser_form_csrf_is_enforced(signed_in_page):
    page, context, base, issuer = signed_in_page
    from playwright.sync_api import expect

    page.get_by_role("link", name="Create link", exact=True).click()
    page.get_by_label("Destination URL").fill("https://content.example.test/page")
    page.locator('main input[name="csrf_token"]').evaluate("element => element.value = 'tampered'")
    page.get_by_role("button", name="Create link", exact=True).click()
    expect(page.locator("body")).to_contain_text("csrf_rejected")
    assert page.url == base + "/dashboard/links"


def test_m2m_dpop_and_replay_against_real_redis(live_application):
    base, issuer, _ = live_application
    key, jkt = issuer.proof_key()
    token = issuer.access(sub="app_machine", client_id="machine", cnf={"jkt": jkt})
    proof = issuer.proof(token, key, "POST", base + "/api/v1/links")
    headers = {"Authorization": "DPoP " + token, "DPoP": proof}
    response = httpx.post(
        base + "/api/v1/links",
        headers=headers,
        json={"destination_url": "https://content.example.test/page"},
    )
    assert response.status_code == 201, response.text
    # A fresh HTTP client still shares replay consumption via Redis.
    assert (
        httpx.post(
            base + "/api/v1/links",
            headers=headers,
            json={"destination_url": "https://content.example.test/page"},
        ).status_code
        == 401
    )


def test_operator_disabling_binding_revokes_existing_browser_access(signed_in_page):
    page, context, base, issuer = signed_in_page

    async def set_active(active):
        engine = create_async_engine(os.environ["POSTGRES_TEST_URL"])
        async with engine.begin() as connection:
            await connection.execute(
                WorkspaceIdentityBinding.__table__.update()
                .where(
                    WorkspaceIdentityBinding.issuer == issuer.url,
                    WorkspaceIdentityBinding.organization_id == ORG_A,
                )
                .values(is_active=active)
            )
        await engine.dispose()

    # Playwright's sync API owns an event loop on this thread.
    with ThreadPoolExecutor(max_workers=1) as runner:
        runner.submit(asyncio.run, set_active(False)).result(timeout=15)
        try:
            response = page.goto(base + "/dashboard/links")
            assert response.status == 403
        finally:
            runner.submit(asyncio.run, set_active(True)).result(timeout=15)
