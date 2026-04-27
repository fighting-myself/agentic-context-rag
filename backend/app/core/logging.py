import logging
import os
import uuid
from logging.handlers import RotatingFileHandler

from pythonjsonlogger.json import JsonFormatter

from app.core.config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.log_path), exist_ok=True)

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers.clear()

    formatter = JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(trace_id)s"
    )
    file_handler = RotatingFileHandler(
        settings.log_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console)


def new_trace_id() -> str:
    return uuid.uuid4().hex
