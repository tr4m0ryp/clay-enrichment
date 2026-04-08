import logging
import os
from logging.handlers import TimedRotatingFileHandler

_LOG_DIR = "logs"
_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_setup_done = False


def setup_logging() -> None:
    global _setup_done
    if _setup_done:
        return

    os.makedirs(_LOG_DIR, exist_ok=True)

    formatter = logging.Formatter(_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    log_file = os.path.join(_LOG_DIR, "app.log")
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    _setup_done = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
