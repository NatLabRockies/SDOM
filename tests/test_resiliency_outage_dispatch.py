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
    # The baseline value is now seeded into the ``SOC_init`` boundary
    # parameter (representing SOC at the start of ``start_hour``), not
    # into a fixed ``SOC`` variable. The SOC dynamics constraint covers
    # ``start_hour`` and links Pcha[start_hour]/Pdis[start_hour] to
    # SOC[start_hour], so ``SOC[s, start_hour]`` is a free variable.
    assert not model.storage.SOC["Li-Ion", 5].is_fixed()
    assert pyo.value(model.storage.SOC_init["Li-Ion"]) == pytest.approx(30.0)
    # SOC dynamics now covers the anchor hour as well.
    assert ("Li-Ion", 5) in model.storage.soc_dynamics


def test_outage_soc_dynamics_links_anchor_hour_charge_discharge():
    """Regression: previously ``Pcha[s, h]`` / ``Pdis[s, h]`` had no SOC
    equation for non-outaged storage because ``_soc_dynamics`` skipped
    ``t == start_hour`` while ``SOC[s, h]`` was fixed via ``Var.fix``.

    Now the constraint is generated for every hour, including
    ``start_hour``, with ``SOC_init[s]`` as the prior state.
    """
    n = 24
    ds = _make_designed_system(n=n)
    br = _make_baseline_results(ds, soc_value=20.0)
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        # Outage the *thermal* assets; storage is not outaged, so
        # delta_storage[s, t] == 1 everywhere and Pcha/Pdis at the
        # anchor hour are *not* clamped to zero by capacity bounds.
        outaged_assets={"balancing_units": "all"},
    )
    start = 3
    model = build_outage_dispatch(
        br,
        start_hour=start,
        outage_spec=spec,
        designed_system=ds,
        n_hours=n,
    )
    # The SOC dynamics constraint must exist for the anchor hour.
    assert ("Li-Ion", start) in model.storage.soc_dynamics
    # Solve and check that the anchor-hour SOC equation actually holds.
    solver = _highs()
    res = solver.solve(model)
    assert str(res.solver.termination_condition) == "optimal"
    soc_init = pyo.value(model.storage.SOC_init["Li-Ion"])
    soc_h = pyo.value(model.storage.SOC["Li-Ion", start])
    pcha_h = pyo.value(model.storage.Pcha["Li-Ion", start])
    pdis_h = pyo.value(model.storage.Pdis["Li-Ion", start])
    eta_ch = pyo.value(model.storage.eta_ch["Li-Ion"])
    eta_dis = pyo.value(model.storage.eta_dis["Li-Ion"])
    expected = soc_init + eta_ch * pcha_h - pdis_h / eta_dis
    assert soc_h == pytest.approx(expected, abs=1e-6)


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


# ---------------------------------------------------------------------------
# SOC recovery-target slack (#68)
# ---------------------------------------------------------------------------
def test_outage_recovery_soc_slack_default_value_and_metadata():
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
    assert model._sdom_outage_meta["soc_slack_penalty"] == pytest.approx(1_000.0)
    assert hasattr(model, "recovery_soc_slack")
    slack = model.recovery_soc_slack
    assert isinstance(slack, pyo.Var)
    assert slack["Li-Ion"].domain is pyo.NonNegativeReals


def test_outage_recovery_soc_slack_penalty_override():
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
        soc_slack_penalty=2_500.0,
    )
    assert model._sdom_outage_meta["soc_slack_penalty"] == pytest.approx(2_500.0)


def test_outage_recovery_soc_slack_penalty_negative_rejected():
    n = 24
    ds = _make_designed_system(n=n)
    br = _make_baseline_results(ds, soc_value=20.0)
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"balancing_units": "all"},
    )
    with pytest.raises(ValueError, match="soc_slack_penalty must be non-negative"):
        build_outage_dispatch(
            br,
            start_hour=1,
            outage_spec=spec,
            designed_system=ds,
            n_hours=n,
            soc_slack_penalty=-1.0,
        )


def test_outage_recovery_target_constraint_includes_slack():
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
    # The recovery_target constraint for Li-Ion must mention the new slack var.
    con = model.recovery_target["Li-Ion"]
    body_str = str(con.expr)
    assert "recovery_soc_slack[Li-Ion]" in body_str


def test_outage_recovery_soc_slack_resolves_unreachable_target():
    solver = _highs()
    n = 24
    ds = _make_designed_system(n=n)
    br = _make_baseline_results(ds, soc_value=0.0)
    # Recovery window for start_hour=1, duration=4, recovery=2 ends at hour 6.
    # With both balancing_units and storage outaged, storage can only charge
    # during recovery hours 5..6 (Cap_Pch=10 -> max 20 MWh), so a 40 MWh
    # recovery target is unreachable and slack must absorb ~20 MWh.
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=2,
        outaged_assets={"balancing_units": "all", "storage": "all"},
        min_soc_recovery={"Li-Ion": 1.0},
    )
    model = build_outage_dispatch(
        br,
        start_hour=1,
        outage_spec=spec,
        designed_system=ds,
        n_hours=n,
        soc_slack_penalty=1_000.0,
    )
    result = solver.solve(model)
    assert str(result.solver.termination_condition).lower() == "optimal"
    slack_value = pyo.value(model.recovery_soc_slack["Li-Ion"])
    assert slack_value > 10.0  # ~20 MWh expected; well above numerical noise


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


# ---------------------------------------------------------------------------
# Prorated fixed-O&M cost in objective
# ---------------------------------------------------------------------------
def test_outage_fom_cost_expr_zero_when_designed_system_has_no_fom():
    ds = _make_designed_system(n=24)
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
        n_hours=24,
    )
    assert pyo.value(model.fom_cost_expr) == pytest.approx(0.0, abs=1e-9)
    assert model._sdom_outage_meta["fom_cost_USD"] == pytest.approx(0.0, abs=1e-9)
    assert model._sdom_outage_meta["horizon_hours"] == 8


def test_outage_fom_cost_expr_prorated_storage_thermal_solar_wind():
    from sdom.constants import MW_TO_KW

    n = 8760
    idx = pd.RangeIndex(start=1, stop=n + 1, name="Hour")
    storage = {
        "Li-Ion": {
            "Cap_Pch": 10.0,
            "Cap_Pdis": 12.0,
            "Cap_E": 40.0,
            "eta_ch": 1.0,
            "eta_dis": 1.0,
            "soc_min_frac": 0.0,
            "vom": 0.0,
            "fom": 5.0,
            "cost_ratio": 0.5,
        }
    }
    thermal = {
        "83": {"capacity_MW": 100.0, "var_cost": 30.0, "fom": 7.0},
    }
    ds = DesignedSystem(
        storage_caps=storage,
        thermal_caps=thermal,
        solar_caps={"pv_a": 50.0},
        wind_caps={"wind_a": 20.0},
        solar_fom={"pv_a": 11.0},
        wind_fom={"wind_a": 13.0},
        load=pd.Series([50.0] * n, index=idx),
        cf_solar=pd.DataFrame({"pv_a": [0.0] * n}, index=idx),
        cf_wind=pd.DataFrame({"wind_a": [0.0] * n}, index=idx),
        nuclear=pd.Series([0.0] * n, index=idx),
        hydro=pd.Series([0.0] * n, index=idx),
        other_renewables=pd.Series([0.0] * n, index=idx),
        import_cap=pd.Series([100.0] * n, index=idx),
        import_price=pd.Series([50.0] * n, index=idx),
        export_cap=pd.Series([0.0] * n, index=idx),
        export_price=pd.Series([0.0] * n, index=idx),
        phi_fix_t=pd.Series([0.0] * n, index=idx),
        phi_var_t=pd.Series([0.0] * n, index=idx),
        month_of_hour=pd.Series([1] * n, index=idx),
    )
    br = _make_baseline_results(ds, soc_value=20.0)
    spec = OutageSpec(
        duration_hours=48,
        recovery_hours=48,
        outaged_assets={"balancing_units": "all"},
    )
    model = build_outage_dispatch(
        br,
        start_hour=1,
        outage_spec=spec,
        designed_system=ds,
        n_hours=n,
    )
    # Horizon = duration + recovery = 96 (no clipping at start_hour=1).
    horizon_hours = 96
    frac = horizon_hours / 8760.0
    expected_annual = (
        MW_TO_KW * 5.0 * (0.5 * 10.0 + 0.5 * 12.0)  # storage
        + MW_TO_KW * 7.0 * 100.0  # thermal
        + MW_TO_KW * 11.0 * 50.0  # solar
        + MW_TO_KW * 13.0 * 20.0  # wind
    )
    expected_outage = expected_annual * frac
    assert model._sdom_outage_meta["horizon_hours"] == horizon_hours
    assert pyo.value(model.fom_cost_expr) == pytest.approx(expected_outage, rel=1e-12)
    assert model._sdom_outage_meta["fom_cost_USD"] == pytest.approx(
        expected_outage, rel=1e-12
    )


def test_outage_fom_cost_expr_prorates_with_clipped_horizon():
    from sdom.constants import MW_TO_KW

    n = 24
    idx = pd.RangeIndex(start=1, stop=n + 1, name="Hour")
    thermal = {"83": {"capacity_MW": 50.0, "var_cost": 30.0, "fom": 4.0}}
    ds = DesignedSystem(
        storage_caps={},
        thermal_caps=thermal,
        solar_caps={},
        wind_caps={},
        load=pd.Series([10.0] * n, index=idx),
        cf_solar=pd.DataFrame(index=idx),
        cf_wind=pd.DataFrame(index=idx),
        nuclear=pd.Series([0.0] * n, index=idx),
        hydro=pd.Series([0.0] * n, index=idx),
        other_renewables=pd.Series([0.0] * n, index=idx),
        import_cap=pd.Series([100.0] * n, index=idx),
        import_price=pd.Series([50.0] * n, index=idx),
        export_cap=pd.Series([0.0] * n, index=idx),
        export_price=pd.Series([0.0] * n, index=idx),
        phi_fix_t=pd.Series([0.0] * n, index=idx),
        phi_var_t=pd.Series([0.0] * n, index=idx),
        month_of_hour=pd.Series([1] * n, index=idx),
    )
    br = _make_baseline_results(ds, soc_value=0.0)
    spec = OutageSpec(
        duration_hours=10,
        recovery_hours=10,
        outaged_assets={},
    )
    # start_hour=20 -> raw horizon end = 20+10+10-1 = 39, clipped to n_hours=24,
    # so horizon_hours = 24 - 20 + 1 = 5.
    model = build_outage_dispatch(
        br,
        start_hour=20,
        outage_spec=spec,
        designed_system=ds,
        n_hours=n,
    )
    horizon_hours = 5
    expected_annual = MW_TO_KW * 4.0 * 50.0
    expected_outage = expected_annual * (horizon_hours / 8760.0)
    assert model._sdom_outage_meta["horizon_hours"] == horizon_hours
    assert pyo.value(model.fom_cost_expr) == pytest.approx(expected_outage, rel=1e-12)


