"""Links capability gate and registry check on Identity-owned organizations."""

from plazia_authlib.authz.contracts import (
    AuthzAuditContext,
    AuthzCheckRequest,
    AuthzObjectRef,
    AuthzSubjectRef,
)
from plazia_authlib.authz.openfga_authorization import OpenFgaAuthorizationAdapter
from plazia_authlib.authz.registry import AuthzActionRegistry
from plazia_authlib.authz.vocabulary import (
    AUTHZ_MODEL_PACKET_ID,
    AuthzConsistency,
    AuthzDecisionValue,
    AuthzRepo,
)

from app.contexts.access.application.authorization import AuthorizationAttempt
from app.contexts.access.domain.principal import AccessDeniedError, AccessUnavailableError


class OpenFgaOrganizationAuthority:
    def __init__(self, url: str, store_id: str, model_id: str) -> None:
        if not url or not store_id or not model_id:
            raise ValueError("An OpenFGA endpoint, store and immutable model id are required")
        self._registry = AuthzActionRegistry.shared()
        self._authorization = OpenFgaAuthorizationAdapter(
            api_url=url,
            store_id=store_id,
            authorization_model_id=model_id,
            action_registry=self._registry,
        )

    async def require(self, attempt: AuthorizationAttempt) -> None:
        actor = attempt.actor
        actor.require(attempt.permission)
        if attempt.context is None:
            raise AccessUnavailableError
        operation = attempt.context.operation_context
        traceparent = operation.traceparent
        if traceparent is None:
            raise AccessUnavailableError
        identity = attempt.context.actor_context
        subject = (
            AuthzSubjectRef.machine(actor.subject)
            if actor.subject.startswith("mch_")
            else AuthzSubjectRef.user(actor.subject)
        )
        request = AuthzCheckRequest(
            subject=subject,
            object=AuthzObjectRef("organization", str(actor.organization_id), AuthzRepo.identity),
            action=self._registry.action_for(
                object_type="organization", action_name=attempt.permission.replace(":", ".")
            ),
            audit_context=AuthzAuditContext(
                request_id=operation.request_id,
                correlation_id=operation.correlation_id or operation.request_id,
                traceparent=traceparent,
                actor_id=identity.actor_id,
                actor_type=identity.actor_type,
                source_channel=operation.source_channel,
                source_repo=AuthzRepo.links,
                model_packet_id=AUTHZ_MODEL_PACKET_ID,
                idempotency_key=operation.idempotency_key,
            ),
            consistency=AuthzConsistency.higher_consistency,
        )
        decision = await self._authorization.check(request)
        if decision.decision == AuthzDecisionValue.unavailable:
            raise AccessUnavailableError
        if not decision.permits_service_attempt:
            raise AccessDeniedError("organization_authority")

    async def close(self) -> None:
        await self._authorization.close()
