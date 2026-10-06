"""
Structured logs: one JSON object per line, with the request and turn attached.

    {"ts": "...", "level": "INFO", "logger": "app.http", "msg": "POST /api/sessions/{id}/messages 202",
     "request_id": "3f2a…", "thread_id": "…", "turn_id": "t3", "duration_ms": 41}

Two ContextVars do the attaching, so call sites stay plain `logger.info(...)`:
  - request_id: set by the HTTP middleware (main.py) for each request
  - the turn:   set by runner.turn() (progress.py) for agent work

Secrets never reach the output: tokens in URLs and Authorization headers are
masked by redact() before a line is written.
"""
import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# access_token=…  /  Bearer …  /  any bare JWT (three base64url parts, header starts with eyJ)
_SECRETS = [
    (re.compile(r"(access_token=)[^&\s\"']+"), r"\1[REDACTED]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*"), "[REDACTED_JWT]"),
]


def redact(text: str) -> str:
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


class JsonFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }

        request_id = request_id_var.get()
        if request_id:
            entry["request_id"] = request_id

        # imported here: progress imports the API layer, which imports this module
        from app.api.progress import current_turn
        turn = current_turn()
        if turn is not None:
            entry["thread_id"] = turn.thread_id
            entry["turn_id"] = turn.turn_id

        # logger.info("...", extra={"fields": {...}}) adds structured fields
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry.update(fields)

        if record.exc_info:
            entry["exc"] = redact(self.formatException(record.exc_info))

        return json.dumps(entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn's own handlers would print a second, plain-text copy
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    # the middleware writes the access log (without query strings), so silence uvicorn's
    logging.getLogger("uvicorn.access").disabled = True

    # one line per outbound HTTP call is noise next to our own timed tool / LLM lines
    for name in ("httpx", "httpx2", "httpcore", "openai"):
        logging.getLogger(name).setLevel(max(logging.WARNING, root.level))


def log_fields(logger: logging.Logger, msg: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, msg, extra={"fields": fields})
