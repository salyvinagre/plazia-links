import re
import uuid
from contextvars import ContextVar

from shared_observability.trace_context import TraceContext
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    return request_id_var.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        value = supplied if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", supplied) else uuid.uuid4().hex
        request.state.request_id = value
        request.state.trace = TraceContext.extract(dict(request.headers))
        trace_token = trace_id_var.set(request.state.trace.trace_id)
        token = request_id_var.set(value)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = value
            if hasattr(request.state, "idempotency_replayed"):
                response.headers["Idempotency-Replayed"] = (
                    "true" if request.state.idempotency_replayed else "false"
                )
            return response
        finally:
            request_id_var.reset(token)
            trace_id_var.reset(trace_token)
