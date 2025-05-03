import logging
import sys
import os
from datetime import datetime
from pathlib import Path
import colorama
from app.config import settings

# Initialize colorama for cross-platform colored terminal output
colorama.init()

class UnicodeConsoleHandler(logging.StreamHandler):
    """Custom StreamHandler that handles Unicode characters properly"""
    def __init__(self, stream=None):
        super().__init__(stream)
        
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            # Ensure the stream can handle Unicode or handle fallback
            try:
                stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                # Fallback to replacing problematic characters
                stream.write(msg.encode(stream.encoding, 'replace').decode(stream.encoding) + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

class EncodingFilter(logging.Filter):
    """Filter to handle encoding issues with log messages containing Unicode."""
    def filter(self, record):
        # Ensure all message attributes can be encoded safely
        for attr_name in ['msg', 'message']:
            if hasattr(record, attr_name) and isinstance(getattr(record, attr_name), str):
                try:
                    # Test if the string can be encoded in the console's encoding
                    getattr(record, attr_name).encode(sys.stdout.encoding or 'utf-8')
                except UnicodeEncodeError:
                    # Replace problematic characters
                    setattr(record, attr_name, 
                            getattr(record, attr_name).encode(sys.stdout.encoding or 'utf-8', 
                                                           'replace').decode(sys.stdout.encoding or 'utf-8'))
        return True

def get_colored_formatter():
    """Return a formatter that adds colors to log levels"""
    # ANSI color codes
    COLORS = {
        'DEBUG': colorama.Fore.CYAN,
        'INFO': colorama.Fore.GREEN,
        'WARNING': colorama.Fore.YELLOW,
        'ERROR': colorama.Fore.RED,
        'CRITICAL': colorama.Fore.RED + colorama.Style.BRIGHT
    }
    
    class ColoredFormatter(logging.Formatter):
        def format(self, record):
            levelname = record.levelname
            if levelname in COLORS:
                record.levelname = f"{COLORS[levelname]}{levelname}{colorama.Style.RESET_ALL}"
            return super().format(record)
    
    return ColoredFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def setup_logging():
    """Configure logging for the application with improved Unicode handling"""
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, settings.LOG_LEVEL))
    
    # Remove existing handlers to avoid duplicates
    logger.handlers = []
    
    # Console logging configuration
    console_log_enabled = getattr(settings, 'LOG_TO_CONSOLE', True)
    console_colored = getattr(settings, 'COLORED_LOGS', True)
    
    if console_log_enabled:
        # Use custom handler for better Unicode handling
        console_handler = UnicodeConsoleHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, settings.LOG_LEVEL))
        
        # Add encoding filter
        console_handler.addFilter(EncodingFilter())
        
        # Choose formatter based on color setting
        if console_colored:
            formatter = get_colored_formatter()
        else:
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            
        console_handler.setFormatter(formatter)
        
        # Try to set encoding explicitly
        try:
            console_handler.stream.reconfigure(encoding='utf-8')
        except (AttributeError, TypeError):
            # Fallback for Python versions that don't support reconfigure
            pass
            
        logger.addHandler(console_handler)
    
    # Áp dụng các cấu hình log level cụ thể cho từng module
    module_log_levels = getattr(settings, 'MODULE_LOG_LEVELS', {})
    for module, level in module_log_levels.items():
        logging.getLogger(module).setLevel(getattr(logging, level))
        
    logger.debug(f"Applied custom log levels for modules: {list(module_log_levels.keys())}")

    
    # File handler if configured
    if settings.LOG_FILE:
        try:
            # Use datestamp in filename
            timestamp = datetime.now().strftime('%Y%m%d')
            log_dir = os.path.dirname(settings.LOG_FILE) or '.'
            log_filename = os.path.basename(settings.LOG_FILE).split('.')[0]
            log_path = Path(f"{log_dir}/{log_filename}_{timestamp}.log")
            
            # Create parent directory if it doesn't exist
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Create file handler with UTF-8 encoding
            file_handler = logging.FileHandler(log_path, encoding='utf-8')
            file_handler.setLevel(getattr(logging, settings.LOG_LEVEL))
            
            # Always use plain formatter for files (no colors)
            file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            
            logger.addHandler(file_handler)
            logger.info(f"Log file created at {log_path}")
        except Exception as e:
            # If file logging fails, log to console
            logger.error(f"Failed to set up file logging: {str(e)}")
    
    # Set reduced logging level for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    
    # Log some diagnostic information
    logger.debug(f"Logging initialized. Console: {console_log_enabled}, Colors: {console_colored}")
    logger.debug(f"Python version: {sys.version}")
    logger.debug(f"Console encoding: {sys.stdout.encoding}")
    logger.debug(f"Default encoding: {sys.getdefaultencoding()}")
    
    return logger

def get_module_logger(name):
    """Helper to get a logger for a specific module"""
    return logging.getLogger(name)