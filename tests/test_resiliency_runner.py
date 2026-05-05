"""Phase 5 / Deliverable: single-process tests for ``run_resiliency_evaluation``.

These tests exercise the orchestrator on the serial path (``n_workers=1``)
so they can monkeypatch in-process attributes (e.g. to simulate per-hour
solver failures) and avoid the cost of spawning subprocess workers.
"""

from __future__ import annotations

import pandas as pd
import pyomo.environ as pyo
import pytest

from sdom.resiliency import (
    BaselineDispatchResults,
    DesignedSystem,
    OutageSpec,
    ResiliencyResults,
    run_resiliency_evaluation,
)
from sdom.resiliency import runner as runner_module


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------
def _highs_available() -> bool:
    for name in ("appsi_highs", "highs"):
        try:
            s = pyo.SolverFactory(name)
            if s is not None and s.available(exception_flag=False):
                return True
        except Exception:
            continue
    return False


pytestmark = pytest.mark.skipif(
    not _highs_available(), reason="HiGHS solver not available"
)


def _make_designed_system(
    *,
    n=24,
    storage=None,
    thermal=None,
    load_value=50.0,
    import_cap_value=100.0,
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
        nuclear=pd.Series([0.0] * n, index=idx),
        hydro=pd.Series([0.0] * n, index=idx),
        other_renewables=pd.Series([0.0] * n, index=idx),
        import_cap=pd.Series([import_cap_value] * n, index=idx),
        import_price=pd.Series([50.0] * n, index=idx),
        export_cap=pd.Series([0.0] * n, index=idx),
        export_price=pd.Series([0.0] * n, index=idx),
        phi_fix_t=pd.Series([0.0] * n, index=idx),
        phi_var_t=pd.Series([0.0] * n, index=idx),
        month_of_hour=pd.Series([1] * n, index=idx),
    )


def _make_baseline_results(designed_system, *, soc_value=20.0, attach_ds=True):
    n = len(designed_system.load)
    idx = pd.RangeIndex(start=1, stop=n + 1, name="Hour")
    techs = list(designed_system.storage_caps.keys())
    soc = pd.DataFrame(
        {tech: [soc_value] * n for tech in techs},
        index=idx,
    )
    metadata = {"designed_system": designed_system} if attach_ds else {}
    return BaselineDispatchResults(
        soc_trajectory=soc,
        objective_value=0.0,
        solver_status="optimal",
        metadata=metadata,
    )


@pytest.fixture()
def small_system():
    ds = _make_designed_system(n=24)
    br = _make_baseline_results(ds, soc_value=20.0)
    return ds, br


# ---------------------------------------------------------------------------
# Basic API / hour selection
# ---------------------------------------------------------------------------
def test_run_serial_n_workers_1_returns_results_per_hour(small_system):
    ds, br = small_system
    spec = OutageSpec(
        duration_hours=2,
        recovery_hours=2,
        outaged_assets={"balancing_units": "all"},
    )
    res = run_resiliency_evaluation(
        br,
        outage_spec=spec,
        hours=[1, 5, 10],
        n_hours=24,
        n_workers=1,
    )
    assert isinstance(res, ResiliencyResults)
    assert list(res.per_hour.index) == [1, 5, 10]
    assert res.metadata["n_workers_used"] == 1


def test_run_serial_default_hours_is_full_horizon(small_system):
    ds, br = small_system
    spec = OutageSpec(
        duration_hours=1,
        recovery_hours=1,
        outaged_assets={},
    )
    res = run_resiliency_evaluation(
        br,
        outage_spec=spec,
        hours=None,
        n_hours=24,
        n_workers=1,
    )
    assert list(res.per_hour.index) == list(range(1, 25))
    assert len(res.per_hour) == 24


# ---------------------------------------------------------------------------
# EUE behaviour
# ---------------------------------------------------------------------------
def test_eue_zero_when_no_outage(small_system):
    ds, br = small_system
    spec = OutageSpec(
        duration_hours=2,
        recovery_hours=2,
        outaged_assets={},
    )
    res = run_resiliency_evaluation(
        br,
        outage_spec=spec,
        hours=[1, 4, 8, 12],
        n_hours=24,
        n_workers=1,
    )
    for h in res.per_hour.index:
        assert float(res.per_hour.loc[h, "EUE"]) == pytest.approx(0.0, abs=1e-6)
        assert int(res.per_hour.loc[h, "USE_hours"]) == 0


def test_eue_positive_when_full_blackout():
    # Storage starts empty, only sources are thermal and imports - both
    # outaged. Slack must cover the full load during the outage window.
    ds = _make_designed_system(
        n=8,
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
    res = run_resiliency_evaluation(
        br,
        outage_spec=spec,
        hours=[1, 2, 3],
        n_hours=8,
        n_workers=1,
    )
    eues = res.per_hour["EUE"].tolist()
    assert all(eue > 0 for eue in eues)
    assert res.eue_total() > 0


# ---------------------------------------------------------------------------
# Truncation flag at year-end
# ---------------------------------------------------------------------------
def test_truncated_flag_set_at_year_end(small_system):
    ds, br = small_system
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"balancing_units": "all"},
    )
    res = run_resiliency_evaluation(
        br,
        outage_spec=spec,
        hours=[10, 22],
        n_hours=24,
        n_workers=1,
    )
    assert bool(res.per_hour.loc[10, "truncated"]) is False
    assert bool(res.per_hour.loc[22, "truncated"]) is True


# ---------------------------------------------------------------------------
# Failure isolation (serial path so monkeypatching works in-process)
# ---------------------------------------------------------------------------
def test_worker_failure_isolated(monkeypatch, small_system):
    ds, br = small_system
    spec = OutageSpec(
        duration_hours=2,
        recovery_hours=2,
        outaged_assets={"balancing_units": "all"},
    )

    real_builder = runner_module._build_outage_dispatch

    def maybe_failing_builder(baseline_results, *, start_hour, **kwargs):
        if int(start_hour) == 5:
            raise RuntimeError("simulated solver failure at start_hour=5")
        return real_builder(baseline_results, start_hour=start_hour, **kwargs)

    monkeypatch.setattr(
        runner_module, "_build_outage_dispatch", maybe_failing_builder
    )

    res = run_resiliency_evaluation(
        br,
        outage_spec=spec,
        hours=[1, 5, 10],
        n_hours=24,
        n_workers=1,
    )

    assert res.per_hour.loc[5, "solver_status"] == "error"
    assert "simulated solver failure" in str(res.per_hour.loc[5, "error_message"])
    # Other hours still produced a normal record.
    for h in (1, 10):
        assert res.per_hour.loc[h, "solver_status"] != "error"
        assert res.per_hour.loc[h, "error_message"] == ""


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------
def test_results_ordered_by_start_hour(small_system):
    ds, br = small_system
    spec = OutageSpec(
        duration_hours=1,
        recovery_hours=1,
        outaged_assets={},
    )
    res = run_resiliency_evaluation(
        br,
        outage_spec=spec,
        hours=[10, 5, 20, 1],
        n_hours=24,
        n_workers=1,
    )
    hours_col = res.to_dataframe()["hour"].tolist()
    assert hours_col == [1, 5, 10, 20]


# ---------------------------------------------------------------------------
# designed_system resolution
# ---------------------------------------------------------------------------
def test_run_with_explicit_designed_system_kwarg(small_system):
    ds, br = small_system
    # baseline_results.metadata already contains a different DesignedSystem
    # to force a clear precedence test.
    other = _make_designed_system(n=24, load_value=999.0)
    br_with_other = _make_baseline_results(ds, soc_value=20.0)
    br_with_other.metadata["designed_system"] = other
    spec = OutageSpec(
        duration_hours=1,
        recovery_hours=1,
        outaged_assets={},
    )
    res = run_resiliency_evaluation(
        br_with_other,
        outage_spec=spec,
        designed_system=ds,
        hours=[1, 2],
        n_hours=24,
        n_workers=1,
    )
    # If the kwarg won, the LP runs against the small load=50 system (which
    # is feasible without slack). If the metadata DS had won, load=999 would
    # exceed the thermal cap (100) and produce EUE>0.
    assert res.per_hour.loc[1, "EUE"] == pytest.approx(0.0, abs=1e-6)
    assert res.per_hour.loc[2, "EUE"] == pytest.approx(0.0, abs=1e-6)
    assert res.per_hour.loc[1, "solver_status"] == "optimal"


def test_run_without_designed_system_anywhere_raises(small_system):
    ds, _ = small_system
    br_empty = _make_baseline_results(ds, soc_value=20.0, attach_ds=False)
    spec = OutageSpec(
        duration_hours=1,
        recovery_hours=1,
        outaged_assets={},
    )
    with pytest.raises(ValueError, match="designed_system"):
        run_resiliency_evaluation(
            br_empty,
            outage_spec=spec,
            hours=[1],
            n_hours=24,
            n_workers=1,
        )
