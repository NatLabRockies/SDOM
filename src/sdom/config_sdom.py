import logging
import sys
from .constants import LOG_COLORS


class LazyStreamHandler(logging.StreamHandler):
    """A ``StreamHandler`` that resolves its target stream at emit time.

    The stock ``logging.StreamHandler`` snapshots ``sys.stderr`` at
    construction time and keeps that reference for the handler's lifetime.
    That breaks in any environment that swaps ``sys.stderr`` after
    ``configure_logging`` runs (pytest's per-test capture buffers, Jupyter
    kernels, embedded apps), because the handler can end up holding a
    reference to a stream that has since been closed, causing
    ``ValueError: I/O operation on closed file`` on the next log record.

    This subclass overrides ``stream`` as a property that re-reads the
    current ``sys.stderr`` (or ``sys.stdout``) every time the handler
    formats/emits a record, so the handler tracks the live stream.
    """

    def __init__(self, stream_name: str = "stderr") -> None:
        if stream_name not in ("stderr", "stdout"):
            raise ValueError(
                f"stream_name must be 'stderr' or 'stdout', got {stream_name!r}"
            )
        # Bypass ``StreamHandler.__init__`` (which would pin a concrete
        # stream attribute) but still run ``Handler.__init__`` so locks and
        # level are initialized.
        logging.Handler.__init__(self)
        self._stream_name = stream_name
        self._stream_override = None

    @property
    def stream(self):
        """Return the pinned override (if any) or the *current* ``sys`` stream."""
        if self._stream_override is not None:
            return self._stream_override
        return getattr(sys, self._stream_name)

    @stream.setter
    def stream(self, value):
        # Honor explicit assignments so context managers that swap the
        # handler's stream (notably ``pyomo.common.log._StreamRedirector``
        # used by ``capture_output(capture_fd=True)``) continue to work.
        # When the assigned value is the *current* live ``sys`` stream, we
        # drop the override and resume lazy resolution -- this is how
        # well-behaved redirectors "restore" the original stream on exit.
        if value is getattr(sys, self._stream_name):
            self._stream_override = None
        else:
            self._stream_override = value


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
    handlers = [LazyStreamHandler("stderr")]
    formatter = ColorFormatter('%(levelname)s - %(message)s')

    if log_file:
        handlers.append(logging.FileHandler(log_file))

    for handler in handlers:
        handler.setFormatter(formatter)

    # Replace root handlers without closing the previous ones. ``basicConfig(
    # force=True)`` would call ``.close()`` on every existing handler, which
    # is unsafe in environments (notably pytest's log-capture and live-log
    # plugins) that attach handlers owning resources they manage themselves.
    # Closing those handlers from inside SDOM corrupts the host's state and,
    # combined with pyomo's ``capture_output(capture_fd=True)``, can deadlock
    # the next solver call on flush during context teardown.
    root_logger = logging.getLogger()
    for existing in list(root_logger.handlers):
        root_logger.removeHandler(existing)
    for handler in handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(level)
    _normalize_third_party_loggers()
