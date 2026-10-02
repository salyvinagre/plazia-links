import json
import logging
import sys
from collections.abc import MutableMapping
from datetime import UTC, datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "ts": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
                "request_id": getattr(record, "request_id", None),
                "error_type": getattr(record, "error_type", None),
                "trace_id": getattr(record, "trace_id", None),
            },
            default=str,
        )


def setup_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)


class LoggerAdapter(logging.LoggerAdapter[logging.Logger]):
    def process(
        self, msg: object, kwargs: MutableMapping[str, Any]
    ) -> tuple[object, MutableMapping[str, Any]]:
        from app.interfaces.middleware.request_id import get_request_id, trace_id_var

        rid = get_request_id()
        if rid:
            kwargs.setdefault("extra", {})["request_id"] = rid
        if trace_id_var.get():
            kwargs.setdefault("extra", {})["trace_id"] = trace_id_var.get()
        return msg, kwargs


def get_logger(name: str) -> LoggerAdapter:
    return LoggerAdapter(logging.getLogger(name), {})
