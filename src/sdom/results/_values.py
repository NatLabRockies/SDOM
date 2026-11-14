"""Extract numeric model values with collector-specific missing values."""

import math
from collections.abc import Iterable

import numpy as np
from pyomo.core.base.var import IndexedVar
from pyomo.environ import value as pyo_value

from ..common.utilities import safe_pyomo_value


def _collect_curtailment_costs(host) -> dict[str, float]:
    """Extract authoritative signed costs, rejecting unavailable expressions.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with technology curtailment cost expressions. Inactive
        contributions have constant zero expressions by construction.

    Returns
    -------
    dict of str to float
        Solar PV, Wind, and Hydro costs in modeled-horizon USD.

    Raises
    ------
    ValueError
        If an expression is missing, uninitialized, or nonfinite.
    """
    costs = {}
    for technology, block in (("Solar PV", host.pv), ("Wind", host.wind), ("Hydro", host.hydro)):
        expression = getattr(block, "curtailment_cost_expr", None)
        amount = pyo_value(expression, exception=False) if expression is not None else None
        if amount is None or not math.isfinite(amount):
            raise ValueError(f"Missing or nonfinite curtailment cost for {host.name}, {technology}: {amount!r}")
        costs[technology] = float(amount)
    return costs


def _sum_initialized_dispatch(
    variable: IndexedVar,
    hours: Iterable[int],
    *,
    technology: str | None = None,
) -> float:
    """Sum dispatch numerically, rejecting missing or nonfinite values.

    Parameters
    ----------
    variable : pyomo.core.base.var.IndexedVar
        Dispatch indexed by hour, or by hour and storage technology.
    hours : iterable of int
        Modeled hours in their existing iteration order.
    technology : str, optional
        Storage technology used as the second index when supplied.

    Returns
    -------
    float
        Dispatch total, or zero when no hours are supplied.

    Raises
    ------
    ValueError
        If a dispatch value is missing or nonfinite. The diagnostic identifies
        the variable and hour rather than returning a partial total.
    """
    total = 0.0
    for hour in hours:
        datum = variable[hour] if technology is None else variable[hour, technology]
        value = safe_pyomo_value(datum)
        if value is None or not math.isfinite(value):
            raise ValueError(
                f"Missing or nonfinite dispatch for {datum.name} at hour {hour}: {value!r}"
            )
        total += value
    return total


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
