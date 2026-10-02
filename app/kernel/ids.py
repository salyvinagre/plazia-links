"""Links-owned identifiers; tenant identifiers belong to shared_identity."""

from shared_kernel import CanonicalId, CanonicalIds


class LinkId(CanonicalId):
    _prefix = "lnk"


class PoolId(CanonicalId):
    _prefix = "lpl"


class SubscriptionId(CanonicalId):
    _prefix = "lsb"


CanonicalIds.register_many((LinkId, PoolId, SubscriptionId))
