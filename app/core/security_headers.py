from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    ("Content-Security-Policy"): (
        "default-src 'self'; script-src 'self' https://unpkg.com "
        "https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' "
        "https://fonts.googleapis.com; font-src 'self' "
        "https://fonts.gstatic.com; img-src 'self' data: https:; "
        "connect-src 'self'"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response: Response = await call_next(request)
        for name, value in HEADERS.items():
            response.headers[name] = value
        if getattr(request.app.state, "auth_mode", "legacy") == "identity":
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            # Native same-origin form POSTs must retain a non-null Origin for CSRF.
            # Authorization callbacks must never leak their code/state in a referrer.
            response.headers["Referrer-Policy"] = (
                "same-origin" if request.url.path.startswith("/dashboard") else "no-referrer"
            )
            if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
                response.headers["Content-Security-Policy"] = (
                    "default-src 'self'; script-src 'none'; style-src 'self'; "
                    "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; "
                    "form-action 'self'; object-src 'none'"
                )
        return response
