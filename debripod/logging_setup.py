from __future__ import annotations

import json
import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


_CREDENTIAL_URL = re.compile(r"(https?://[^\s/:@]+:)[^@\s]+@", re.IGNORECASE)
_AUTHORIZATION = re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[^\s,;]+")
_SECRET_VALUE = re.compile(r"(?i)\b(authorization|bearer|token|csrf|cookie|password|secret)\s*[:=]?\s*[^\s,;]+")


def redact_text(value: object) -> str:
    text = str(value or "")
    text = _CREDENTIAL_URL.sub(r"\1[redacted]@", text)
    text = _AUTHORIZATION.sub("Authorization: Bearer [redacted]", text)
    return _SECRET_VALUE.sub(lambda match: match.group(1) + "=[redacted]", text)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class _TerminalAccessHandler(logging.StreamHandler):
    """Dedicated terminal output for local API and media requests."""


def configure_logging(directory: str | Path) -> Path:
    root = logging.getLogger()
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "debripod.log"
    has_file_handler = any(
        isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == target
        for handler in root.handlers
    )
    if not has_file_handler:
        handler = RotatingFileHandler(target, maxBytes=2 * 1024 * 1024, backupCount=4, encoding="utf-8")
        handler.setFormatter(_JsonFormatter())
        root.addHandler(handler)
    root.setLevel(logging.INFO)

    access_logger = logging.getLogger("debripod.access")
    if not any(isinstance(handler, _TerminalAccessHandler) for handler in access_logger.handlers):
        terminal = _TerminalAccessHandler(sys.stdout)
        terminal.setFormatter(logging.Formatter("%(message)s"))
        access_logger.addHandler(terminal)
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False
    return target
