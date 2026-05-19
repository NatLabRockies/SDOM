"""Tests for the zonal Block-construction path of ``initialize_model``.

Covers per-area Block dispatch with a transportation
model linking areas. Asserts the model topology, per-area sub-blocks,
signed flow variable, capacity constraints, and end-to-end LP feasibility.

Result-collection (``run_solver`` / ``collect_results_from_model``) under
the zonal path lands in the results collector — these tests therefore drive the
solver via the raw Pyomo solver factory.
"""

from __future__ import annotations

import copy
import os

import pandas as pd
import pyomo.environ as pyo
import pytest

from sdom import initialize_model, load_data
from sdom.constants import (
    AREA_TRANSPORTATION_MODEL_NETWORK,
    COPPER_PLATE_NETWORK,
    IMPORTS_EXPORTS_CAPACITY_PRICE_NET_LOAD,
    IMPORTS_EXPORTS_NOT_MODEL,
)
from sdom.io_manager import get_network_formulation


REL_ZONAL_FIXTURE = "Data/zonal_test"


def _abs_data_path(rel: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", rel))


@pytest.fixture(scope="module")
def zonal_data():
    return load_data(_abs_data_path(REL_ZONAL_FIXTURE))


@pytest.fixture(scope="module")
def zonal_model(zonal_data):
    return initialize_model(
        zonal_data, n_hours=24, with_resilience_constraints=False
    )


def _highs_solver():
    """Return an available HiGHS solver instance or skip the test."""
    for name in ("appsi_highs", "highs"):
        try:
            s = pyo.SolverFactory(name)
            if s is not None and s.available(exception_flag=False):
                return s
        except Exception:
            continue
    pytest.skip("HiGHS solver not available")


# ---------------------------------------------------------------------------
# Dispatcher classification
# ---------------------------------------------------------------------------
def test_dispatcher_classification_helpers_are_consistent(zonal_data):
    """``data['areas']`` and ``get_network_formulation`` agree on the dispatch axis."""
    legacy = load_data(_abs_data_path("Data/no_exchange_run_of_river"))
    assert get_network_formulation(legacy) == COPPER_PLATE_NETWORK
    assert len(legacy["areas"]) == 1

    assert get_network_formulation(zonal_data) == AREA_TRANSPORTATION_MODEL_NETWORK
    assert len(zonal_data["areas"]) >= 2


# ---------------------------------------------------------------------------
# Topology + per-area sub-blocks
# ---------------------------------------------------------------------------
def test_zonal_model_has_area_set_and_blocks(zonal_data, zonal_model):
    declared_areas = [a["area_id"] for a in zonal_data["areas"]]
    assert list(zonal_model.A) == declared_areas

    assert hasattr(zonal_model, "area")
    for a in declared_areas:
        ab = zonal_model.area[a]
        for sub in (
            "pv",
            "wind",
            "thermal",
            "storage",
            "hydro",
            "demand",
            "nuclear",
            "other_renewables",
        ):
            assert hasattr(ab, sub), f"area '{a}' is missing sub-block '{sub}'"
        assert len(ab.h) == 24


def test_zonal_model_has_signed_flow_with_capacity_constraints(zonal_data, zonal_model):
    line_ids = [l["line_id"] for l in zonal_data["lines"]]
    assert list(zonal_model.L) == line_ids

    # Signed flow variable is over Reals; capacity is enforced by explicit
    # Constraint blocks (PRD §5.6 locked decision), not Var bounds.
    for l in line_ids:
        for h in zonal_model.h:
            assert zonal_model.f[l, h].domain is pyo.Reals
            assert zonal_model.f[l, h].lb is None
            assert zonal_model.f[l, h].ub is None

    n_l, n_h = len(line_ids), len(zonal_model.h)
    assert len(zonal_model.f_upper) == n_l * n_h
    assert len(zonal_model.f_lower) == n_l * n_h


def test_zonal_supply_balance_per_area_and_genmix_at_top(zonal_data, zonal_model):
    n_h = len(zonal_model.h)
    for a in zonal_model.A:
        assert len(zonal_model.area[a].SupplyBalance) == n_h

    assert hasattr(zonal_model, "GenMix_Share")
    assert hasattr(zonal_model, "GenMix_Target")


# ---------------------------------------------------------------------------
# End-to-end LP feasibility
# ---------------------------------------------------------------------------
def test_zonal_model_solves_to_optimality_with_highs(zonal_model):
    solver = _highs_solver()
    results = solver.solve(zonal_model, tee=False)
    assert (
        results.solver.termination_condition == pyo.TerminationCondition.optimal
    )
    obj_val = pyo.value(zonal_model.Obj)
    assert obj_val > 0

    # Every flow honours its asymmetric capacity bounds.
    for l in zonal_model.L:
        for h in zonal_model.h:
            f = pyo.value(zonal_model.f[l, h])
            cap_ft = float(zonal_model.LineCap_FT[l, h])
            cap_tf = float(zonal_model.LineCap_TF[l, h])
            assert -cap_tf - 1e-6 <= f <= cap_ft + 1e-6


def test_zonal_supply_balance_holds_at_optimum(zonal_model):
    solver = _highs_solver()
    solver.solve(zonal_model, tee=False)

    tol = 1e-3
    for a in zonal_model.A:
        ab = zonal_model.area[a]
        for h in zonal_model.h:
            gen = (
                pyo.value(ab.pv.generation[h])
                + pyo.value(ab.wind.generation[h])
                + sum(
                    pyo.value(ab.thermal.generation[h, bu])
                    for bu in ab.thermal.plants_set
                )
                + pyo.value(ab.hydro.generation[h])
                + pyo.value(ab.nuclear.alpha)
                * pyo.value(ab.nuclear.ts_parameter[h])
                + pyo.value(ab.other_renewables.alpha)
                * pyo.value(ab.other_renewables.ts_parameter[h])
                + sum(pyo.value(ab.storage.PD[h, j]) for j in ab.storage.j)
            )
            charging = sum(
                pyo.value(ab.storage.PC[h, j]) for j in ab.storage.j
            )
            net_inflow = sum(
                pyo.value(zonal_model.f[l, h]) for l in zonal_model.L_in[a]
            ) - sum(
                pyo.value(zonal_model.f[l, h]) for l in zonal_model.L_out[a]
            )
            demand = pyo.value(ab.demand.ts_parameter[h])
            residual = gen + net_inflow - charging - demand
            assert abs(residual) < tol, (
                f"area={a} hour={h} residual={residual:.6e}"
            )


# ---------------------------------------------------------------------------
# Guards: deferred features under the AT path
# ---------------------------------------------------------------------------
def test_resiliency_under_zonal_raises_not_implemented(zonal_data):
    with pytest.raises(NotImplementedError) as excinfo:
        initialize_model(
            zonal_data, n_hours=24, with_resilience_constraints=True
        )
    assert AREA_TRANSPORTATION_MODEL_NETWORK in str(excinfo.value)


def test_imports_under_zonal_raises_not_implemented(zonal_data):
    """AT + non-NotModel Imports must raise until the follow-up commit."""
    mutated = copy.deepcopy(zonal_data)
    mutated["formulations"] = pd.DataFrame(
        [
            {"Component": "Hydro", "Formulation": "RunOfRiverFormulation"},
            {
                "Component": "Imports",
                "Formulation": IMPORTS_EXPORTS_CAPACITY_PRICE_NET_LOAD,
            },
            {"Component": "Exports", "Formulation": IMPORTS_EXPORTS_NOT_MODEL},
            {
                "Component": "Network",
                "Formulation": AREA_TRANSPORTATION_MODEL_NETWORK,
            },
        ]
    )
    with pytest.raises(NotImplementedError) as excinfo:
        initialize_model(mutated, n_hours=24)
    msg = str(excinfo.value)
    assert "imports" in msg.lower()
    assert IMPORTS_EXPORTS_NOT_MODEL in msg
