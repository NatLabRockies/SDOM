"""Extract numeric model values with collector-specific missing values."""


import numpy as np

from ..common.utilities import safe_pyomo_value


def _value_or_nan(obj) -> float:
    """Return a float value or NaN when not initialized/available."""
    val = getattr(obj, "value", None)
    if val is None:
        val = safe_pyomo_value(obj)
    return np.nan if val is None else float(val)


def _value_or_zero(obj) -> float:
    """Return a float value or zero when not initialized/available."""
    val = getattr(obj, "value", None)
    if val is None:
        val = safe_pyomo_value(obj)
    return 0.0 if val is None else float(val)
