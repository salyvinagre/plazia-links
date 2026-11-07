import re

import pytest

from app.contexts.links.domain.link import (
    Entropy,
    InvalidLinkError,
    LinkPolicy,
    PublicCode,
    Visibility,
)


@pytest.mark.parametrize(
    "level,length", [(Entropy.low, 8), (Entropy.medium, 20), (Entropy.high, 32)]
)
def test_generated_profile_has_exact_base64url_entropy(level, length):
    codes = {PublicCode.generate(level) for _ in range(100)}
    assert len(codes) == 100
    assert all(len(code) == length and re.fullmatch(r"[A-Za-z0-9_-]+", code) for code in codes)


def test_private_client_policy_defaults_private_and_rejects_downgrade():
    assert LinkPolicy.select(None, None, private_required=True) == LinkPolicy(
        Entropy.high, Visibility.client_private
    )
    assert LinkPolicy.select(None, None, private_required=False) == LinkPolicy(
        Entropy.low, Visibility.organization
    )
    for level in (Entropy.low, Entropy.medium):
        with pytest.raises(InvalidLinkError):
            LinkPolicy.select(level, Visibility.client_private, private_required=False)
    with pytest.raises(InvalidLinkError):
        LinkPolicy.select(Entropy.high, Visibility.organization, private_required=True)


async def test_api_accepts_only_client_private_visibility(identity_client, issuer):
    from tests.identity_support import bearer

    for visibility, status in (("workload_private", 422), ("client_private", 201)):
        response = await identity_client.post(
            "/api/v1/pools",
            headers=bearer(issuer),
            json={"size": 1, "entropy": "high", "visibility": visibility},
        )
        assert response.status_code == status
        if status == 201:
            assert response.json()["visibility"] == "client_private"
