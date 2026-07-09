"""JSON log formatter — structured logging for production.

Usage in main.py:
    from app.logging import setup_json_logging
    setup_json_logging(level=logging.WARNING)

When LOG_FORMAT=json, all log records are emitted as JSON objects:
    {"ts": "2026-07-08T12:34:56Z", "level": "ERROR", "logger": "app.api", "msg": "..."}
"""
import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

# Set by app.main's request middleware for the duration of one request, so
# any log line emitted while handling it can be tied back to that request —
# without this there was no way to correlate a user's bug report to specific
# log lines beyond grepping timestamps.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class JsonFormatter(logging.Formatter):
    """Format log records as JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info and record.exc_info[1]:
            payload["exc"] = str(record.exc_info[1])
        return json.dumps(payload, default=str, ensure_ascii=False)


def setup_json_logging(level: int = logging.INFO) -> None:
    """Configure root logger to emit JSON to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.setLevel(level)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)
