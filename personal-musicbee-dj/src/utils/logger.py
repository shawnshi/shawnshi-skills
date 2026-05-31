"""
Global Logger for MusicBee DJ
"""
import logging
import sys

def setup_logger(name: str = "MusicBee-DJ") -> logging.Logger:
    """
    Configures and returns a robust logger instance for terminal output and future file logging.
    """
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # Console Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-7s | %(name)s | %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # Prevent propagation
        logger.propagate = False
        
    return logger

log = setup_logger()
