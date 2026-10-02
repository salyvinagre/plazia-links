"""Real Chromium, PostgreSQL 18, Redis, OpenFGA and SMTP capture; local OAuth issuer."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from tests.identity_support import ORG_A, LocalIssuer

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.getenv("IDENTITY_E2E") != "1", reason="Dedicated acceptance infrastructure required"
    ),
]


@pytest.fixture(scope="module", params=["container", "serverless"])
def live_application(request):
    from playwright.sync_api import sync_playwright

    issuer = LocalIssuer()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "PLZL_ENVIRONMENT": "test",
        "PLZL_DEPLOYMENT_MODE": request.param,
        "PLZL_DATABASE_URL": os.environ["POSTGRES_TEST_URL"],
        "PLZL_IDENTITY_ISSUER": issuer.url,
        "PLZL_IDENTITY_AUDIENCE": "https://links.example.test/api/v1",
        "PLZL_IDENTITY_CLIENT_ID": issuer.client_id,
        "PLZL_IDENTITY_CLIENT_SECRET": issuer.client_secret,
        "PLZL_IDENTITY_PUBLIC_BASE_URL": base,
        "PLZL_IDENTITY_ALLOW_INSECURE_LOOPBACK": "true",
        "PLZL_RATE_LIMIT_ENABLED": "false",
    }
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [sys.executable, "-m", "app.cli", "bind-organization", ORG_A, "--name", "Browser tenant"],
        cwd=root,
        env=env | {"PLZL_DATABASE_URL": os.environ["POSTGRES_OWNER_TEST_URL"]},
        check=True,
        capture_output=True,
    )
    fga = os.environ["PLZL_OPENFGA_URL"]
    store = os.environ["PLZL_OPENFGA_STORE_ID"]
    tuple_key = {
        "user": "user:usr_0199a112345670008000000000000003",
        "relation": "owner",
        "object": f"organization:{ORG_A}",
    }
    httpx.post(
        fga + f"/stores/{store}/write",
        json={
            "writes": {"tuple_keys": [tuple_key]},
            "authorization_model_id": os.environ["PLZL_OPENFGA_MODEL_ID"],
        },
    ).raise_for_status()
    output = root / "output" / "playwright"
    output.mkdir(parents=True, exist_ok=True)
    with (output / f"server-{request.param}.log").open("w+") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.index:app",
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
                    raise AssertionError((output / f"server-{request.param}.log").read_text())
                try:
                    if httpx.get(base + "/health", timeout=0.5).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Server did not become ready")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    yield base, issuer, browser, request.param
                finally:
                    browser.close()
        finally:
            process.terminate()
            process.wait(timeout=10)
            issuer.close()
            httpx.post(
                fga + f"/stores/{store}/write",
                json={
                    "deletes": {"tuple_keys": [tuple_key]},
                    "authorization_model_id": os.environ["PLZL_OPENFGA_MODEL_ID"],
                },
            ).raise_for_status()


def test_reserve_subscribe_activate_and_delivery(live_application):
    import asyncio

    from playwright.sync_api import expect
    from shared_notifications.email_smtp import SmtpEmailTransport, SmtpEmailTransportConfiguration

    from app.contexts.links.adapters.repositories.sql.notifications import PostgresDeliveryQueue
    from app.contexts.links.application.workflows.notifications import ActivationEmailsWorkflow

    base, issuer, browser, mode = live_application
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.goto(base + "/login")
    page.wait_for_url(base + "/dashboard/links")
    page.get_by_label("Pool name").fill("Early access")
    page.get_by_label("Number of links").fill("2")
    page.get_by_role("button", name="Reserve links").click()
    rows = page.get_by_role("row").filter(has_text="Awaiting destination")
    expect(rows).to_have_count(2)
    code = rows.first.locator("td").first.get_by_role("link").inner_text().strip("/")
    link = rows.first.get_by_role("link", name="Activate")
    screenshot = Path("output/playwright")
    page.screenshot(path=str(screenshot / f"pool-{mode}-desktop.png"), full_page=True)
    visitor_context = browser.new_context(viewport={"width": 390, "height": 844})
    visitor = visitor_context.new_page()
    visitor.goto(base + "/" + code)
    expect(visitor.get_by_role("heading", name="This link is coming soon")).to_be_visible()
    visitor.screenshot(path=str(screenshot / f"waiting-{mode}-mobile.png"), full_page=True)
    visitor.get_by_label("Email address").fill("subscriber@example.com")
    visitor.get_by_role("button", name="Notify me").click()
    expect(visitor.get_by_role("heading", name="You’re on the list")).to_be_visible()
    rows.first.locator("summary").click()
    link.click()
    page.get_by_label("Destination URL").fill("https://example.com/ready")
    page.get_by_role("button", name="Save changes").click()
    expect(page.get_by_role("heading", name="Links", exact=True)).to_be_visible()
    assert (
        httpx.get(base + "/" + code, follow_redirects=False).headers["location"]
        == "https://example.com/ready"
    )
    queue = PostgresDeliveryQueue(os.environ["POSTGRES_WORKER_TEST_URL"])
    smtp = SmtpEmailTransport(
        configuration=SmtpEmailTransportConfiguration(
            host="127.0.0.1",
            port=int(os.environ["SMTP_TEST_PORT"]),
            from_address="links@example.com",
        )
    )
    workflow = ActivationEmailsWorkflow(queue, smtp, base)

    async def deliver():
        while await workflow.run_once():
            pass

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(asyncio.run, deliver()).result(timeout=30)
    messages = httpx.get(os.environ["MAILPIT_TEST_URL"] + "/api/v1/messages").json()["messages"]
    matching = [
        message
        for message in messages
        if message["Subject"] == "Your link is ready"
        and any(recipient["Address"] == "subscriber@example.com" for recipient in message["To"])
    ]
    assert matching
    assert any(
        f"{base}/{code}"
        in httpx.get(os.environ["MAILPIT_TEST_URL"] + f"/api/v1/message/{message['ID']}").json()[
            "Text"
        ]
        for message in matching
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base + "/dashboard/links")
    page.screenshot(path=str(screenshot / f"pool-{mode}-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert visitor.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert context.request.get(base + "/api/v1/links").status == 401
    page.get_by_role("button", name="Sign out").click()
    expect(page.get_by_role("heading", name="Signed out of Plazia Links")).to_be_visible()
    visitor_context.close()
    context.close()
