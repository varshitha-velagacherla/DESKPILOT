import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Create logs folder
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Create logger
logger = logging.getLogger("assistant")
logger.setLevel(logging.INFO)

# Prevent duplicate handlers
if not logger.handlers:

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(filename)s:%(lineno)d | %(message)s"
    )

    # File handler
    file_handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8"
    )

    file_handler.setFormatter(formatter)

    # Console handler
    # console_handler = logging.StreamHandler()
    # console_handler.setFormatter(formatter)

    # logger.addHandler(file_handler)
    # logger.addHandler(console_handler)