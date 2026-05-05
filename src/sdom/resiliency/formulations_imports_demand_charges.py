"""Imports formulation with monthly fixed and variable demand charges.

This module is part of the SDOM resiliency-evaluation package. It defines a
standalone Pyomo block builder that models hourly imports with two billing-period
peak demand charges (fixed and variable, monthly). It mirrors the layered design
of :mod:`sdom.models.formulations_imports_exports` but is intentionally
self-contained: it does NOT inherit from or modify any existing formulation
module.

Notes
-----
- Pure linear program: no binary variables, no big-M.
- The block is opt-in via ``formulation_overrides`` and is **not** registered in
  ``constants.py`` or ``io_manager.py``.
- Monthly fixed-charge tariffs :math:`\\phi^{fix}_{t}` MUST be constant within
  each month. A non-constant series triggers a :class:`UserWarning`.
"""

from __future__ import annotations

import warnings

import pandas as pd
import pyomo.environ as pyo


__all__ = ["add_imports_with_demand_charges"]


def _validate_phi_fix_monthly_constancy(
    phi_fix_t: pd.Series, month_of_hour: pd.Series
) -> None:
    """Warn if ``phi_fix_t`` is not constant within each month.

    Parameters
    ----------
    phi_fix_t : pandas.Series
        Hourly fixed-charge tariff (USD/MW), indexed by hour.
    month_of_hour : pandas.Series
        Mapping hour -> month index.
    """
    df = pd.DataFrame({"phi": phi_fix_t, "month": month_of_hour})
    nunique = df.groupby("month")["phi"].nunique()
    bad_months = nunique[nunique > 1].index.tolist()
    if bad_months:
        warnings.warn(
            f"phi_fix_t is not constant within month(s) {bad_months}; "
            "the fixed demand charge is defined as a monthly tariff and "
            "should not vary hourly inside a billing month.",
            UserWarning,
            stacklevel=3,
        )


def add_imports_with_demand_charges(
    model,
    *,
    import_cap: pd.Series,
    import_price: pd.Series,
    phi_fix_t: pd.Series,
    phi_var_t: pd.Series,
    month_of_hour: pd.Series,
    block_name: str = "imports",
):
    """Attach the ``ImportsWithDemandChargesFormulation`` block to ``model``.

    The block adds hourly import variables ``Pimp[t]``, monthly fixed and
    variable demand-charge variables ``D_fix[m]`` / ``D_var[m]``, the capacity
    bound, the demand-charge linking inequalities, and an additive cost
    expression ``total_cost_expr`` suitable for inclusion in any objective.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Host model. Must already define ``model.h`` (a Pyomo :class:`Set` of
        hour indices).
    import_cap : pandas.Series
        Hourly import capacity :math:`\\overline{P}^{imp}_{t}` (MW), indexed by
        hour matching ``model.h``.
    import_price : pandas.Series
        Hourly import energy price :math:`c^{imp}_{t}` (USD/MWh).
    phi_fix_t : pandas.Series
        Hourly fixed demand-charge tariff :math:`\\phi^{fix}_{t}` (USD/MW).
        Must be constant within each calendar month.
    phi_var_t : pandas.Series
        Hourly variable (time-of-use) demand-charge tariff
        :math:`\\phi^{var}_{t}` (USD/MW).
    month_of_hour : pandas.Series
        Mapping hour -> month integer.
    block_name : str, optional
        Name of the sub-block attached to ``model``. Default ``"imports"``.

    Returns
    -------
    pyomo.environ.Block
        The block that was attached to ``model``.

    Raises
    ------
    AttributeError
        If ``model.h`` is not present.

    Notes
    -----
    The contributed cost is

    .. math::

        Z_{imp,dc} = \\sum_t c^{imp}_t\\, p^{imp}_t
                     + \\sum_m \\left( D^{fix}_m + D^{var}_m \\right),

    with linking constraints
    :math:`D^{k}_{m} \\ge \\phi^{k}_{t}\\, p^{imp}_{t}` for all
    :math:`t \\in \\mathcal{T}_m` and :math:`k \\in \\{fix, var\\}`.

    Examples
    --------
    >>> import pyomo.environ as pyo
    >>> import pandas as pd
    >>> m = pyo.ConcreteModel()
    >>> m.h = pyo.RangeSet(1, 24)
    >>> idx = range(1, 25)
    >>> add_imports_with_demand_charges(  # doctest: +SKIP
    ...     m,
    ...     import_cap=pd.Series(100.0, index=idx),
    ...     import_price=pd.Series(1.0, index=idx),
    ...     phi_fix_t=pd.Series(50.0, index=idx),
    ...     phi_var_t=pd.Series(2.0, index=idx),
    ...     month_of_hour=pd.Series(1, index=idx),
    ... )
    """
    if not hasattr(model, "h"):
        raise AttributeError("model must declare an hourly set 'model.h' before calling this builder.")

    _validate_phi_fix_monthly_constancy(phi_fix_t, month_of_hour)

    block = pyo.Block()
    model.add_component(block_name, block)

    # Variables
    block.Pimp = pyo.Var(model.h, domain=pyo.NonNegativeReals, initialize=0)

    months_sorted = sorted({int(v) for v in month_of_hour.unique()})
    block.M = pyo.Set(initialize=months_sorted, ordered=True)
    block.D_fix = pyo.Var(block.M, domain=pyo.NonNegativeReals, initialize=0)
    block.D_var = pyo.Var(block.M, domain=pyo.NonNegativeReals, initialize=0)

    # Parameters
    block.cap_param = pyo.Param(model.h, initialize=import_cap.to_dict(), mutable=False)
    block.price_param = pyo.Param(model.h, initialize=import_price.to_dict(), mutable=False)
    block.phi_fix_param = pyo.Param(model.h, initialize=phi_fix_t.to_dict(), mutable=False)
    block.phi_var_param = pyo.Param(model.h, initialize=phi_var_t.to_dict(), mutable=False)

    # Cache hour -> month mapping (plain dict for closure capture)
    month_map = {int(t): int(m) for t, m in month_of_hour.items()}

    # Constraints
    def _capacity_rule(b, t):
        return b.Pimp[t] <= b.cap_param[t]

    block.capacity_constraint = pyo.Constraint(model.h, rule=_capacity_rule)

    def _dc_fix_rule(b, t):
        m = month_map[t]
        return b.D_fix[m] >= b.phi_fix_param[t] * b.Pimp[t]

    block.demand_charge_fix_constraint = pyo.Constraint(model.h, rule=_dc_fix_rule)

    def _dc_var_rule(b, t):
        m = month_map[t]
        return b.D_var[m] >= b.phi_var_param[t] * b.Pimp[t]

    block.demand_charge_var_constraint = pyo.Constraint(model.h, rule=_dc_var_rule)

    # Cost expression
    block.total_cost_expr = pyo.Expression(
        expr=sum(block.price_param[t] * block.Pimp[t] for t in model.h)
        + sum(block.D_fix[m] + block.D_var[m] for m in block.M)
    )

    return block
