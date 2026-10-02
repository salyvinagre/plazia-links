"""Read-only serverless build preflight. Never connect, migrate or provision at build time."""

import sys
from pathlib import Path

from app.config import IdentitySettings, Settings
from app.core.schema import expected_schema_heads


class ServerlessPreflight:
    @staticmethod
    def check(config: Settings, identity: IdentitySettings) -> None:
        if sys.version_info[:2] != (3, 14):
            raise RuntimeError("The serverless runtime must select Python 3.14")
        if config.deployment_mode != "serverless":
            raise RuntimeError("Set DEPLOYMENT_MODE=serverless for the function deployment")
        if config.environment.lower() not in {"production", "prod"}:
            raise RuntimeError("Use production security settings even for a Vercel preview")
        config.validate_runtime_profile()
        identity.validate_deployment(production=True)
        if not config.redis_url.startswith("rediss://"):
            raise RuntimeError("The serverless Redis connection must use TLS (rediss://)")
        root = Path(__file__).resolve().parents[2]
        for asset in (
            "app/templates/identity/links.html",
            "app/static/css/identity.css",
            "uv.lock",
        ):
            if not (root / asset).is_file():
                raise RuntimeError(f"Missing serverless bundle input: {asset}")
        expected_schema_heads()


if __name__ == "__main__":
    ServerlessPreflight.check(Settings(), IdentitySettings())
    print("Serverless configuration and bundle inputs verified; database was not modified.")
