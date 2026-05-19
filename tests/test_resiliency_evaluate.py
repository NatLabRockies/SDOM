"""Phase 7 / Deliverable A tests for ``evaluate_resiliency``.

The synthetic tests monkeypatch :func:`sdom.resiliency.load_designed_system`
inside the ``evaluate`` module so they do not need to materialise the full
set of snapshot + previous-stage CSVs that the loader requires; the real
end-to-end CSV path is covered by ``tests/test_resiliency_integration.py``.
"""

from __future__ import annotations

import pandas as pd
import pyomo.environ as pyo
import pytest

from sdom.resiliency import (
    DesignedSystem,
    OutageSpec,
    ResiliencyResults,
    evaluate_resiliency,
)
from sdom.resiliency import evaluate as evaluate_module


# ---------------------------------------------------------------------------
# Solver gate
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


# ---------------------------------------------------------------------------
# Synthetic DesignedSystem
# ---------------------------------------------------------------------------
def _make_designed_system(n: int = 24) -> DesignedSystem:
    idx = pd.RangeIndex(start=1, stop=n + 1, name="Hour")
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
    thermal = {"83": {"capacity_MW": 100.0, "var_cost": 30.0}}
    return DesignedSystem(
        storage_caps=storage,
        thermal_caps=thermal,
        solar_caps={},
        wind_caps={},
        load=pd.Series([50.0] * n, index=idx),
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


@pytest.fixture
def patched_loader(monkeypatch):
    """Patch ``load_designed_system`` inside ``evaluate`` to return a synthetic system."""
    ds = _make_designed_system(n=24)

    def _fake_loader(snapshot_dir, *, inputs_dir, year=2030, scenario_id=1,
                    formulation_overrides=None):
        # Stash call args for assertions if needed.
        _fake_loader.calls.append(
            dict(
                snapshot_dir=snapshot_dir,
                inputs_dir=inputs_dir,
                year=year,
                scenario_id=scenario_id,
                formulation_overrides=formulation_overrides,
            )
        )
        return ds

    _fake_loader.calls = []
    monkeypatch.setattr(evaluate_module, "load_designed_system", _fake_loader)
    return _fake_loader


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_evaluate_resiliency_synthetic(tmp_path, patched_loader):
    snapshot_dir = tmp_path / "snapshot"
    inputs_dir = tmp_path / "inputs"
    snapshot_dir.mkdir()
    inputs_dir.mkdir()

    spec = OutageSpec(
        duration_hours=2,
        recovery_hours=2,
        outaged_assets={"balancing_units": "all"},
    )
    results = evaluate_resiliency(
        snapshot_dir=snapshot_dir,
        inputs_dir=inputs_dir,
        outage_spec=spec,
        year=2030,
        scenario_id=1,
        n_hours=24,
        n_workers=1,
        solver="highs",
    )

    assert isinstance(results, ResiliencyResults)
    assert len(results.per_hour) == 24
    assert results.metadata["n_hours"] == 24
    assert results.metadata["solver"] == "highs"
    assert results.metadata.get("outage_spec") is not None
    # The patched loader should have been invoked with our paths.
    assert patched_loader.calls, "load_designed_system was not called"
    assert patched_loader.calls[0]["snapshot_dir"] == snapshot_dir
    assert patched_loader.calls[0]["inputs_dir"] == inputs_dir


def test_evaluate_resiliency_passes_through_kwargs(tmp_path, monkeypatch):
    snapshot_dir = tmp_path / "snapshot"
    inputs_dir = tmp_path / "inputs"
    snapshot_dir.mkdir()
    inputs_dir.mkdir()
    ds = _make_designed_system(n=24)

    captured = {}

    def fake_loader(snapshot_dir, *, inputs_dir, year=2030, scenario_id=1,
                    formulation_overrides=None):
        captured["loader"] = dict(
            snapshot_dir=snapshot_dir,
            inputs_dir=inputs_dir,
            year=year,
            scenario_id=scenario_id,
            formulation_overrides=formulation_overrides,
        )
        return ds

    real_build = evaluate_module.build_baseline_dispatch
    real_run_baseline = evaluate_module.run_baseline_dispatch
    real_run_eval = evaluate_module.run_resiliency_evaluation

    def fake_build(designed_system, *, n_hours=8760, min_soc_per_tech=None,
                    curtailment_penalty=0.0, formulation_overrides=None,
                    model_name="SDOM_BaselineDispatch", profile=False):
        captured["build"] = dict(
            n_hours=n_hours,
            min_soc_per_tech=min_soc_per_tech,
            curtailment_penalty=curtailment_penalty,
            profile=profile,
        )
        return real_build(
            designed_system,
            n_hours=n_hours,
            min_soc_per_tech=min_soc_per_tech,
            curtailment_penalty=curtailment_penalty,
            profile=profile,
        )

    def fake_run_baseline(model, *, solver="highs", solver_options=None, tee=False, profile=False):
        captured["run_baseline"] = dict(
            solver=solver, solver_options=solver_options, profile=profile,
        )
        return real_run_baseline(model, solver=solver, solver_options=solver_options, tee=tee, profile=profile)

    def fake_run_eval(baseline_results, *, outage_spec, designed_system=None,
                       hours=None, slack_penalty=10_000.0, curtailment_penalty=0.0,
                       min_soc_per_tech=None, n_hours=8760, n_workers=None,
                       solver="highs", solver_options=None, profile_outages=False):
        captured["run_eval"] = dict(
            slack_penalty=slack_penalty,
            curtailment_penalty=curtailment_penalty,
            min_soc_per_tech=min_soc_per_tech,
            n_hours=n_hours,
            n_workers=n_workers,
            solver=solver,
            solver_options=solver_options,
            hours=None if hours is None else list(hours),
            profile_outages=profile_outages,
        )
        return real_run_eval(
            baseline_results,
            outage_spec=outage_spec,
            designed_system=designed_system,
            hours=hours,
            slack_penalty=slack_penalty,
            curtailment_penalty=curtailment_penalty,
            min_soc_per_tech=min_soc_per_tech,
            n_hours=n_hours,
            n_workers=n_workers,
            solver=solver,
            solver_options=solver_options,
            profile_outages=profile_outages,
        )

    monkeypatch.setattr(evaluate_module, "load_designed_system", fake_loader)
    monkeypatch.setattr(evaluate_module, "build_baseline_dispatch", fake_build)
    monkeypatch.setattr(evaluate_module, "run_baseline_dispatch", fake_run_baseline)
    monkeypatch.setattr(evaluate_module, "run_resiliency_evaluation", fake_run_eval)

    spec = OutageSpec(
        duration_hours=2,
        recovery_hours=2,
        outaged_assets={"balancing_units": "all"},
    )
    formulation_overrides = {"Imports": "ImportsWithDemandChargesFormulation"}
    min_soc = {"Li-Ion": 0.2}

    evaluate_resiliency(
        snapshot_dir=snapshot_dir,
        inputs_dir=inputs_dir,
        outage_spec=spec,
        year=2030,
        scenario_id=1,
        n_hours=24,
        hours=[1, 2, 3],
        min_soc_per_tech=min_soc,
        slack_penalty=999.0,
        curtailment_penalty=1.5,
        formulation_overrides=formulation_overrides,
        n_workers=1,
        solver="highs",
    )

    # Loader received formulation_overrides
    assert captured["loader"]["formulation_overrides"] == formulation_overrides
    assert captured["loader"]["year"] == 2030
    assert captured["loader"]["scenario_id"] == 1

    # Builder received curtailment_penalty + min_soc
    assert captured["build"]["curtailment_penalty"] == 1.5
    assert captured["build"]["min_soc_per_tech"] == min_soc
    assert captured["build"]["n_hours"] == 24

    # Baseline runner received solver
    assert captured["run_baseline"]["solver"] == "highs"

    # Resiliency runner received slack_penalty etc.
    assert captured["run_eval"]["slack_penalty"] == 999.0
    assert captured["run_eval"]["curtailment_penalty"] == 1.5
    assert captured["run_eval"]["min_soc_per_tech"] == min_soc
    assert captured["run_eval"]["n_hours"] == 24
    assert captured["run_eval"]["n_workers"] == 1
    assert captured["run_eval"]["solver"] == "highs"
    assert captured["run_eval"]["hours"] == [1, 2, 3]


def test_evaluate_resiliency_default_hours_is_full_horizon(tmp_path, patched_loader):
    snapshot_dir = tmp_path / "snapshot"
    inputs_dir = tmp_path / "inputs"
    snapshot_dir.mkdir()
    inputs_dir.mkdir()

    spec = OutageSpec(
        duration_hours=2,
        recovery_hours=2,
        outaged_assets={"balancing_units": "all"},
    )
    results = evaluate_resiliency(
        snapshot_dir=snapshot_dir,
        inputs_dir=inputs_dir,
        outage_spec=spec,
        n_hours=24,
        hours=None,
        n_workers=1,
    )
    # Full horizon: anchor hours 1..24
    assert sorted(results.per_hour.index.tolist()) == list(range(1, 25))


def test_evaluate_resiliency_explicit_hours_subset(tmp_path, patched_loader):
    snapshot_dir = tmp_path / "snapshot"
    inputs_dir = tmp_path / "inputs"
    snapshot_dir.mkdir()
    inputs_dir.mkdir()

    spec = OutageSpec(
        duration_hours=2,
        recovery_hours=2,
        outaged_assets={"balancing_units": "all"},
    )
    results = evaluate_resiliency(
        snapshot_dir=snapshot_dir,
        inputs_dir=inputs_dir,
        outage_spec=spec,
        n_hours=24,
        hours=[1, 5, 10],
        n_workers=1,
    )
    assert len(results.per_hour) == 3
    assert sorted(results.per_hour.index.tolist()) == [1, 5, 10]
