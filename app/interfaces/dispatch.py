"""Transport mapping into the shared runtime dispatch boundaries."""

from typing import Any, cast

from fastapi import HTTPException, Request
from shared_kernel import RequestContext
from shared_messaging import CommandBus, QueryBus
from shared_observability.trace_context import TraceContext

from app.contexts.access.contracts import Principal
from app.contexts.links.contracts import CommandResultDto


def request_context(
    request: Request,
    actor: Principal | None = None,
    *,
    mutation: bool = False,
    key: str | None = None,
) -> RequestContext:
    key = key or request.headers.get("Idempotency-Key")
    if mutation and (
        not key
        or not key.isascii()
        or not 1 <= len(key) <= 128
        or any(not (char.isalnum() or char in "-_.:") for char in key)
    ):
        raise HTTPException(400, "invalid_idempotency_key")
    trace = getattr(request.state, "trace", None) or TraceContext.extract(dict(request.headers))
    return RequestContext.for_actor(
        actor_id=actor.subject if actor else "visitor",
        actor_type="principal" if actor else "anonymous",
        request_id=request.state.request_id,
        correlation_id=request.headers.get("X-Correlation-ID", "")[:128] or None,
        source_channel="http",
        traceparent=trace.traceparent,
        tracestate=trace.tracestate,
        idempotency_key=key,
    )


def commands(request: Request) -> CommandBus:
    return cast(CommandBus, request.app.state.commands)


def queries(request: Request) -> QueryBus:
    return cast(QueryBus, request.app.state.queries)


async def mutate(
    request: Request, command: object, actor: Principal, *, key: str | None = None
) -> Any:
    result = await commands(request).dispatch(
        command, context=request_context(request, actor, mutation=True, key=key)
    )
    if not isinstance(result, CommandResultDto):
        raise TypeError("Mutation result must provide replay evidence")
    request.state.idempotency_replayed = result.replayed
    return result.value
