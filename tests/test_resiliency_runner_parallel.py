"""Phase 5 / Deliverable: multiprocess tests for ``run_resiliency_evaluation``.

These tests verify that the ``ProcessPoolExecutor``-backed parallel path
produces identical per-hour metrics to the serial (in-process) path, and
that ``n_workers=None`` resolves to ``max(1, os.cpu_count() - 1)``.
"""

from __future__ import annotations

import os

import pandas as pd
import pyomo.environ as pyo
import pytest

from sdom.resiliency import (
    BaselineDispatchResults,
    DesignedSystem,
    OutageSpec,
    run_resiliency_evaluation,
)


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
    n=12,
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
                "Cap_E": 20.0,
                "eta_ch": 1.0,
                "eta_dis": 1.0,
                "soc_min_frac": 0.0,
                "vom": 0.0,
            }
        }
    if thermal is None:
        thermal = {"83": {"capacity_MW": 30.0, "var_cost": 30.0}}
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


def _make_baseline_results(designed_system, *, soc_value=10.0):
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
# Parity test: parallel vs serial
# ---------------------------------------------------------------------------
def test_n_workers_2_matches_n_workers_1():
    # Force EUE>0 on some hours: thermal cap=30, imports outaged, load=50.
    # Storage (Cap_Pdis=10, soc starts at 10) covers a few hours, after
    # which slack kicks in. This makes the test non-trivial.
    ds = _make_designed_system(
        n=12,
        thermal={"83": {"capacity_MW": 30.0, "var_cost": 30.0}},
        load_value=50.0,
        import_cap_value=100.0,
    )
    br = _make_baseline_results(ds, soc_value=10.0)
    spec = OutageSpec(
        duration_hours=3,
        recovery_hours=2,
        outaged_assets={"imports": "all"},
    )
    hours = list(range(1, 7))

    res_serial = run_resiliency_evaluation(
        br,
        outage_spec=spec,
        hours=hours,
        n_hours=12,
        n_workers=1,
    )
    res_parallel = run_resiliency_evaluation(
        br,
        outage_spec=spec,
        hours=hours,
        n_hours=12,
        n_workers=2,
    )

    assert res_serial.metadata["n_workers_used"] == 1
    assert res_parallel.metadata["n_workers_used"] == 2

    # Verify the comparison is meaningful: at least one hour has EUE > 0.
    assert (res_serial.per_hour["EUE"] > 0).any()

    cols = ["EUE", "USE_hours", "max_unserved_MW", "objective_value"]
    for col in cols:
        a = res_serial.per_hour[col].astype(float).to_numpy()
        b = res_parallel.per_hour[col].astype(float).to_numpy()
        assert a == pytest.approx(b, abs=1e-6), (
            f"column {col} differs:\nserial={a}\nparallel={b}"
        )


# ---------------------------------------------------------------------------
# n_workers default resolution
# ---------------------------------------------------------------------------
def test_n_workers_default_chooses_cpu_count_minus_one(monkeypatch):
    ds = _make_designed_system(n=12)
    br = _make_baseline_results(ds, soc_value=10.0)
    spec = OutageSpec(
        duration_hours=1,
        recovery_hours=1,
        outaged_assets={},
    )
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    res = run_resiliency_evaluation(
        br,
        outage_spec=spec,
        hours=[1, 2, 3],
        n_hours=12,
        n_workers=None,
    )
    assert res.metadata["n_workers_used"] == 3


def test_n_workers_default_floors_to_one(monkeypatch):
    ds = _make_designed_system(n=12)
    br = _make_baseline_results(ds, soc_value=10.0)
    spec = OutageSpec(
        duration_hours=1,
        recovery_hours=1,
        outaged_assets={},
    )
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    res = run_resiliency_evaluation(
        br,
        outage_spec=spec,
        hours=[1, 2],
        n_hours=12,
        n_workers=None,
    )
    assert res.metadata["n_workers_used"] == 1
