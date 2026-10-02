"""Check the Identity-owned organization graph through the official OpenFGA SDK."""

from typing import Any, cast

from openfga_sdk import ClientConfiguration
from openfga_sdk.client import OpenFgaClient
from openfga_sdk.client.models import ClientCheckRequest
from shared_authz import AuthzSubjectRef

from app.contexts.access.application.authorization import AuthorizationAttempt
from app.contexts.access.domain.principal import AccessDeniedError, AccessUnavailableError


class OpenFgaOrganizationAuthority:
    def __init__(self, url: str, store_id: str, model_id: str) -> None:
        if not url or not store_id or not model_id:
            raise ValueError("An OpenFGA endpoint, store and immutable model id are required")
        self._client = OpenFgaClient(
            ClientConfiguration(api_url=url, store_id=store_id, authorization_model_id=model_id)
        )

    async def require(self, attempt: AuthorizationAttempt) -> None:
        actor = attempt.actor
        actor.require(attempt.permission)
        try:
            subject = (
                AuthzSubjectRef.machine(actor.subject)
                if actor.subject.startswith("mch_")
                else AuthzSubjectRef.user(actor.subject)
            )
            response = await self._client.check(
                ClientCheckRequest(
                    user=f"{subject.kind.value}:{subject.id}",
                    relation="reader" if attempt.permission == "links:read" else "manager",
                    object=f"organization:{actor.organization_id}",
                ),
                {"consistency": "HIGHER_CONSISTENCY"},
            )
        except Exception as exc:
            raise AccessUnavailableError from exc
        if response.allowed is not True:
            raise AccessDeniedError("organization_authority")

    async def close(self) -> None:
        await cast(Any, self._client).close()
