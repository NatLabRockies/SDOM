"""Tests for SDOM logging configuration behavior."""

import logging

from sdom.config_sdom import configure_logging


def _seed_pyomo_default_handler() -> logging.Logger:
    """Simulate Pyomo's default logger setup used outside SDOM."""
    pyomo_logger = logging.getLogger("pyomo")
    pyomo_logger.handlers.clear()
    pyomo_logger.addHandler(logging.StreamHandler())
    pyomo_logger.propagate = True
    return pyomo_logger


def test_configure_logging_clears_pyomo_handlers():
    pyomo_logger = _seed_pyomo_default_handler()

    configure_logging(level=logging.INFO)

    assert pyomo_logger.handlers == []
    assert pyomo_logger.propagate is True


def test_configure_logging_prevents_duplicate_pyomo_output(capsys):
    pyomo_logger = _seed_pyomo_default_handler()

    configure_logging(level=logging.INFO)
    pyomo_logger.info("duplicate-check-message")

    captured = capsys.readouterr()
    emitted = captured.out + captured.err

    assert emitted.count("duplicate-check-message") == 1
