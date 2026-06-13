"""
Centralized logging configuration for SNO.
Call setup_logging() once at startup (src/main.py) to configure the root logger.
All other modules use: logger = logging.getLogger(__name__)
"""
import logging
import sys
from src.config import settings


def setup_logging() -> None:
    """Configure the root logger for the entire SNO application."""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers if called more than once (e.g., Streamlit hot-reload)
    if not root.handlers:
        root.addHandler(handler)

    # Suppress noisy third-party loggers
    for noisy in ("httpx", "httpcore", "neo4j", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
