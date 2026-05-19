"""Tests for ``sdom.models.formulations_network`` (PRD §5.6).

These tests build a small isolated ``ConcreteModel`` (3 areas, 2 lines,
3 hours) and validate the topology, parameters, variable, constraints,
expressions, and dual accessibility independently of the rest of SDOM.
"""

import pytest
import pyomo.environ as pyo

from sdom.models.formulations_network import (
    add_network_constraints,
    add_network_expressions,
    add_network_parameters,
    add_network_sets,
    add_network_variables,
    network_transmission_cost_rule,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
AREAS = ["A1", "A2", "A3"]
HOURS = [1, 2, 3]
LINES = ["L1", "L2"]
LINE_FROM = {"L1": "A1", "L2": "A2"}
LINE_TO = {"L1": "A2", "L2": "A3"}
CAP_FT = 100.0
CAP_TF = 80.0


def _base_model():
    m = pyo.ConcreteModel()
    m.A = pyo.Set(initialize=AREAS, ordered=True)
    m.h = pyo.Set(initialize=HOURS, ordered=True)
    return m


def _full_model():
    m = _base_model()
    add_network_sets(m, lines=LINES, line_from=LINE_FROM, line_to=LINE_TO)
    line_cap_ft = {(l, h): CAP_FT for l in LINES for h in HOURS}
    line_cap_tf = {(l, h): CAP_TF for l in LINES for h in HOURS}
    add_network_parameters(m, line_cap_ft=line_cap_ft, line_cap_tf=line_cap_tf)
    add_network_variables(m)
    add_network_constraints(m)
    add_network_expressions(m)
    return m


# ---------------------------------------------------------------------------
# Solver helper (mirrors pattern in tests/test_resiliency_baseline_dispatch.py)
# ---------------------------------------------------------------------------
def _highs():
    for name in ("appsi_highs", "highs"):
        try:
            s = pyo.SolverFactory(name)
            if s is not None and s.available(exception_flag=False):
                return s
        except Exception:
            continue
    pytest.skip("HiGHS solver not available")


# ---------------------------------------------------------------------------
# 1. add_network_sets — line set + from/to params
# ---------------------------------------------------------------------------
def test_add_network_sets_populates_topology():
    m = _base_model()
    add_network_sets(m, lines=LINES, line_from=LINE_FROM, line_to=LINE_TO)

    assert list(m.L) == ["L1", "L2"]
    assert pyo.value(m.line_from["L1"]) == "A1"
    assert pyo.value(m.line_from["L2"]) == "A2"
    assert pyo.value(m.line_to["L1"]) == "A2"
    assert pyo.value(m.line_to["L2"]) == "A3"


# ---------------------------------------------------------------------------
# 2. L_in[a] — incoming lines per area
# ---------------------------------------------------------------------------
def test_add_network_sets_L_in_per_area():
    m = _base_model()
    add_network_sets(m, lines=LINES, line_from=LINE_FROM, line_to=LINE_TO)

    assert set(m.L_in["A1"]) == set()
    assert set(m.L_in["A2"]) == {"L1"}
    assert set(m.L_in["A3"]) == {"L2"}


# ---------------------------------------------------------------------------
# 3. L_out[a] — outgoing lines per area
# ---------------------------------------------------------------------------
def test_add_network_sets_L_out_per_area():
    m = _base_model()
    add_network_sets(m, lines=LINES, line_from=LINE_FROM, line_to=LINE_TO)

    assert set(m.L_out["A1"]) == {"L1"}
    assert set(m.L_out["A2"]) == {"L2"}
    assert set(m.L_out["A3"]) == set()


# ---------------------------------------------------------------------------
# 4. add_network_parameters — directional capacity params
# ---------------------------------------------------------------------------
def test_add_network_parameters_values():
    m = _full_model()
    for l in LINES:
        for h in HOURS:
            assert pyo.value(m.LineCap_FT[l, h]) == pytest.approx(CAP_FT)
            assert pyo.value(m.LineCap_TF[l, h]) == pytest.approx(CAP_TF)


# ---------------------------------------------------------------------------
# 5. add_network_variables — signed flow var, no bounds
# ---------------------------------------------------------------------------
def test_add_network_variables_signed_unbounded():
    m = _base_model()
    add_network_sets(m, lines=LINES, line_from=LINE_FROM, line_to=LINE_TO)
    add_network_variables(m)

    # No bounds on the Var itself — capacity is enforced via constraints.
    for l in LINES:
        for h in HOURS:
            assert m.f[l, h].domain is pyo.Reals
            assert m.f[l, h].lb is None
            assert m.f[l, h].ub is None


# ---------------------------------------------------------------------------
# 6. add_network_constraints — count and structure
# ---------------------------------------------------------------------------
def test_add_network_constraints_count():
    m = _full_model()
    expected = len(LINES) * len(HOURS)
    assert len(m.f_upper) == expected
    assert len(m.f_lower) == expected


# ---------------------------------------------------------------------------
# 7. Per-direction congestion duals are accessible
# ---------------------------------------------------------------------------
def test_f_upper_dual_accessible_after_solve():
    solver = _highs()
    m = _full_model()
    m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)

    # Maximize sum(f) — every f_upper constraint must bind at LineCap_FT.
    m.obj = pyo.Objective(
        expr=sum(m.f[l, h] for l in m.L for h in m.h),
        sense=pyo.maximize,
    )

    results = solver.solve(m)
    status = str(results.solver.termination_condition)
    assert status in ("optimal", "TerminationCondition.optimal")

    # Every f[l,h] should be at its FT capacity.
    for l in m.L:
        for h in m.h:
            assert pyo.value(m.f[l, h]) == pytest.approx(CAP_FT)

    # Per-direction shadow prices must be available and non-zero on f_upper.
    nonzero = 0
    for l in m.L:
        for h in m.h:
            d_up = m.dual.get(m.f_upper[l, h])
            assert d_up is not None
            if abs(d_up) > 1e-9:
                nonzero += 1
    assert nonzero == len(LINES) * len(HOURS)


# ---------------------------------------------------------------------------
# 8. network_transmission_cost_rule — placeholder returns 0
# ---------------------------------------------------------------------------
def test_network_transmission_cost_rule_returns_zero():
    m = _full_model()
    assert network_transmission_cost_rule(m) == 0


# ---------------------------------------------------------------------------
# 9. add_network_expressions — signed scalars (reporting-only)
# ---------------------------------------------------------------------------
def test_add_network_expressions_are_signed_scalars():
    m = _full_model()
    # Fix f to a known value and verify the (signed) reporting expressions.
    for l in LINES:
        for h in HOURS:
            m.f[l, h].fix(50.0)
    for l in LINES:
        for h in HOURS:
            assert pyo.value(m.f_FT[l, h]) == pytest.approx(50.0)
            assert pyo.value(m.f_TF[l, h]) == pytest.approx(-50.0)

    for l in LINES:
        for h in HOURS:
            m.f[l, h].fix(-30.0)
    for l in LINES:
        for h in HOURS:
            # Downstream code is expected to clip to >= 0 with max(value, 0).
            assert max(pyo.value(m.f_FT[l, h]), 0.0) == pytest.approx(0.0)
            assert max(pyo.value(m.f_TF[l, h]), 0.0) == pytest.approx(30.0)
