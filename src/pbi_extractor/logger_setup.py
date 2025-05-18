# src/pbi_extractor/logger_setup.py

"""Configures the application logger."""

import logging
import sys
from pathlib import Path

# TODO: Integrate with config_manager for log level and file path

def setup_logging(log_level: str = "INFO", log_file: Path | None = None) -> None:
    """Configures basic logging for the application.

    Args:
        log_level (str): The minimum logging level (e.g., 'DEBUG', 'INFO', 'WARNING').
        log_file (Path | None): Optional path to a log file. If None, logs to console.
    """
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level}")

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Configure root logger
    # logging.basicConfig(level=numeric_level, format='%(asctime)s - %(levelname)s - %(message)s')

    # Get the root logger
    logger = logging.getLogger() # Get root logger
    logger.setLevel(numeric_level)
    logger.handlers.clear() # Clear existing handlers if any (e.g., from basicConfig)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        # Ensure log directory exists
        log_file.parent.mkdir(parents=True, exist_ok=True)
        # File Handler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logging.info(f"Logging initialized. Level: {log_level}. File: {log_file if log_file else 'Console'}")


def get_logger(name: str) -> logging.Logger:
    """Returns a logger instance for the given name."""
    return logging.getLogger(name)

# Example of how to use it in other modules:
# from .logger_setup import get_logger
# logger = get_logger(__name__)
# logger.info("This is an info message.")