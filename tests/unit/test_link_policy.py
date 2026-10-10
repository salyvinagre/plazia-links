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


def test_workload_policy_defaults_private_and_rejects_downgrade():
    assert LinkPolicy.select(None, None, workload=True) == LinkPolicy(
        Entropy.high, Visibility.workload_private
    )
    assert LinkPolicy.select(None, None, workload=False) == LinkPolicy(
        Entropy.low, Visibility.organization
    )
    for level in (Entropy.low, Entropy.medium):
        with pytest.raises(InvalidLinkError):
            LinkPolicy.select(level, Visibility.workload_private, workload=False)
    with pytest.raises(InvalidLinkError):
        LinkPolicy.select(Entropy.high, Visibility.organization, workload=True)
