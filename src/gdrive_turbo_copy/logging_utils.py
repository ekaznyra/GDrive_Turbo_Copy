"""Lightweight structured logging helpers (stdlib only, no extra deps)."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

LOGGER_NAME = "gdrive_turbo_copy"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload["fields"] = fields
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str | int = "INFO", *, json_format: bool = False) -> logging.Logger:
    """Configure and return the package root logger.

    Safe to call multiple times; handlers are only attached once.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        if json_format:
            handler.setFormatter(_JsonFormatter())
        else:
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
            )
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    if not name:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def _fmt_value(value: Any) -> str:
    text = str(value)
    if any(ch in text for ch in (" ", "=", '"')):
        return json.dumps(text, ensure_ascii=False)
    return text


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Emit a structured ``event key=value ...`` log line.

    The raw fields are also attached to the record under ``fields`` so a JSON
    formatter can serialize them.
    """
    rendered = " ".join(f"{key}={_fmt_value(val)}" for key, val in fields.items())
    logger.log(level, "%s %s", event, rendered, extra={"fields": dict(fields)})
