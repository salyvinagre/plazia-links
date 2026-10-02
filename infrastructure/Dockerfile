FROM ghcr.io/astral-sh/uv:0.12.21@sha256:39902c0d33692379d73d4974f7be2f7b1d26d70bdb6d0315e90602b22e1d97fc AS uv
FROM public.ecr.aws/docker/library/python:3.14-slim@sha256:0741d101873c12ab927e6f8653feb8862b9bd58771177acb1b885b95141f91b4 AS builder
COPY --from=uv /uv /bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1
WORKDIR /plazia-links
COPY plazia/packages /plazia/packages
COPY plazia-links/pyproject.toml plazia-links/uv.lock ./
COPY plazia-links/app ./app
COPY plazia-links/worker ./worker
RUN uv sync --locked --no-dev --no-editable

FROM public.ecr.aws/docker/library/python:3.14-slim@sha256:0741d101873c12ab927e6f8653feb8862b9bd58771177acb1b885b95141f91b4
WORKDIR /app
RUN useradd --uid 10001 --create-home app
COPY --from=builder --chown=app:app /plazia-links/.venv /plazia-links/.venv
COPY --from=builder --chown=app:app /plazia-links/app /app/app
COPY --from=builder --chown=app:app /plazia-links/worker /app/worker
ENV PATH="/plazia-links/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
