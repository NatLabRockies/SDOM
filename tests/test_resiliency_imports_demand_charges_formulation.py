"""Tests for ``ImportsWithDemandChargesFormulation`` (Phase 2).

Covers the standalone Pyomo block builder living in
``src/sdom/resiliency/formulations_imports_demand_charges.py``.
"""

from __future__ import annotations

import logging

import pandas as pd
import pyomo.environ as pyo
import pytest

from sdom.resiliency import add_imports_with_demand_charges


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_two_month_model(n_hours: int = 48) -> pyo.ConcreteModel:
    """Return a minimal model with hours 1..n_hours and 2 months (24 hrs each)."""
    model = pyo.ConcreteModel()
    model.h = pyo.RangeSet(1, n_hours)
    month_map = {t: 1 if t <= 24 else 2 for t in range(1, n_hours + 1)}
    model.month_of_hour = pyo.Param(model.h, initialize=month_map, within=pyo.PositiveIntegers)
    return model


def _series(values, *, n_hours: int = 48) -> pd.Series:
    """Build a Series indexed 1..n_hours from a scalar or iterable."""
    if hasattr(values, "__iter__") and not isinstance(values, str):
        data = list(values)
        assert len(data) == n_hours
    else:
        data = [values] * n_hours
    return pd.Series(data, index=range(1, n_hours + 1))


def _highs_solver():
    """Return a HiGHS solver factory or skip the calling test."""
    for name in ("appsi_highs", "highs"):
        try:
            solver = pyo.SolverFactory(name)
            if solver is not None and solver.available(exception_flag=False):
                return solver
        except Exception:
            continue
    pytest.skip("HiGHS solver not available")


# ---------------------------------------------------------------------------
# 1. Block structure
# ---------------------------------------------------------------------------
def test_block_structure_attached():
    model = _make_two_month_model()
    n = 48
    add_imports_with_demand_charges(
        model,
        import_cap=_series(100.0, n_hours=n),
        import_price=_series(1.0, n_hours=n),
        phi_fix_t=_series([100.0] * 24 + [120.0] * 24, n_hours=n),
        phi_var_t=_series([5.0] * 24 + [8.0] * 24, n_hours=n),
        month_of_hour=pd.Series(
            [1] * 24 + [2] * 24, index=range(1, n + 1)
        ),
    )

    block = model.imports
    # Pimp variable
    assert hasattr(block, "Pimp")
    for t in model.h:
        assert block.Pimp[t].domain is pyo.NonNegativeReals

    # Monthly variables
    assert hasattr(block, "M")
    months = set(block.M)
    assert months == {1, 2}
    for m in months:
        assert block.D_fix[m].domain is pyo.NonNegativeReals
        assert block.D_var[m].domain is pyo.NonNegativeReals

    # Constraints
    assert hasattr(block, "capacity_constraint")
    assert hasattr(block, "demand_charge_fix_constraint")
    assert hasattr(block, "demand_charge_var_constraint")

    # Cost expression
    assert hasattr(block, "total_cost_expr")
    assert isinstance(block.total_cost_expr, pyo.Expression)


# ---------------------------------------------------------------------------
# 2. Solve: zero imports when no demand
# ---------------------------------------------------------------------------
def test_solve_zero_imports():
    solver = _highs_solver()
    n = 48
    model = _make_two_month_model(n_hours=n)
    add_imports_with_demand_charges(
        model,
        import_cap=_series(100.0, n_hours=n),
        import_price=_series(2.0, n_hours=n),
        phi_fix_t=_series([100.0] * 24 + [120.0] * 24, n_hours=n),
        phi_var_t=_series([5.0] * 24 + [8.0] * 24, n_hours=n),
        month_of_hour=pd.Series([1] * 24 + [2] * 24, index=range(1, n + 1)),
    )

    model.objective = pyo.Objective(expr=model.imports.total_cost_expr, sense=pyo.minimize)
    res = solver.solve(model)
    assert str(res.solver.termination_condition) == "optimal"

    for t in model.h:
        assert pyo.value(model.imports.Pimp[t]) == pytest.approx(0.0, abs=1e-7)
    for m in model.imports.M:
        assert pyo.value(model.imports.D_fix[m]) == pytest.approx(0.0, abs=1e-7)
        assert pyo.value(model.imports.D_var[m]) == pytest.approx(0.0, abs=1e-7)
    assert pyo.value(model.objective) == pytest.approx(0.0, abs=1e-7)


# ---------------------------------------------------------------------------
# 3. Solve: forces monthly peak demand charges
# ---------------------------------------------------------------------------
def test_solve_forces_monthly_peak():
    solver = _highs_solver()
    n = 48

    # Demand profile
    demand = [0.0] * n
    demand[0] = 10.0  # hour 1
    demand[1] = 20.0  # hour 2
    demand[2] = 30.0  # hour 3 (month 1 peak)
    demand[47] = 50.0  # hour 48 (month 2 peak)

    model = _make_two_month_model(n_hours=n)
    add_imports_with_demand_charges(
        model,
        import_cap=_series(1000.0, n_hours=n),
        import_price=_series(1.0, n_hours=n),
        phi_fix_t=_series([100.0] * 24 + [100.0] * 24, n_hours=n),
        phi_var_t=_series([5.0] * 24 + [8.0] * 24, n_hours=n),
        month_of_hour=pd.Series([1] * 24 + [2] * 24, index=range(1, n + 1)),
    )

    # Force Pimp[t] == demand[t]
    demand_map = {t: demand[t - 1] for t in range(1, n + 1)}
    model.fix_imports = pyo.Constraint(
        model.h, rule=lambda mdl, t: mdl.imports.Pimp[t] == demand_map[t]
    )

    model.objective = pyo.Objective(expr=model.imports.total_cost_expr, sense=pyo.minimize)
    res = solver.solve(model)
    assert str(res.solver.termination_condition) == "optimal"

    assert pyo.value(model.imports.D_fix[1]) == pytest.approx(3000.0, rel=1e-6)
    assert pyo.value(model.imports.D_fix[2]) == pytest.approx(5000.0, rel=1e-6)
    assert pyo.value(model.imports.D_var[1]) == pytest.approx(150.0, rel=1e-6)
    assert pyo.value(model.imports.D_var[2]) == pytest.approx(400.0, rel=1e-6)
    assert pyo.value(model.objective) == pytest.approx(8660.0, rel=1e-6)


# ---------------------------------------------------------------------------
# 4. Validation warning on non-constant phi_fix within a month
# ---------------------------------------------------------------------------
def test_phi_fix_validation_warns_when_nonconstant_within_month(caplog):
    n = 48
    model = _make_two_month_model(n_hours=n)
    bad_phi_fix = [100.0] * 24 + [120.0] * 24
    bad_phi_fix[1] = 110.0  # vary within month 1

    with caplog.at_level(
        logging.WARNING,
        logger="sdom.resiliency.formulations_imports_demand_charges",
    ):
        add_imports_with_demand_charges(
            model,
            import_cap=_series(100.0, n_hours=n),
            import_price=_series(1.0, n_hours=n),
            phi_fix_t=_series(bad_phi_fix, n_hours=n),
            phi_var_t=_series([5.0] * 24 + [8.0] * 24, n_hours=n),
            month_of_hour=pd.Series([1] * 24 + [2] * 24, index=range(1, n + 1)),
        )
    assert any("phi_fix" in rec.getMessage() for rec in caplog.records)
