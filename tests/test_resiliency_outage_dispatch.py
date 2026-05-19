"""Phase 4 / Deliverable B: tests for ``build_outage_dispatch``."""

from __future__ import annotations

import pandas as pd
import pyomo.environ as pyo
import pytest

from sdom.resiliency import (
    BaselineDispatchResults,
    DesignedSystem,
    OutageSpec,
    build_outage_dispatch,
)


# ---------------------------------------------------------------------------
# Helpers
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


def _make_designed_system(
    *,
    n=24,
    storage=None,
    thermal=None,
    hydro_value=0.0,
    nuclear_value=0.0,
    other_renewables_value=0.0,
    import_cap_value=100.0,
    load_value=50.0,
):
    idx = pd.RangeIndex(start=1, stop=n + 1, name="Hour")
    if storage is None:
        storage = {
            "Li-Ion": {
                "Cap_Pch": 10.0,
                "Cap_Pdis": 10.0,
                "Cap_E": 40.0,
                "eta_ch": 1.0,
                "eta_dis": 1.0,
                "soc_min_frac": 0.0,
                "vom": 0.0,
            }
        }
    if thermal is None:
        thermal = {"83": {"capacity_MW": 100.0, "var_cost": 30.0}}
    return DesignedSystem(
        storage_caps=storage,
        thermal_caps=thermal,
        solar_caps={},
        wind_caps={},
        load=pd.Series([load_value] * n, index=idx),
        cf_solar=pd.DataFrame(index=idx),
        cf_wind=pd.DataFrame(index=idx),
        nuclear=pd.Series([nuclear_value] * n, index=idx),
        hydro=pd.Series([hydro_value] * n, index=idx),
        other_renewables=pd.Series([other_renewables_value] * n, index=idx),
        import_cap=pd.Series([import_cap_value] * n, index=idx),
        import_price=pd.Series([50.0] * n, index=idx),
        export_cap=pd.Series([0.0] * n, index=idx),
        export_price=pd.Series([0.0] * n, index=idx),
        phi_fix_t=pd.Series([0.0] * n, index=idx),
        phi_var_t=pd.Series([0.0] * n, index=idx),
        month_of_hour=pd.Series([1] * n, index=idx),
    )


def _make_baseline_results(designed_system, *, soc_value=0.0):
    n = len(designed_system.load)
    idx = pd.RangeIndex(start=1, stop=n + 1, name="Hour")
    techs = list(designed_system.storage_caps.keys())
    soc = pd.DataFrame(
        {tech: [soc_value] * n for tech in techs},
        index=idx,
    )
    return BaselineDispatchResults(
        soc_trajectory=soc,
        objective_value=0.0,
        solver_status="optimal",
        metadata={"designed_system": designed_system},
    )


# ---------------------------------------------------------------------------
# Horizon clipping
# ---------------------------------------------------------------------------
def test_build_outage_dispatch_horizon_clipped():
    ds = _make_designed_system(n=24)
    br = _make_baseline_results(ds, soc_value=20.0)
    spec = OutageSpec(
        duration_hours=24,
        recovery_hours=24,
        outaged_assets={"balancing_units": "all"},
    )
    model = build_outage_dispatch(
        br,
        start_hour=20,
        outage_spec=spec,
        designed_system=ds,
        n_hours=24,
    )
    assert list(model.h) == [20, 21, 22, 23, 24]
    assert hasattr(model.imports, "Pimp")
    assert not hasattr(model.imports, "D_fix")
    assert not hasattr(model.imports, "D_var")
    assert hasattr(model, "u")
    for t in model.h:
        assert model.u[t].domain is pyo.NonNegativeReals


def test_build_outage_dispatch_full_horizon_no_clipping():
    ds = _make_designed_system(n=8760)
    br = _make_baseline_results(ds, soc_value=20.0)
    spec = OutageSpec(
        duration_hours=24,
        recovery_hours=24,
        outaged_assets={"balancing_units": "all"},
    )
    model = build_outage_dispatch(
        br,
        start_hour=100,
        outage_spec=spec,
        designed_system=ds,
        n_hours=8760,
    )
    assert list(model.h) == list(range(100, 148))


# ---------------------------------------------------------------------------
# Solving / slack behaviour
# ---------------------------------------------------------------------------
def test_outage_full_blackout_forces_slack():
    solver = _highs()
    n = 8
    ds = _make_designed_system(
        n=n,
        storage={
            "Li-Ion": {
                "Cap_Pch": 10.0,
                "Cap_Pdis": 10.0,
                "Cap_E": 10.0,
                "eta_ch": 1.0,
                "eta_dis": 1.0,
                "soc_min_frac": 0.0,
                "vom": 0.0,
            }
        },
        load_value=50.0,
        import_cap_value=100.0,
    )
    br = _make_baseline_results(ds, soc_value=0.0)
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"balancing_units": "all", "imports": "all"},
    )
    model = build_outage_dispatch(
        br,
        start_hour=1,
        outage_spec=spec,
        designed_system=ds,
        n_hours=n,
    )
    res = solver.solve(model)
    assert str(res.solver.termination_condition) == "optimal"
    eue = sum(pyo.value(model.u[t]) for t in model.h)
    assert eue > 0
    # During outage hours 1..4 the only sources are storage (Pdis<=Cap_Pdis=10
    # but SOC starts at 0 and there is nothing to charge from) and slack.
    for t in range(1, 5):
        thermal_dispatch = sum(
            pyo.value(model.thermal.Pthermal[b, t])
            for b in model.thermal.B
        )
        imports_dispatch = pyo.value(model.imports.Pimp[t])
        assert thermal_dispatch == pytest.approx(0.0, abs=1e-6)
        assert imports_dispatch == pytest.approx(0.0, abs=1e-6)
        assert pyo.value(model.u[t]) > 0


def test_outage_recovery_window_full_capacity():
    n = 8
    ds = _make_designed_system(n=n)
    br = _make_baseline_results(ds, soc_value=20.0)
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"balancing_units": "all"},
    )
    model = build_outage_dispatch(
        br,
        start_hour=1,
        outage_spec=spec,
        designed_system=ds,
        n_hours=n,
    )
    cap = ds.thermal_caps["83"]["capacity_MW"]
    for t in range(1, 5):
        assert model.thermal.Pthermal["83", t].ub == pytest.approx(0.0)
    for t in range(5, 9):
        assert model.thermal.Pthermal["83", t].ub == pytest.approx(cap)


def test_outage_must_run_derating():
    solver = _highs()
    n = 24
    ds = _make_designed_system(
        n=n,
        thermal={"83": {"capacity_MW": 200.0, "var_cost": 30.0}},
        hydro_value=100.0,
        load_value=100.0,
    )
    br = _make_baseline_results(ds, soc_value=20.0)
    spec = OutageSpec(
        duration_hours=2,
        recovery_hours=2,
        outaged_assets={"hydro": "all"},
    )
    model = build_outage_dispatch(
        br,
        start_hour=1,
        outage_spec=spec,
        designed_system=ds,
        n_hours=n,
    )
    # Outage hours 1..2: hydro effective = 0
    for t in range(1, 3):
        assert pyo.value(model.hydro_eff_param[t]) == pytest.approx(0.0)
    # Recovery hours 3..4: hydro effective = 100
    for t in range(3, 5):
        assert pyo.value(model.hydro_eff_param[t]) == pytest.approx(100.0)

    res = solver.solve(model)
    assert str(res.solver.termination_condition) == "optimal"


def test_outage_initial_soc_seeded_from_baseline():
    n = 24
    ds = _make_designed_system(n=n)
    br = _make_baseline_results(ds, soc_value=0.0)
    # Patch the baseline SOC for hour 5 to 30 MWh.
    br.soc_trajectory.loc[5, "Li-Ion"] = 30.0
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"balancing_units": "all"},
    )
    model = build_outage_dispatch(
        br,
        start_hour=5,
        outage_spec=spec,
        designed_system=ds,
        n_hours=n,
    )
    assert model.storage.SOC["Li-Ion", 5].is_fixed()
    assert pyo.value(model.storage.SOC["Li-Ion", 5]) == pytest.approx(30.0)


def test_outage_recovery_target_default_baseline():
    n = 24
    ds = _make_designed_system(n=n)
    br = _make_baseline_results(ds, soc_value=0.0)
    # End of recovery window for start_hour=1, duration=4, recovery=4 is hour 8.
    br.soc_trajectory.loc[8, "Li-Ion"] = 25.0
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"balancing_units": "all"},
    )
    model = build_outage_dispatch(
        br,
        start_hour=1,
        outage_spec=spec,
        designed_system=ds,
        n_hours=n,
    )
    targets = model._sdom_outage_meta["recovery_target_MWh"]
    assert targets["Li-Ion"] == pytest.approx(25.0)


def test_outage_recovery_target_user_override():
    n = 24
    ds = _make_designed_system(n=n)
    br = _make_baseline_results(ds, soc_value=0.0)
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"balancing_units": "all"},
        min_soc_recovery={"Li-Ion": 0.7},
    )
    model = build_outage_dispatch(
        br,
        start_hour=1,
        outage_spec=spec,
        designed_system=ds,
        n_hours=n,
    )
    cap_e = ds.storage_caps["Li-Ion"]["Cap_E"]
    targets = model._sdom_outage_meta["recovery_target_MWh"]
    assert targets["Li-Ion"] == pytest.approx(0.7 * cap_e)


def test_outage_demand_charges_excluded_by_default():
    n = 24
    ds = _make_designed_system(n=n)
    br = _make_baseline_results(ds, soc_value=20.0)
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"balancing_units": "all"},
    )
    model = build_outage_dispatch(
        br,
        start_hour=1,
        outage_spec=spec,
        designed_system=ds,
        n_hours=n,
    )
    assert not hasattr(model.imports, "D_fix")
    assert not hasattr(model.imports, "D_var")


def test_outage_solves_feasible_zero_outage_equivalence():
    solver = _highs()
    n = 24
    ds = _make_designed_system(n=n)
    br = _make_baseline_results(ds, soc_value=20.0)
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={},
    )
    model = build_outage_dispatch(
        br,
        start_hour=1,
        outage_spec=spec,
        designed_system=ds,
        n_hours=n,
    )
    res = solver.solve(model)
    assert str(res.solver.termination_condition) == "optimal"
    for t in model.h:
        assert pyo.value(model.u[t]) == pytest.approx(0.0, abs=1e-6)
