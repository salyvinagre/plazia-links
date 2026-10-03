"""Product fixtures reach the same authentication boundary as deployed tokens."""

from pathlib import Path

import pytest
from plazia_authlib.testing import IdentityFixture

from app.contexts.access.adapters.identity_tokens import IdentityTokenVerifier
from tests.identity_support import ORG_A, ORG_B, LinksIssuer, bearer


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
