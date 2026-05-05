"""Tests for the pure-LP ``WithoutNetLoadConstraints`` imports/exports formulation.

Phase 3 / Deliverable A.
"""

from __future__ import annotations

import pandas as pd
import pyomo.environ as pyo
import pytest

from sdom.constants import VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP
from sdom.models import formulations_imports_exports as fie


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _formulations_df(imports_form: str, exports_form: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Component": "Imports", "Formulation": imports_form},
            {"Component": "Exports", "Formulation": exports_form},
        ]
    )


def _build_minimal_model(
    *,
    imports_form: str,
    exports_form: str,
    n_hours: int = 24,
    cap_imports: float = 10.0,
    price_imports: float = 1.0,
    cap_exports: float = 10.0,
    price_exports: float = 1.0,
    demand: float = 5.0,
):
    """Build a tiny Pyomo model with imports/exports parameters and demand block."""
    model = pyo.ConcreteModel()
    model.h = pyo.RangeSet(1, n_hours)

    # data dict mimicking io_manager output shape used by these formulations
    cap_imports_df = pd.DataFrame(
        {"*Hour": list(range(1, n_hours + 1)), "Imports": [cap_imports] * n_hours}
    )
    price_imports_df = pd.DataFrame(
        {"*Hour": list(range(1, n_hours + 1)), "Imports_price": [price_imports] * n_hours}
    )
    cap_exports_df = pd.DataFrame(
        {"*Hour": list(range(1, n_hours + 1)), "Exports": [cap_exports] * n_hours}
    )
    price_exports_df = pd.DataFrame(
        {"*Hour": list(range(1, n_hours + 1)), "Exports_price": [price_exports] * n_hours}
    )
    data = {
        "formulations": _formulations_df(imports_form, exports_form),
        "cap_imports": cap_imports_df,
        "price_imports": price_imports_df,
        "cap_exports": cap_exports_df,
        "price_exports": price_exports_df,
    }

    # Imports and exports sub-blocks
    model.imports = pyo.Block()
    model.exports = pyo.Block()
    fie.add_imports_parameters(model, data)
    fie.add_exports_parameters(model, data)
    fie.add_imports_variables(model)
    fie.add_exports_variables(model)
    fie.add_imports_exports_cost_expressions(model, data)

    # demand stub for big-M path; net_load expression is required by the legacy path.
    model.demand = pyo.Block()
    model.demand.ts_parameter = pyo.Param(model.h, initialize={h: demand for h in model.h})
    model.net_load = pyo.Expression(
        model.h,
        rule=lambda mdl, h: mdl.demand.ts_parameter[h] - mdl.imports.variable[h] + mdl.exports.variable[h],
    )

    return model, data


def _highs_solver():
    for name in ("appsi_highs", "highs"):
        try:
            solver = pyo.SolverFactory(name)
            if solver is not None and solver.available(exception_flag=False):
                return solver
        except Exception:
            continue
    pytest.skip("HiGHS solver not available")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_without_net_load_constraints_registered():
    assert "WithoutNetLoadConstraints" in VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP
    desc = VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP["WithoutNetLoadConstraints"]
    assert isinstance(desc, str) and len(desc) > 0


def test_without_net_load_pure_lp():
    """Build with the new formulation; assert NO binary vars and exports run to capacity."""
    solver = _highs_solver()
    model, data = _build_minimal_model(
        imports_form="WithoutNetLoadConstraints",
        exports_form="WithoutNetLoadConstraints",
        n_hours=6,
        cap_exports=10.0,
        price_exports=2.0,
        cap_imports=10.0,
        price_imports=1.0,
    )

    fie.add_imports_constraints(model, data)
    fie.add_exports_constraints(model, data)

    # Pure LP guarantees: no binary auxiliary variable
    assert not hasattr(model, "aux_imp_exp_binary_variable")
    binary_vars = [
        v
        for v in model.component_data_objects(pyo.Var, active=True)
        if v.domain is pyo.Binary
    ]
    assert binary_vars == []

    # Maximize export revenue: sense is min, cost = imports - exports.
    # With positive export price and no demand coupling, optimum forces
    # exports = cap and imports = 0.
    model.objective = pyo.Objective(
        expr=fie.add_imports_exports_cost(model), sense=pyo.minimize
    )
    res = solver.solve(model)
    assert str(res.solver.termination_condition) == "optimal"
    for h in model.h:
        assert pyo.value(model.exports.variable[h]) == pytest.approx(10.0, abs=1e-6)
        assert pyo.value(model.imports.variable[h]) == pytest.approx(0.0, abs=1e-6)


def test_legacy_capacity_price_net_load_unaffected():
    """Regression guard: existing big-M coupling still added for the legacy path."""
    model, data = _build_minimal_model(
        imports_form="CapacityPriceNetLoadFormulation",
        exports_form="CapacityPriceNetLoadFormulation",
        n_hours=6,
    )
    fie.add_imports_constraints(model, data)
    fie.add_exports_constraints(model, data)

    # Big-M binary auxiliary variable must be present
    assert hasattr(model, "aux_imp_exp_binary_variable")
    # And the net-load coupling constraints
    assert hasattr(model, "imp_net_load_constraint")
    assert hasattr(model, "exp_net_load_constraint")
