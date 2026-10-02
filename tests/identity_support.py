"""A standards-shaped local issuer and expiring store for boundary tests only.

No production token validator, OAuth callback, or application authorization is mocked.
"""

import base64
import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid7

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.config import IdentitySettings
from app.contexts.access.adapters.dpop import DPoPVerifier
from app.contexts.access.domain.principal import AccessUnavailableError

ORG_A = "org_0199a112-3456-7000-8000-000000000001"
ORG_B = "org_0199a112-3456-7000-8000-000000000002"
RESOURCE = "https://links.example.test/api"


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


class LocalIssuer:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "fixture-signing-key"
        self.client_id = "links-browser"
        self.client_secret = "fixture-browser-secret-not-a-real-credential"
        self.organization = ORG_A
        self.codes = {}
        self.token_requests = []
        self.bad_nonce = False
        self.jwks_requests = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def config(self, public_base="http://127.0.0.1:8000"):
        return IdentitySettings(
            issuer=self.url,
            audience=RESOURCE,
            client_id=self.client_id,
            client_secret=self.client_secret,
            public_base_url=public_base,
            allow_insecure_loopback=True,
        )

    def access(
        self, org=ORG_A, scopes="read:links create:links update:links delete:links", **overrides
    ):
        now = int(time.time())
        claims = {
            "iss": self.url,
            "aud": RESOURCE,
            "sub": "usr_fixture-alice",
            "client_id": self.client_id,
            "org": org,
            "scope": scopes,
            "iat": now,
            "exp": now + 300,
            "jti": str(uuid7()),
        }
        claims.update(overrides)
        return jwt.encode(
            claims, self.key, algorithm="RS256", headers={"kid": self.kid, "typ": "at+jwt"}
        )

    def proof(self, token, key, method, uri, **overrides):
        claims = {
            "jti": secrets.token_urlsafe(16),
            "iat": int(time.time()),
            "htm": method,
            "htu": uri,
            "ath": DPoPVerifier.digest(token.encode()),
        }
        claims.update(overrides)
        public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
        return jwt.encode(
            claims, key, algorithm="ES256", headers={"typ": "dpop+jwt", "jwk": public}
        )

    @staticmethod
    def proof_key():
        key = ec.generate_private_key(ec.SECP256R1())
        public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
        return key, DPoPVerifier.thumbprint(public)

    def _handler(self):
        issuer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body, content_type="application/json", **headers):
                payload = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                path = urlsplit(self.path)
                if path.path == "/.well-known/jwks":
                    issuer.jwks_requests += 1
                    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(issuer.key.public_key()))
                    self.reply(
                        200, {"keys": [{**public, "kid": issuer.kid, "alg": "RS256", "use": "sig"}]}
                    )
                elif path.path == "/oauth2/auth":
                    params = {k: v[0] for k, v in parse_qs(path.query).items()}
                    if (
                        params.get("client_id") != issuer.client_id
                        or params.get("resource") != RESOURCE
                        or params.get("code_challenge_method") != "S256"
                        or "nonce" not in params
                    ):
                        self.reply(400, {"error": "invalid_request"})
                        return
                    code = secrets.token_urlsafe(24)
                    issuer.codes[code] = params
                    location = (
                        params["redirect_uri"]
                        + "?"
                        + urlencode({"code": code, "state": params["state"]})
                    )
                    # Browser intentionally follows a real top-level authorization redirect.
                    self.reply(302, "", Location=location)
                elif path.path == "/content":
                    self.reply(200, "<h1>Linked content</h1>", "text/html")
                else:
                    self.reply(404, {})

            def do_POST(self):
                if self.path != "/oauth2/token":
                    self.reply(404, {})
                    return
                body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
                params = {k: v[0] for k, v in parse_qs(body).items()}
                issuer.token_requests.append(params)
                launch = issuer.codes.pop(params.get("code", ""), None)
                expected_auth = (
                    "Basic "
                    + base64.b64encode(
                        f"{issuer.client_id}:{issuer.client_secret}".encode()
                    ).decode()
                )
                challenge = DPoPVerifier.digest(params.get("code_verifier", "").encode())
                if (
                    launch is None
                    or self.headers.get("Authorization") != expected_auth
                    or params.get("grant_type") != "authorization_code"
                    or params.get("resource") != RESOURCE
                    or params.get("redirect_uri") != launch["redirect_uri"]
                    or challenge != launch["code_challenge"]
                ):
                    self.reply(400, {"error": "invalid_grant"})
                    return
                access = issuer.access(org=issuer.organization)
                now = int(time.time())
                identity = jwt.encode(
                    {
                        "iss": issuer.url,
                        "sub": "usr_fixture-alice",
                        "aud": issuer.client_id,
                        "iat": now,
                        "exp": now + 300,
                        "nonce": "wrong-nonce" if issuer.bad_nonce else launch["nonce"],
                        "at_hash": base64.urlsafe_b64encode(
                            hashlib.sha256(access.encode()).digest()[:16]
                        )
                        .rstrip(b"=")
                        .decode(),
                    },
                    issuer.key,
                    algorithm="RS256",
                    headers={"kid": issuer.kid, "typ": "JWT"},
                )
                self.reply(
                    200,
                    {
                        "access_token": access,
                        "id_token": identity,
                        "token_type": "Bearer",
                        "expires_in": 300,
                    },
                )

        return Handler
