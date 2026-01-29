"""
Logging utilities for the DevRel Research Agent.
Provides structured logging to both console and file.
"""

import logging
import sys
from pathlib import Path
from config import config


def setup_logging(log_file: str = None, log_level: str = None) -> None:
    """
    Configure logging for the application.

    Args:
        log_file: Path to log file (default from config)
        log_level: Logging level (default from config)
    """
    log_file = log_file or config.LOG_FILE
    log_level = log_level or config.LOG_LEVEL

    # Create logs directory if it doesn't exist
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Clear existing handlers
    root_logger.handlers.clear()

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(getattr(logging, log_level.upper()))
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Console handler (only warnings and above)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)
    console_formatter = logging.Formatter(
        '%(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.

    Args:
        name: Name of the module/component

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
