import logging
from .constants import LOG_COLORS


def _normalize_third_party_loggers() -> None:
    """Route third-party logs through SDOM root handlers only.

    Pyomo installs a default ``pyomo`` logger ``StreamHandler`` that writes the
    raw message (without level prefix). Because that logger also propagates to
    root, messages can appear twice when SDOM configures root logging.
    """
    pyomo_logger = logging.getLogger("pyomo")
    pyomo_logger.handlers.clear()
    pyomo_logger.propagate = True

class ColorFormatter(logging.Formatter):
    """Custom logging formatter that adds color codes to log level names.
    
    This formatter applies ANSI color codes to different log levels for improved
    readability in terminal output. Colors are defined in the LOG_COLORS constant.
    
    Attributes:
        COLORS (dict): Mapping of log level names to ANSI color codes.
        RESET (str): ANSI reset code to restore default terminal colors.
    """
    COLORS = LOG_COLORS
        
    RESET = '\033[0m'

    def format(self, record):
        """Apply color formatting to log record level names.
        
        Args:
            record (logging.LogRecord): The log record to format.
        
        Returns:
            str: The formatted log message with colored level name.
        """
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
        return super().format(record)

def configure_logging(level=logging.INFO, log_file=None):
    """Configure the logging system with colored console output and optional file logging.
    
    Sets up logging handlers with color-coded formatting for terminal output.
    Optionally writes logs to a file as well. Should be called once at the start
    of SDOM execution.
    
    Args:
        level (int, optional): Logging level threshold (e.g., logging.INFO, logging.DEBUG).
            Defaults to logging.INFO.
        log_file (str, optional): Path to a file where logs should be written.
            If None, logs only to console. Defaults to None.
    
    Returns:
        None
    
    Notes:
        The format includes timestamp and log level: 'YYYY-MM-DD HH:MM:SS-new line-LEVEL - message'
        Color formatting is applied via the ColorFormatter class using ANSI codes.
        Multiple calls will reconfigure the logging system.
    """
    handlers = [logging.StreamHandler()]
    formatter = ColorFormatter('%(levelname)s - %(message)s')

    if log_file:
        handlers.append(logging.FileHandler(log_file))

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=handlers, force=True)
    _normalize_third_party_loggers()
