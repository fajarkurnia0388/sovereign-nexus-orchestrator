"""
SNO Centralized Logger — v2.0
Supports both human-readable (text) and machine-parseable (JSON) formats.
Use JSON format in production for log aggregation tools (Loki, ELK, Datadog).
"""
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class _TextFormatter(logging.Formatter):
    """Colorised text formatter for development."""
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        prefix = f"{color}[{record.levelname:8}]{self.RESET}"
        extra = ""
        if hasattr(record, "job_id"):
            extra = f" [job={record.job_id}]"
        if hasattr(record, "playbook"):
            extra += f" [pb={record.playbook}]"
        return f"{ts} {prefix} {record.name}{extra}: {record.getMessage()}"


class _JsonFormatter(logging.Formatter):
    """JSON-lines formatter for production log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key in ("job_id", "playbook", "node", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    """
    Configure the SNO root logger. Call ONCE at process startup (main.py).

    Args:
        level:  Log level string (DEBUG / INFO / WARNING / ERROR).
        fmt:    'text' for colorised output, 'json' for structured log lines.
    """
    # Suppress noisy third-party loggers
    for noisy in (
        "httpx", "httpcore", "neo4j", "qdrant_client", "urllib3",
        "langgraph", "mcp", "asyncio", "uvicorn.access",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    sno_root = logging.getLogger("sno")
    if sno_root.handlers:
        return  # Already configured (avoid duplicate handlers)

    sno_root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if fmt == "json" else _TextFormatter())
    sno_root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """
    Return a child logger under the 'sno' hierarchy.

    Usage:
        logger = get_logger("core.engine")
        logger.info("Job started", extra={"job_id": "abc123", "playbook": "research"})
    """
    return logging.getLogger(f"sno.{name}")