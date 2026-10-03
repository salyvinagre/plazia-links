"""Real Chromium, PostgreSQL 18, Redis, OpenFGA and SMTP capture; local OAuth issuer."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx2
import pytest

from tests.identity_support import ORG_A, LinksIssuer

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.getenv("IDENTITY_E2E") != "1", reason="Dedicated acceptance infrastructure required"
    ),
]


@pytest.fixture(scope="module", params=["container", "serverless"])
def live_application(request):
    from playwright.sync_api import sync_playwright

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    issuer = LinksIssuer(public_base=base)
    env = {
        **os.environ,
        "PLZK_ENVIRONMENT": "test",
        "PLZK_DEPLOYMENT_MODE": request.param,
        "PLZK_DATABASE_URL": os.environ["POSTGRES_TEST_URL"],
        "PLZK_IDENTITY_ISSUER": issuer.url,
        "PLZK_IDENTITY_AUDIENCE": "https://links.example.test/api/v1",
        "PLZK_IDENTITY_CLIENT_ID": issuer.identity.client.client_id,
        "PLZK_IDENTITY_CLIENT_SECRET": issuer.identity.client.client_secret,
        "PLZK_IDENTITY_PUBLIC_BASE_URL": base,
        "PLZK_IDENTITY_ALLOW_INSECURE_LOOPBACK": "true",
        "PLZK_RATE_LIMIT_ENABLED": "false",
    }
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [sys.executable, "-m", "app.cli", "bind-organization", ORG_A, "--name", "Browser tenant"],
        cwd=root,
        env=env | {"PLZK_SCHEMA_DATABASE_URL": os.environ["POSTGRES_OWNER_TEST_URL"]},
        check=True,
        capture_output=True,
    )
    fga = os.environ["PLZK_OPENFGA_URL"]
    store = os.environ["PLZK_OPENFGA_STORE_ID"]
    tuple_key = {
        "user": "user:usr_0199a112345670008000000000000003",
        "relation": "owner",
        "object": f"organization:{ORG_A}",
    }
    httpx2.post(
        fga + f"/stores/{store}/write",
        json={
            "writes": {"tuple_keys": [tuple_key]},
            "authorization_model_id": os.environ["PLZK_OPENFGA_MODEL_ID"],
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
                    if httpx2.get(base + "/health", timeout=0.5).status_code == 200:
                        break
                except httpx2.HTTPError:
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
            httpx2.post(
                fga + f"/stores/{store}/write",
                json={
                    "deletes": {"tuple_keys": [tuple_key]},
                    "authorization_model_id": os.environ["PLZK_OPENFGA_MODEL_ID"],
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
        httpx2.get(base + "/" + code, follow_redirects=False).headers["location"]
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
    messages = httpx2.get(os.environ["MAILPIT_TEST_URL"] + "/api/v1/messages").json()["messages"]
    matching = [
        message
        for message in messages
        if message["Subject"] == "Your link is ready"
        and any(recipient["Address"] == "subscriber@example.com" for recipient in message["To"])
    ]
    assert matching
    assert any(
        f"{base}/{code}"
        in httpx2.get(os.environ["MAILPIT_TEST_URL"] + f"/api/v1/message/{message['ID']}").json()[
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


@pytest.mark.parametrize("width", [1280, 390])
def test_manage_pools_and_delete_a_selection(live_application, width):
    from playwright.sync_api import TimeoutError as BrowserTimeoutError
    from playwright.sync_api import expect

    base, _, browser, mode = live_application
    context = browser.new_context(viewport={"width": width, "height": 900})
    page = context.new_page()
    page.goto(base + "/login")
    page.wait_for_url(base + "/dashboard/links")
    keep = f"Keep-{mode}-{width}"
    page.get_by_label("Pool name").fill(keep)
    page.get_by_label("Number of links").fill("1")
    page.get_by_role("button", name="Reserve links").click()
    expect(page.get_by_role("heading", name=keep, exact=True)).to_be_visible()
    name = f"Manage-{mode}-{width}"
    page.get_by_label("Pool name").fill(name)
    page.get_by_label("Number of links").fill("4")
    page.get_by_role("button", name="Reserve links").click()
    expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible()
    pool_url = page.url
    actions = page.get_by_label("Pool actions", exact=True)
    assert actions.evaluate(
        "element => [element.offsetWidth, element.offsetHeight]"
    ) == page.locator("tbody summary").first.evaluate(
        "element => [element.offsetWidth, element.offsetHeight]"
    )
    items = page.locator("[data-select-link]")
    expect(items).to_have_count(4)
    for item in items.all():
        expect(item).to_be_hidden()
    expect(page.get_by_label("Rename pool")).to_be_hidden()
    expect(page.locator("#delete-selection")).to_be_hidden()
    page.screenshot(
        path=f"output/playwright/pool-actions-{mode}-{width}.png",
        full_page=True,
        animations="disabled",
    )
    actions.focus()
    actions.press("Enter")
    expect(page.get_by_role("button", name="Delete links", exact=True)).to_be_visible()
    actions.press("Escape")
    expect(actions).to_be_focused()
    expect(page.get_by_role("button", name="Delete links", exact=True)).to_be_hidden()
    actions.click()
    page.screenshot(
        path=f"output/playwright/pool-menu-{mode}-{width}.png",
        full_page=True,
        animations="disabled",
    )
    actions.press("Tab")
    expect(page.get_by_role("button", name="Rename pool", exact=True)).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.get_by_label("Rename pool")).to_be_focused()
    page.get_by_label("Rename pool").fill("Cancelled name")
    page.get_by_role("link", name="Cancel", exact=True).click()
    expect(page.get_by_label("Rename pool")).to_be_hidden()
    expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible()
    actions.click()
    page.get_by_role("button", name="Rename pool", exact=True).click()
    page.get_by_label("Rename pool").fill(name + "-renamed")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("heading", name=name + "-renamed", exact=True)).to_be_visible()
    assert page.url == pool_url
    expect(page.get_by_label("Rename pool")).to_be_hidden()
    actions.click()
    page.get_by_role("button", name="Delete links", exact=True).click()
    expect(items.first).to_be_focused()
    deleting = page.get_by_role("button", name="Delete selected")
    expect(deleting).to_be_disabled()
    page.get_by_label("Select all links", exact=True).check()
    expect(page.get_by_text("All 4 selected", exact=True)).to_be_visible()
    expect(items.first).to_be_disabled()
    page.get_by_label("Select all links", exact=True).uncheck()
    items.nth(0).check()
    items.nth(1).check()
    expect(page.get_by_text("2 selected", exact=True)).to_be_visible()
    assert page.get_by_label("Select all links", exact=True).evaluate(
        "element => element.indeterminate"
    )
    page.get_by_role("button", name="Cancel selection", exact=True).click()
    expect(actions).to_be_focused()
    expect(page.locator("#delete-selection")).to_be_hidden()
    for item in items.all():
        expect(item).to_be_hidden()
        expect(item).not_to_be_checked()
    actions.click()
    page.get_by_role("button", name="Delete links", exact=True).click()
    expect(deleting).to_be_disabled()
    items.nth(0).check()
    items.nth(1).check()
    selected = [items.nth(i).input_value() for i in (0, 1)]
    remaining = [items.nth(i).input_value() for i in (2, 3)]
    page.screenshot(
        path=f"output/playwright/pool-management-{mode}-{width}.png",
        full_page=True,
        animations="disabled",
    )
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.once("dialog", lambda dialog: dialog.dismiss())
    with pytest.raises(BrowserTimeoutError):
        with page.expect_request(
            lambda request: request.method == "POST" and "/dashboard/links/delete" in request.url,
            timeout=500,
        ):
            deleting.click()
    expect(items).to_have_count(4)
    expect(page.get_by_text("2 selected", exact=True)).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    deleting.click()
    expect(items).to_have_count(2)
    assert page.url == pool_url
    assert [item.input_value() for item in items.all()] == remaining
    assert not set(selected) & set(remaining)
    expect(page.get_by_text("2 links in this pool", exact=True)).to_be_visible()
    expect(page.locator("#delete-selection")).to_be_hidden()
    expect(items.first).to_be_hidden()
    actions.click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Delete pool", exact=True).click()
    page.wait_for_url(base + "/dashboard/links")
    expect(page.get_by_role("link", name=name + "-renamed")).to_have_count(0)
    page.get_by_label("Link actions", exact=True).click()
    page.get_by_role("button", name="Delete links", exact=True).click()
    expect(page.locator("[data-select-link]").first).to_be_visible()
    page.get_by_role("button", name="Cancel selection", exact=True).click()
    expect(page.get_by_label("Link actions", exact=True)).to_be_focused()
    expect(page.locator("[data-select-link]").first).to_be_hidden()
    page.get_by_role("link", name=keep + " 1", exact=True).click()
    expect(page.locator("[data-select-link]")).to_have_count(1)
    # Newer pools push the surviving pool beyond the first navigation page.
    import psycopg
    from shared_identity import OrganizationId

    from app.kernel.ids import PoolId

    ids = [PoolId.new().uuid for _ in range(100)]
    with psycopg.connect(os.environ["POSTGRES_OWNER_TEST_URL"]) as connection:
        connection.cursor().executemany(
            "INSERT INTO links.pools (id, organization_id, name) VALUES (%s, %s, %s)",
            [(id, OrganizationId(ORG_A).uuid, f"Navigation {i}") for i, id in enumerate(ids)],
        )
    try:
        page.goto(base + "/dashboard/links")
        page.get_by_role("link", name="Next pools", exact=True).click()
        page.get_by_role("link", name=keep + " 1", exact=True).click()
        expect(page.get_by_role("heading", name=keep, exact=True)).to_be_visible()
        assert "pool_page=2" in page.url
        actions.click()
        page.get_by_role("button", name="Rename pool", exact=True).click()
        page.get_by_label("Rename pool").fill(keep + "-renamed")
        page.get_by_role("button", name="Save", exact=True).click()
        expect(page.get_by_role("heading", name=keep + "-renamed", exact=True)).to_be_visible()
        assert "pool_page=2" in page.url
        expect(page.get_by_role("link", name="Previous pools", exact=True)).to_be_visible()
        expect(page.get_by_label("Rename pool")).to_be_hidden()
        page.screenshot(
            path=f"output/playwright/pool-navigation-{mode}-{width}.png",
            full_page=True,
            animations="disabled",
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        actions.click()
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Delete pool", exact=True).click()
        page.wait_for_url(base + "/dashboard/links?pool_page=2")
        expect(page.get_by_role("heading", name=keep + "-renamed", exact=True)).to_have_count(0)
        # All means the matching collection, including links beyond the visible page.
        across = f"Across-{mode}-{width}"
        page.get_by_label("Pool name").fill(across)
        page.get_by_label("Number of links").fill("21")
        page.get_by_role("button", name="Reserve links").click()
        expect(page.get_by_role("heading", name=across, exact=True)).to_be_visible()
        expect(items).to_have_count(20)
        actions.click()
        page.get_by_role("button", name="Delete links", exact=True).click()
        for item in items.all():
            item.check()
        expect(page.get_by_text("20 selected", exact=True)).to_be_visible()
        expect(page.get_by_label("Select all links", exact=True)).not_to_be_checked()
        page.get_by_label("Select all links", exact=True).check()
        expect(page.get_by_text("All 21 selected", exact=True)).to_be_visible()
        expect(items.first).to_be_disabled()
        page.once("dialog", lambda dialog: dialog.accept())
        deleting.click()
        expect(
            page.get_by_role("heading", name="No links in this pool", exact=True)
        ).to_be_visible()
        expect(page.get_by_role("heading", name=across, exact=True)).to_be_visible()
        actions.click()
        expect(page.get_by_role("button", name="Delete links", exact=True)).to_have_count(0)
        page.get_by_label("Pool name").fill(f"Global-{mode}-{width}")
        page.get_by_label("Number of links").fill("21")
        page.get_by_role("button", name="Reserve links").click()
        expect(
            page.get_by_role("heading", name=f"Global-{mode}-{width}", exact=True)
        ).to_be_visible()
        page.get_by_role("link", name="All links", exact=True).click()
        expect(items).to_have_count(20)
        page.get_by_label("Link actions", exact=True).click()
        page.get_by_role("button", name="Delete links", exact=True).click()
        all_links = page.get_by_label("Select all links", exact=True)
        total = int(all_links.get_attribute("data-total"))
        assert total > 20
        all_links.check()
        expect(page.get_by_text(f"All {total} selected", exact=True)).to_be_visible()
        page.once("dialog", lambda dialog: dialog.accept())
        deleting.click()
        expect(page.get_by_role("heading", name="No links yet", exact=True)).to_be_visible()
    finally:
        with psycopg.connect(os.environ["POSTGRES_OWNER_TEST_URL"]) as connection:
            connection.execute("DELETE FROM links.pools WHERE id = ANY(%s)", (ids,))
        context.close()
