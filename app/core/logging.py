"""Cau hinh logging tap trung."""
from __future__ import annotations

import logging
import sys

from app.core.config import settings


def setup_logging(level: str | None = None) -> None:
    """Cau hinh handler cho stdout, dinh dang ngan gon."""
    log_level = (level or settings.log_level).upper()
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(log_level)
    logging.getLogger("neo4j").setLevel("WARNING")
    logging.getLogger("httpx").setLevel("WARNING")
    logging.getLogger("urllib3").setLevel("WARNING")
