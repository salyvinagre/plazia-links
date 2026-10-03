"""A standards-shaped local issuer and expiring store for boundary tests only.

No production token validator, OAuth callback, or application authorization is mocked.
"""

import threading
import time
from dataclasses import replace
from pathlib import Path

from plazia_authlib.testing import IdentityFixture, LocalIssuer

from app.contexts.access.domain.principal import AccessUnavailableError
from app.platform.settings import IdentitySettings

ORG_A = "org_0199a112345670008000000000000001"
ORG_B = "org_0199a112345670008000000000000002"
RESOURCE = "https://links.example.test/api/v1"


class MemoryState:
    def __init__(self):
        self.values = {}
        self.available = True
        self.lock = threading.Lock()

    def _check(self):
        if not self.available:
            raise AccessUnavailableError

    async def put(self, purpose, key, value, ttl):
        self._check()
        with self.lock:
            self.values[purpose, key] = (value, time.time() + ttl)

    async def get(self, purpose, key):
        self._check()
        with self.lock:
            value, expires = self.values.get((purpose, key), (None, 0))
            return value if expires > time.time() else None

    async def take(self, purpose, key):
        self._check()
        with self.lock:
            value, expires = self.values.pop((purpose, key), (None, 0))
            return value if expires > time.time() else None

    async def remove(self, purpose, key):
        self._check()
        with self.lock:
            self.values.pop((purpose, key), None)

    async def consume_once(self, key, ttl):
        self._check()
        with self.lock:
            _, expires = self.values.get(("dpop", key), (None, 0))
            if expires > time.time():
                return False
            self.values["dpop", key] = ("1", time.time() + ttl)
            return True


class LinksIssuer(LocalIssuer):
    """Links configuration/content fixtures over the shared protocol issuer."""

    def __init__(
        self, public_base="http://127.0.0.1:8000", *, identity: IdentityFixture | None = None
    ):
        if identity is None:
            identity = IdentityFixture.from_text(
                Path(__file__).with_name("fixtures").joinpath("identity.toml").read_text()
            )
        identity = replace(
            identity,
            client=replace(identity.client, redirect_uris=(public_base + "/auth/callback",)),
        )
        super().__init__(identity, audience=RESOURCE)

    def config(self, public_base="http://127.0.0.1:8000"):
        return IdentitySettings(
            issuer=self.url,
            audience=RESOURCE,
            client_id=self.identity.client.client_id,
            client_secret=self.identity.client.client_secret,
            public_base_url=public_base,
            allow_insecure_loopback=True,
        )

    def handle_get(self, path):
        if path == "/content":
            return 200, "<html><body>Linked fixture content</body></html>", "text/html"
        return None


def bearer(issuer, **claims):
    return {
        "Authorization": "Bearer "
        + issuer.authority.issue_human_session(
            issuer.identity.user, issuer.identity.client, claim_overrides={**claims}
        )
    }
