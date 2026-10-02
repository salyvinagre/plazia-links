import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from sqlalchemy import select

from app.contexts.access.adapters.models import WorkspaceIdentityBinding
from tests.identity_support import ORG_A, ORG_B, RESOURCE


def bearer(issuer, **claims):
    return {"Authorization": "Bearer " + issuer.access(**claims)}


async def sign_in(client):
    start = await client.get("/login")
    assert start.status_code == 303
    async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as browser:
        authorization = await browser.get(start.headers["location"])
    callback = authorization.headers["location"]
    response = await client.get(callback)
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/links"
    return callback


@pytest.mark.asyncio
async def test_core_api_create_update_and_public_redirect(identity_client, issuer):
    client = identity_client
    response = await client.post(
        "/api/v1/links",
        headers=bearer(issuer),
        json={
            "destination_url": "https://example.com/first#section",
            "short_code": "coreflow",
            "notes": "private notes",
        },
    )
    assert response.status_code == 201, response.text
    link = response.json()
    assert response.headers["location"] == f"/api/v1/links/{link['id']}"
    assert link["destination_url"].endswith("#section")
    updated = await client.patch(
        f"/api/v1/links/{link['id']}",
        headers=bearer(issuer),
        json={"destination_url": "https://example.com/updated"},
    )
    assert updated.status_code == 200
    public = await client.get("/coreflow")
    assert public.status_code == 307
    assert public.headers["location"] == "https://example.com/updated"
    assert public.headers["cache-control"] == "no-store"
    await client.patch(
        f"/api/v1/links/{link['id']}", headers=bearer(issuer), json={"is_active": False}
    )
    assert (await client.get("/coreflow")).status_code != 307


@pytest.mark.asyncio
async def test_cross_tenant_reads_mutations_and_enumeration_are_denied(identity_client, issuer):
    client = identity_client
    response = await client.post(
        "/api/v1/links",
        headers=bearer(issuer, org=ORG_A),
        json={"destination_url": "https://example.com/a"},
    )
    link_id = response.json()["id"]
    other = bearer(issuer, org=ORG_B)
    assert (await client.get("/api/v1/links", headers=other)).json()["items"] == []
    for method in ("GET", "PATCH", "DELETE"):
        args = {"json": {"notes": "tamper"}} if method == "PATCH" else {}
        denied = await client.request(method, f"/api/v1/links/{link_id}", headers=other, **args)
        assert denied.status_code == 404
    forbidden_selector = await client.post(
        "/api/v1/links",
        headers=bearer(issuer),
        json={"workspace_id": "caller-chosen", "destination_url": "https://example.com/a"},
    )
    assert forbidden_selector.status_code == 422


@pytest.mark.asyncio
async def test_scopes_and_binding_are_both_required(identity_client, identity_db, issuer):
    assert (
        await identity_client.post(
            "/api/v1/links",
            headers=bearer(issuer, scopes="read:links"),
            json={"destination_url": "https://example.com"},
        )
    ).status_code == 403
    binding = await identity_db.scalar(
        select(WorkspaceIdentityBinding).where(WorkspaceIdentityBinding.organization_id == ORG_A)
    )
    binding.is_active = False
    await identity_db.commit()
    assert (await identity_client.get("/api/v1/links", headers=bearer(issuer))).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "https://another.example/api"},
        {"iss": "https://foreign.example"},
        {"exp": 10},
        {"org": "arbitrary-org"},
        {"org": None},
        {"jti": None},
        {"client_id": None},
        {"scope": ["read:links"]},
        {"cnf": {"x5t#S256": "unsupported"}},
    ],
)
async def test_invalid_access_claims_fail_closed(identity_client, issuer, claims):
    response = await identity_client.get("/api/v1/links", headers=bearer(issuer, **claims))
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_id_tokens_local_credentials_and_duplicate_headers_are_not_api_access(
    identity_client, issuer
):
    claims = jwt.decode(issuer.access(), options={"verify_signature": False})
    identity = jwt.encode(
        claims, issuer.key, algorithm="RS256", headers={"kid": issuer.kid, "typ": "JWT"}
    )
    for token in (identity, "uf_old_api_key", "opaque-token"):
        assert (
            await identity_client.get("/api/v1/links", headers={"Authorization": "Bearer " + token})
        ).status_code == 401
    response = await identity_client.get(
        "/api/v1/links",
        headers=[
            ("Authorization", "Bearer " + issuer.access()),
            ("Authorization", "Bearer " + issuer.access()),
        ],
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_dpop_machine_token_and_shared_replay_protection(identity_client, issuer):
    key, thumbprint = issuer.proof_key()
    token = issuer.access(client_id="m2m-fixture", sub="app_machine", cnf={"jkt": thumbprint})
    uri = str(identity_client.base_url).rstrip("/") + "/api/v1/links"
    proof = issuer.proof(token, key, "POST", uri)
    headers = {"Authorization": "DPoP " + token, "DPoP": proof}
    response = await identity_client.post(
        "/api/v1/links", headers=headers, json={"destination_url": "https://example.com/machine"}
    )
    assert response.status_code == 201, response.text
    replay = await identity_client.post(
        "/api/v1/links", headers=headers, json={"destination_url": "https://example.com/replay"}
    )
    assert replay.status_code == 401
    assert replay.headers["www-authenticate"].startswith("DPoP")
    assert (
        await identity_client.get("/api/v1/links", headers={"Authorization": "Bearer " + token})
    ).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override",
    [
        {"htm": "DELETE"},
        {"htu": "https://foreign.example/api/v1/links"},
        {"ath": "wrong-hash"},
        {"iat": 10},
    ],
)
async def test_dpop_request_bindings_are_checked(identity_client, issuer, override):
    key, thumbprint = issuer.proof_key()
    token = issuer.access(cnf={"jkt": thumbprint})
    uri = str(identity_client.base_url).rstrip("/") + "/api/v1/links"
    response = await identity_client.get(
        "/api/v1/links",
        headers={
            "Authorization": "DPoP " + token,
            "DPoP": issuer.proof(token, key, "GET", uri, **override),
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_dpop_store_outage_and_concurrent_replay(identity_client, issuer, ephemeral):
    key, jkt = issuer.proof_key()
    token = issuer.access(cnf={"jkt": jkt})
    uri = str(identity_client.base_url).rstrip("/") + "/api/v1/links"
    proof = issuer.proof(token, key, "GET", uri)
    ephemeral.available = False
    response = await identity_client.get(
        "/api/v1/links", headers={"Authorization": "DPoP " + token, "DPoP": proof}
    )
    assert response.status_code == 503
    ephemeral.available = True
    from app.contexts.access.adapters.dpop import DPoPVerifier
    from app.contexts.access.domain.principal import InvalidCredentialsError

    results = await asyncio.gather(
        *[DPoPVerifier(ephemeral).verify(proof, token, jkt, "GET", uri) for _ in range(6)],
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, InvalidCredentialsError) for result in results) == 5


@pytest.mark.asyncio
async def test_cookie_session_does_not_authorize_api_and_logout_revokes(
    identity_client, issuer, ephemeral
):
    client = identity_client
    callback = await sign_in(client)
    cookie = client.cookies.get("plazia_links_session")
    assert cookie and "." not in cookie
    dashboard = await client.get("/dashboard/links")
    assert dashboard.status_code == 200
    assert dashboard.headers["referrer-policy"] == "same-origin"
    assert issuer.access() not in dashboard.text
    assert (await client.get("/api/v1/links")).status_code == 401
    assert (await client.get(callback)).status_code == 400
    # State is stored as verified facts, not access or refresh token strings.
    raw = await ephemeral.get("session", cookie)
    state = json.loads(raw)
    csrf = state["csrf_token"]
    assert "access_token" not in state and "refresh_token" not in state
    for invalid in ("invalid", "invalid-☃"):
        assert (await client.post("/logout", data={"csrf_token": invalid})).status_code == 403
    assert (await client.post("/logout", data={"csrf_token": csrf})).status_code == 303
    client.cookies.set("plazia_links_session", cookie)
    assert (await client.get("/dashboard/links")).headers["location"] == "/login"


@pytest.mark.asyncio
async def test_browser_forms_share_core_commands_and_escape_html(
    identity_client, issuer, ephemeral
):
    client = identity_client
    await sign_in(client)
    state = json.loads(await ephemeral.get("session", client.cookies.get("plazia_links_session")))
    csrf = state["csrf_token"]
    data = {
        "destination_url": "https://example.com/browser",
        "title": "<script>alert(1)</script>",
        "short_code": "browser",
        "csrf_token": csrf,
    }
    assert (
        await client.post("/dashboard/links", data={**data, "csrf_token": "bad"})
    ).status_code == 403
    assert (
        await client.post("/dashboard/links", data=data, headers={"Origin": "https://evil.example"})
    ).status_code == 403
    response = await client.post("/dashboard/links", data=data)
    assert response.status_code == 303, response.text
    listing = await client.get("/dashboard/links")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in listing.text
    assert "<script>alert(1)</script>" not in listing.text
    link = (await client.get("/api/v1/links", headers=bearer(issuer))).json()["items"][0]
    edited = await client.post(
        f"/dashboard/links/{link['id']}",
        data={
            "destination_url": "https://example.com/new",
            "title": "Edited",
            "notes": "n",
            "is_active": "on",
            "csrf_token": csrf,
        },
    )
    assert edited.status_code == 303
    assert (await client.get("/browser")).headers["location"] == "https://example.com/new"


@pytest.mark.asyncio
async def test_callback_nonce_and_browser_binding(identity_client, issuer):
    start = await identity_client.get("/login")
    query = parse_qs(urlsplit(start.headers["location"]).query)
    assert query["resource"] == [RESOURCE]
    assert query["code_challenge_method"] == ["S256"]
    issuer.bad_nonce = True
    async with httpx.AsyncClient(trust_env=False) as browser:
        auth = await browser.get(start.headers["location"])
    assert (await identity_client.get(auth.headers["location"])).status_code == 400
    assert identity_client.cookies.get("plazia_links_session") is None
    assert (
        await identity_client.get("/auth/callback?code=unsolicited&state=" + "x" * 43)
    ).status_code == 400


@pytest.mark.asyncio
async def test_legacy_and_unsafe_surfaces_are_unmounted(identity_client, issuer):
    paths = [
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/api-keys",
        "/api/v1/workspaces/test/domains",
        "/api/v1/links/test/health",
        "/api/v1/workspaces/test/webhooks",
    ]
    for path in paths:
        assert (await identity_client.post(path, headers=bearer(issuer), json={})).status_code in {
            404,
            405,
        }
    assert (await identity_client.get("/dashboard/email")).status_code == 404


@pytest.mark.asyncio
async def test_code_conflict_is_409_and_does_not_break_following_requests(identity_client, issuer):
    for expected in (201, 409):
        response = await identity_client.post(
            "/api/v1/links",
            headers=bearer(issuer),
            json={"destination_url": "https://example.com", "short_code": "collision"},
        )
        assert response.status_code == expected
    assert (await identity_client.get("/api/v1/links", headers=bearer(issuer))).json()["total"] == 1


@pytest.mark.asyncio
async def test_wrong_signature_and_private_dpop_key_are_rejected(identity_client, issuer):
    from cryptography.hazmat.primitives.asymmetric import rsa

    claims = jwt.decode(issuer.access(), options={"verify_signature": False})
    foreign_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        claims, foreign_key, algorithm="RS256", headers={"kid": issuer.kid, "typ": "at+jwt"}
    )
    assert (
        await identity_client.get("/api/v1/links", headers={"Authorization": "Bearer " + forged})
    ).status_code == 401
    key, jkt = issuer.proof_key()
    token = issuer.access(cnf={"jkt": jkt})
    uri = str(identity_client.base_url).rstrip("/") + "/api/v1/links"
    proof = issuer.proof(token, key, "GET", uri)
    payload = jwt.decode(proof, options={"verify_signature": False})
    private_jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key))
    unsafe = jwt.encode(
        payload, key, algorithm="ES256", headers={"typ": "dpop+jwt", "jwk": private_jwk}
    )
    assert (
        await identity_client.get(
            "/api/v1/links", headers={"Authorization": "DPoP " + token, "DPoP": unsafe}
        )
    ).status_code == 401
    assert (
        await identity_client.get(
            "/api/v1/links",
            headers=[("Authorization", "DPoP " + token), ("DPoP", proof), ("DPoP", proof)],
        )
    ).status_code == 401


@pytest.mark.asyncio
async def test_authentication_unavailability_never_enables_local_login(identity_client, ephemeral):
    ephemeral.available = False
    assert (await identity_client.get("/login")).status_code == 503
    assert (
        await identity_client.post(
            "/api/v1/auth/login", json={"email": "test@example.com", "password": "test"}
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_oauth_code_cannot_be_completed_in_another_browser(identity_client, issuer):
    start = await identity_client.get("/login")
    async with httpx.AsyncClient(trust_env=False) as browser:
        authorization = await browser.get(start.headers["location"])
    location = authorization.headers["location"]
    original_cookies = identity_client.cookies
    identity_client.cookies = httpx.Cookies()
    assert (await identity_client.get(location)).status_code == 400
    identity_client.cookies = original_cookies
    assert (await identity_client.get(location)).status_code == 303


@pytest.mark.asyncio
async def test_session_expiration_and_tenant_disable_take_effect(
    identity_client, identity_db, ephemeral
):
    client = identity_client
    await sign_in(client)
    cookie = client.cookies.get("plazia_links_session")
    raw = json.loads(await ephemeral.get("session", cookie))
    raw["expires_at"] = 1
    await ephemeral.put("session", cookie, json.dumps(raw), 300)
    assert (await client.get("/dashboard/links")).status_code == 303
    assert await ephemeral.get("session", cookie) is None
    await sign_in(client)
    binding = await identity_db.scalar(
        select(WorkspaceIdentityBinding).where(WorkspaceIdentityBinding.organization_id == ORG_A)
    )
    binding.is_active = False
    await identity_db.commit()
    assert (await client.get("/dashboard/links")).status_code == 403


@pytest.mark.asyncio
async def test_operator_binding_is_idempotent_and_never_retargets(identity_db, issuer):
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.platform.access import workspace_provisioning

    provisioning = workspace_provisioning(identity_db, issuer.url)
    first = await provisioning.bind(ORG_A, "First")
    assert await provisioning.bind(ORG_A, "Same tenant") == first
    second = await provisioning.bind(ORG_B, "Second")
    with pytest.raises(ValueError):
        await provisioning.bind(ORG_A, "Retarget", second)
    assert (await identity_db.get(Workspace, first)).owner_id is None
    assert (await identity_db.scalars(select(User))).all() == []
    await provisioning.disable(ORG_A)
    assert (await identity_db.get(WorkspaceIdentityBinding, first)).is_active is False


@pytest.mark.asyncio
async def test_openapi_documents_scopes_without_tenant_selectors(identity_client):
    schema = (await identity_client.get("/openapi.json")).json()
    scopes = {"get": "read:links", "post": "create:links"}
    for method, scope in scopes.items():
        assert schema["paths"]["/api/v1/links"][method]["security"] == [{"IdentityAccess": [scope]}]
    create = schema["components"]["schemas"]["CreateLinkRequest"]
    assert create["additionalProperties"] is False
    assert "workspace_id" not in create["properties"]
    assert "org" not in create["properties"]
    assert "/api/v1/auth/login" not in schema["paths"]


def test_identity_configuration_fails_closed():
    from app.config import IdentitySettings, Settings

    with pytest.raises(ValueError):
        IdentitySettings(
            issuer="", audience="", client_id="", client_secret=""
        ).validate_deployment(production=True)
    insecure = IdentitySettings(
        issuer="http://127.0.0.1:9000",
        audience=RESOURCE,
        client_id="client",
        client_secret="secret",
        allow_insecure_loopback=True,
    )
    insecure.validate_deployment(production=False)
    with pytest.raises(ValueError):
        insecure.validate_deployment(production=True)
    with pytest.raises(RuntimeError):
        Settings(environment="production", auth_mode="legacy").validate_runtime_profile()


def test_identity_worker_excludes_network_delivery_jobs(monkeypatch):
    import importlib

    import worker.run as worker
    from app.config import settings

    monkeypatch.setattr(settings, "auth_mode", "identity")
    try:
        worker = importlib.reload(worker)
        names = {job.__name__ for job in worker.WorkerSettings.functions}
        assert names == {"process_click", "cleanup_old_data"}
        assert len(worker.WorkerSettings.cron_jobs) == 1
    finally:
        monkeypatch.setattr(settings, "auth_mode", "legacy")
        importlib.reload(worker)


@pytest.mark.asyncio
async def test_private_destination_validation_is_a_client_error(identity_client, issuer):
    headers = bearer(issuer)
    invalid = "http://127.0.0.1/internal"
    created = await identity_client.post(
        "/api/v1/links", headers=headers, json={"destination_url": invalid}
    )
    assert created.status_code == 422
    valid = await identity_client.post(
        "/api/v1/links", headers=headers, json={"destination_url": "https://example.com/public"}
    )
    assert valid.status_code == 201
    updated = await identity_client.patch(
        f"/api/v1/links/{valid.json()['id']}",
        headers=headers,
        json={"destination_url": invalid},
    )
    assert updated.status_code == 422
    retained = await identity_client.get(f"/api/v1/links/{valid.json()['id']}", headers=headers)
    assert retained.json()["destination_url"] == "https://example.com/public"
