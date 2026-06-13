"""Centralised logging configuration.

Replaces the one-off `logging.basicConfig(...)` at the top of main.py with a
single setup function that:

  * always emits structured `extra={...}` fields alongside every record,
  * optionally switches to JSON output (for production / cron / Sentry),
  * uses a console-friendly format in interactive mode.

Every other module already uses the standard library `logging` module, so
adopting this is a one-line change in main.py.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


class _JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON with all `extra` fields."""

    # Standard LogRecord attributes that we never want to emit under "extra".
    _RESERVED = {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(
    level: int = logging.INFO,
    log_file: str | None = "data/lead_bot.log",
    json_output: bool | None = None,
) -> None:
    """Configure root logger. Idempotent — safe to call multiple times."""
    if json_output is None:
        json_output = os.getenv("LOG_JSON", "false").lower() in ("1", "true", "yes")

    root = logging.getLogger()
    root.setLevel(level)
    # Remove handlers we previously installed to avoid duplicate lines
    # when this is called twice (interactive + cron).
    for h in list(root.handlers):
        root.removeHandler(h)

    if json_output:
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    if log_file:
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError:
            # If the log file can't be opened (read-only filesystem, etc.)
            # we still want the rest of the app to run.
            pass
