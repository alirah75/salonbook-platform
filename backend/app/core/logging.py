"""Structured allowlisted logs: no headers, query strings, bodies or exception messages."""

import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", "log.record")
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": event,
        }
        request_id = request_id_context.get()
        if request_id:
            payload["request_id"] = request_id
        for key in ("method", "route", "status_code", "duration_ms", "error_code", "error_type"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info and record.exc_info[0]:
            payload["error_type"] = record.exc_info[0].__name__
            payload["stack"] = [
                {"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Configure only owned/server loggers; never enable SQL or raw URL access logs."""
    for name in ("salonbook", "uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    logging.getLogger("uvicorn.access").disabled = True


logger = logging.getLogger("salonbook")
