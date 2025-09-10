"""Logging configuration for Hollow Knight bot."""

import logging
import sys
from typing import Optional

from .config import config


def setup_logging(log_level: Optional[str] = None) -> logging.Logger:
    """Set up logging configuration for the bot.
    
    Args:
        log_level: Override the log level from config
        
    Returns:
        Configured logger instance
    """
    level = log_level or config.log_level
    
    # Create formatter
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # Create file handler
    file_handler = logging.FileHandler('hollow_bot.log')
    file_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Create bot logger
    bot_logger = logging.getLogger("hollowbot")
    bot_logger.setLevel(getattr(logging, level.upper()))
    
    return bot_logger


# Initialize logger
log = setup_logging()
