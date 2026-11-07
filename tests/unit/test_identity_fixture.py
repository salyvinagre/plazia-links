"""Product fixtures reach the same authentication boundary as deployed tokens."""

from pathlib import Path

import pytest
from plazia_authlib.testing import IdentityFixture

from app.contexts.access.adapters.identity_tokens import IdentityTokenVerifier
from app.contexts.access.domain.principal import InvalidCredentialsError
from app.platform.access import AccessRuntime
from tests.identity_support import ORG_A, ORG_B, LinksIssuer, MemoryState, bearer


@pytest.mark.parametrize("custom", [False, True])
async def test_fixture_claims_reach_production_authentication(custom):
    text = Path(__file__).parents[1].joinpath("fixtures/identity.toml").read_text()
    if custom:
        text = text.replace("links-browser", "custom-browser").replace(ORG_A, ORG_B)
        text = text.replace(', "links:create", "links:update", "links:delete"', "")
        text = text.replace(
            "usr_0199a112345670008000000000000003", "usr_0199a112345670008000000000000009"
        )
    fixture = IdentityFixture.from_text(text)
    public_base = "http://127.0.0.1:8765"
    with LinksIssuer(public_base=public_base, identity=fixture if custom else None) as issuer:
        assert issuer.identity.client.redirect_uris == (public_base + "/auth/callback",)
        assert issuer.config(public_base).redirect_uri == public_base + "/auth/callback"
        verifier = IdentityTokenVerifier(issuer.url, issuer.audience)
        try:
            principal = await verifier.access_token(bearer(issuer)["Authorization"][7:])
            assert principal.issuer == issuer.url
            assert principal.client_id == fixture.client.client_id
            assert principal.subject == fixture.user.id
            assert str(principal.organization_id) == fixture.user.organization_id
            assert principal.scopes == frozenset(fixture.user.scopes)
        finally:
            await verifier.close()


@pytest.mark.parametrize("trailing_slash", [False, True])
async def test_machine_issuer_preserves_browser_authority_and_verified_tenant(trailing_slash):
    with LinksIssuer() as browser, LinksIssuer() as machine, LinksIssuer() as unknown:
        suffix = "/" if trailing_slash else ""
        config = type(browser.config())(
            **{
                **browser.config().model_dump(),
                "issuer": browser.url + suffix,
                "machine_issuers": (machine.url + suffix,),
            }
        )
        runtime = AccessRuntime.build(config, MemoryState())
        try:
            principal = await runtime.tokens.access_token(
                machine.authority.issue_machine_credential(
                    machine.identity.machine, machine.identity.client
                )
            )
            assert principal.issuer == machine.url
            assert principal.subject == machine.identity.machine.id
            assert str(principal.organization_id) == ORG_A
            human = await runtime.tokens.access_token(bearer(browser)["Authorization"][7:])
            assert human.issuer == browser.url
            assert config.authorization_endpoint == browser.url + "/oauth2/auth"
            for token in (
                bearer(machine)["Authorization"][7:],
                unknown.authority.issue_machine_credential(
                    unknown.identity.machine, unknown.identity.client
                ),
                machine.authority.issue_machine_credential(
                    machine.identity.machine,
                    machine.identity.client,
                    audience="https://printer.example/api/v1",
                ),
                machine.authority.issue_machine_credential(
                    machine.identity.machine,
                    machine.identity.client,
                    claim_overrides={"iss": browser.url},
                ),
            ):
                with pytest.raises(InvalidCredentialsError):
                    await runtime.tokens.access_token(token)
        finally:
            await runtime.tokens.close()


@pytest.mark.parametrize(
    "machine",
    ["http://remote.example", "https://user@remote.example", "https://remote.example/path"],
)
def test_machine_discovery_requires_an_admitted_origin(issuer, machine):
    config = issuer.config().model_copy(update={"machine_issuers": (machine,)})
    with pytest.raises(ValueError):
        config.validate_deployment(production=False)
