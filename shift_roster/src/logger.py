"""Application-wide logger."""
import logging
import os
from src.config import config


def get_logger(name: str) -> logging.Logger:
    os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(config.LOG_LEVEL)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Console
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File
    fh = logging.FileHandler(config.LOG_FILE)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
