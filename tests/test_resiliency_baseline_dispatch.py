"""Phase 3 / Deliverable C: tests for ``build_baseline_dispatch`` / ``run_baseline_dispatch``."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyomo.environ as pyo
import pytest

from sdom.resiliency import (
    BaselineDispatchResults,
    DesignedSystem,
    build_baseline_dispatch,
    load_designed_system,
    run_baseline_dispatch,
)

from _resiliency_fixtures import (
    INPUTS_DIR_MEA,
    REPO_ROOT,
    SCENARIO_ID,
    SNAPSHOT_DIR_MEA,
    YEAR,
)

N_HOURS = 24


@pytest.fixture(scope="module")
def designed_system_mea() -> DesignedSystem:
    if not INPUTS_DIR_MEA.exists() or not SNAPSHOT_DIR_MEA.exists():
        pytest.skip(f"Paper_MEA fixtures missing under {INPUTS_DIR_MEA.parent.parent}")
    return load_designed_system(
        SNAPSHOT_DIR_MEA,
        inputs_dir=INPUTS_DIR_MEA,
        year=YEAR,
        scenario_id=SCENARIO_ID,
    )


@pytest.fixture(scope="module")
def baseline_model_mea(designed_system_mea):
    return build_baseline_dispatch(designed_system_mea, n_hours=N_HOURS)


@pytest.fixture(scope="module")
def baseline_results_mea(baseline_model_mea):
    return run_baseline_dispatch(baseline_model_mea, solver="highs")


# ---------------------------------------------------------------------------
# Synthetic fixture — REMOVED.
#
# The pre-refactor baseline-dispatch builder accepted a hand-rolled
# ``DesignedSystem`` (no ``cem_data``). After the CEM-reuse refactor
# (commit 5b346ad), ``build_baseline_dispatch`` requires ``cem_data`` so it
# can call ``_initialize_model_copperplate``. The tests below therefore
# exercise structure / capacity-pinning / solve on the MEA fixture loaded
# via ``designed_system_mea`` above.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Solver helper
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
# 1. Structure
# ---------------------------------------------------------------------------
def test_build_baseline_dispatch_n_hours_24(designed_system_mea):
    model = build_baseline_dispatch(designed_system_mea, n_hours=24)
    assert isinstance(model, pyo.ConcreteModel)
    # Hour set
    assert list(model.h) == list(range(1, 25))
    # Imports / exports blocks (CEM variable names after refactor)
    assert hasattr(model.imports, "variable")
    assert hasattr(model.exports, "variable")
    # Demand-charges block (Phase 2 layered builder)
    assert hasattr(model, "demand_charges")
    # Storage block — CEM names
    for name in ("PC", "PD", "SOC", "Pcha", "Pdis", "Ecap"):
        assert hasattr(model.storage, name), name
    # VRE blocks
    assert hasattr(model, "pv") and hasattr(model.pv, "generation")
    assert hasattr(model, "wind") and hasattr(model.wind, "generation")
    # Thermal block
    assert hasattr(model.thermal, "generation")
    assert hasattr(model.thermal, "plant_installed_capacity")
    # Power balance (CEM constraint name)
    assert hasattr(model, "SupplyBalance")
    for t in model.h:
        assert t in model.SupplyBalance
    # Operational objective (replaces full-cost ``Obj``)
    assert hasattr(model, "dispatch_objective")
    assert isinstance(model.dispatch_objective, pyo.Objective)


def test_baseline_dispatch_capacities_pinned(designed_system_mea):
    model = build_baseline_dispatch(designed_system_mea, n_hours=24)
    # Storage: Pcha/Pdis/Ecap scalar capacity vars fixed to DesignedSystem values.
    for s, spec in designed_system_mea.storage_caps.items():
        assert model.storage.Pcha[s].fixed
        assert model.storage.Pdis[s].fixed
        assert model.storage.Ecap[s].fixed
        assert pyo.value(model.storage.Pcha[s]) == pytest.approx(spec["Cap_Pch"])
        assert pyo.value(model.storage.Pdis[s]) == pytest.approx(spec["Cap_Pdis"])
        assert pyo.value(model.storage.Ecap[s]) == pytest.approx(spec["Cap_E"])
    # Thermal: plant_installed_capacity fixed for every plant in the CEM data.
    for bu in model.thermal.plants_set:
        assert model.thermal.plant_installed_capacity[bu].fixed
    # VRE: capacity_fraction is the design var (max_capacity is a Param).
    for k in designed_system_mea.solar_caps:
        assert model.pv.capacity_fraction[k].fixed
    for k in designed_system_mea.wind_caps:
        assert model.wind.capacity_fraction[k].fixed


def test_baseline_dispatch_solves_feasible(baseline_results_mea):
    res = baseline_results_mea
    assert res.solver_status == "optimal"
    obj = res.objective_value
    assert obj == pytest.approx(obj)  # finite (NaN check)
    assert abs(obj) < 1e15


def test_baseline_dispatch_min_soc_per_tech_kwarg(designed_system_mea):
    solver = _highs()
    tech = "Li-Ion"
    cap_e = designed_system_mea.storage_caps[tech]["Cap_E"]
    model = build_baseline_dispatch(
        designed_system_mea,
        n_hours=24,
        min_soc_per_tech={tech: 0.5},
    )
    for t in model.h:
        assert model.storage.SOC[t, tech].lb == pytest.approx(0.5 * cap_e)
    res = solver.solve(model)
    assert str(res.solver.termination_condition) == "optimal"
    for t in model.h:
        assert pyo.value(model.storage.SOC[t, tech]) >= 0.5 * cap_e - 1e-6


def test_run_baseline_dispatch_returns_results(baseline_results_mea, designed_system_mea):
    results = baseline_results_mea
    assert isinstance(results, BaselineDispatchResults)
    assert results.solver_status == "optimal"
    assert isinstance(results.objective_value, float)

    # Trajectory shapes — first axis is hours, second axis is the CEM set.
    n_storage_cem = len(results.soc_trajectory.columns)
    assert results.soc_trajectory.shape == (24, n_storage_cem)
    assert results.pcha_trajectory.shape == (24, n_storage_cem)
    assert results.pdis_trajectory.shape == (24, n_storage_cem)
    # Every storage tech in the filtered DesignedSystem must appear.
    for s in designed_system_mea.storage_caps:
        assert s in results.soc_trajectory.columns

    assert results.psolar_trajectory.shape[0] == 24
    assert results.psolar_trajectory.shape[1] == len(designed_system_mea.solar_caps)
    assert results.pwind_trajectory.shape[0] == 24
    assert results.pwind_trajectory.shape[1] == len(designed_system_mea.wind_caps)
    assert results.pthermal_trajectory.shape[0] == 24

    for attr in ("pimp", "pexp", "nuclear", "hydro", "other_renewables", "load", "month_of_hour"):
        s = getattr(results, attr)
        assert isinstance(s, pd.Series)
        assert len(s) == 24


# ---------------------------------------------------------------------------
# Real MEA smoke
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_baseline_dispatch_real_mea_24h(baseline_results_mea):
    res = baseline_results_mea
    assert res.solver_status == "optimal"
    assert res.objective_value == pytest.approx(res.objective_value)
    assert abs(res.objective_value) < 1e15


# ---------------------------------------------------------------------------
# FOM accounting (Z^B_FOM)
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_designed_system_carries_fom(designed_system_mea):
    ds = designed_system_mea

    # Storage: fom (USD/kW-yr) and cost_ratio match StorageData_2030.csv.
    for tech, spec in ds.storage_caps.items():
        assert "fom" in spec and isinstance(spec["fom"], float)
        assert "cost_ratio" in spec and isinstance(spec["cost_ratio"], float)
    if "Li-Ion" in ds.storage_caps:
        assert ds.storage_caps["Li-Ion"]["fom"] == pytest.approx(7.9)
        assert ds.storage_caps["Li-Ion"]["cost_ratio"] == pytest.approx(0.5)
    if "H2" in ds.storage_caps:
        assert ds.storage_caps["H2"]["fom"] == pytest.approx(46.0)
        assert ds.storage_caps["H2"]["cost_ratio"] == pytest.approx(0.325)

    # Thermal: fom present (0.0 in MEA inputs).
    for bu, spec in ds.thermal_caps.items():
        assert "fom" in spec and isinstance(spec["fom"], float)
        assert spec["fom"] == pytest.approx(0.0)

    # Solar / Wind: per-plant FOM_M dicts populated.
    assert ds.solar_fom and ds.wind_fom
    for pid in ds.solar_caps:
        assert pid in ds.solar_fom
        assert isinstance(ds.solar_fom[pid], float)
        assert ds.solar_fom[pid] == pytest.approx(18.0)
    for pid in ds.wind_caps:
        assert pid in ds.wind_fom
        assert isinstance(ds.wind_fom[pid], float)
        assert ds.wind_fom[pid] == pytest.approx(29.3)


@pytest.mark.integration
def test_cost_breakdown_reconciles(baseline_results_mea):
    cb = baseline_results_mea.cost_breakdown
    assert isinstance(cb, dict) and cb
    for key in (
        "thermal_var_USD",
        "storage_var_USD",
        "imports_USD",
        "exports_USD",
        "demand_charges_USD",
        "curtailment_USD",
        "fom_USD",
        "total_USD",
    ):
        assert key in cb
        assert isinstance(cb[key], float)

    # FOM > 0 in MEA (solar=18, wind=29.3, storage non-zero).
    assert cb["fom_USD"] > 0.0

    sum_components = (
        cb["thermal_var_USD"]
        + cb["storage_var_USD"]
        + cb["imports_USD"]
        - cb["exports_USD"]
        + cb["demand_charges_USD"]
        + cb["curtailment_USD"]
        + cb["fom_USD"]
    )
    assert sum_components == pytest.approx(cb["total_USD"], rel=1e-6, abs=1.0)
    assert cb["total_USD"] == pytest.approx(baseline_results_mea.objective_value)


@pytest.mark.integration
def test_fom_constant_independent_of_dispatch(designed_system_mea):
    _highs()
    tech = next(iter(designed_system_mea.storage_caps))
    m_a = build_baseline_dispatch(designed_system_mea, n_hours=N_HOURS)
    m_b = build_baseline_dispatch(
        designed_system_mea,
        n_hours=N_HOURS,
        min_soc_per_tech={tech: 0.5},
    )
    r_a = run_baseline_dispatch(m_a)
    r_b = run_baseline_dispatch(m_b)
    assert r_a.cost_breakdown["fom_USD"] == pytest.approx(
        r_b.cost_breakdown["fom_USD"], rel=1e-9
    )
