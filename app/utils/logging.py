import logging
import sys
from datetime import datetime
from pathlib import Path

from app.config import settings

def setup_logging():
    """Configure logging for the application"""
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, settings.LOG_LEVEL))
    
    # Remove existing handlers to avoid duplicates
    logger.handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, settings.LOG_LEVEL))
    
    # Format
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(formatter)

    try:
        console_handler.stream.reconfigure(encoding='utf-8')  # 👈 dành cho Python 3.7+
    except Exception:
        pass

    logger.addHandler(console_handler)
    
    # File handler if configured
    if settings.LOG_FILE:
        # Use datestamp in filename
        timestamp = datetime.now().strftime('%Y%m%d')
        log_path = Path(f"{settings.LOG_FILE.split('.')[0]}_{timestamp}.log")
        
        # Create parent directory if it doesn't exist
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(getattr(logging, settings.LOG_LEVEL))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    # Suppress overly verbose logs from libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    return logger