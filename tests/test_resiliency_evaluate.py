"""Phase 7 / Deliverable A tests for ``evaluate_resiliency`` (MEA data).

After the CEM-reuse refactor (commit 5b346ad) ``build_baseline_dispatch``
requires ``DesignedSystem.cem_data``, which can only be populated by the
real loader. The pre-refactor tests monkey-patched the loader to return a
hand-built ``DesignedSystem``; that path no longer works. These tests now
exercise the same behaviours against the real MEA snapshot, with
expensive evaluate calls cached at module scope.
"""

from __future__ import annotations

import pyomo.environ as pyo
import pytest

from sdom.resiliency import (
    OutageSpec,
    ResiliencyResults,
    evaluate_resiliency,
)
from sdom.resiliency import evaluate as evaluate_module

from _resiliency_fixtures import (
    INPUTS_DIR_MEA,
    SNAPSHOT_DIR_MEA,
    SCENARIO_ID,
    YEAR,
)


# ---------------------------------------------------------------------------
# Solver / data gates
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


pytestmark = [
    pytest.mark.skipif(not _highs_available(), reason="HiGHS solver not available"),
    pytest.mark.skipif(
        not INPUTS_DIR_MEA.exists() or not SNAPSHOT_DIR_MEA.exists(),
        reason="Paper_MEA fixtures missing",
    ),
    pytest.mark.slow,
]


SPEC_SMALL = OutageSpec(
    duration_hours=2,
    recovery_hours=2,
    outaged_assets={"imports": "all"},
)


# ---------------------------------------------------------------------------
# Module-scoped MEA evaluate results (expensive — share across tests)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def mea_eval_full_horizon():
    """Full-horizon evaluate on a small ``n_hours`` (anchors = range(1, n+1))."""
    return evaluate_resiliency(
        snapshot_dir=SNAPSHOT_DIR_MEA,
        inputs_dir=INPUTS_DIR_MEA,
        outage_spec=SPEC_SMALL,
        year=YEAR,
        scenario_id=SCENARIO_ID,
        n_hours=3,
        hours=None,
        n_workers=1,
        solver="highs",
    )


@pytest.fixture(scope="module")
def mea_eval_subset():
    """Evaluate with an explicit ``hours`` subset."""
    return evaluate_resiliency(
        snapshot_dir=SNAPSHOT_DIR_MEA,
        inputs_dir=INPUTS_DIR_MEA,
        outage_spec=SPEC_SMALL,
        year=YEAR,
        scenario_id=SCENARIO_ID,
        n_hours=24,
        hours=[1, 5, 10],
        n_workers=1,
        solver="highs",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_evaluate_resiliency_smoke(mea_eval_full_horizon):
    """End-to-end ``evaluate_resiliency`` returns a populated ``ResiliencyResults``."""
    results = mea_eval_full_horizon
    assert isinstance(results, ResiliencyResults)
    assert results.metadata["n_hours"] == 3
    assert results.metadata["solver"] == "highs"
    assert results.metadata.get("outage_spec") is not None


def test_evaluate_resiliency_passes_through_kwargs(monkeypatch):
    """Loader + build + baseline run + outage runner all receive forwarded kwargs."""
    captured: dict[str, dict] = {}

    real_loader = evaluate_module.load_designed_system
    real_build = evaluate_module.build_baseline_dispatch
    real_run_baseline = evaluate_module.run_baseline_dispatch
    real_run_eval = evaluate_module.run_resiliency_evaluation

    def fake_loader(snapshot_dir, *, inputs_dir, year=2030, scenario_id=1,
                    formulation_overrides=None):
        captured["loader"] = dict(
            snapshot_dir=snapshot_dir,
            inputs_dir=inputs_dir,
            year=year,
            scenario_id=scenario_id,
            formulation_overrides=formulation_overrides,
        )
        return real_loader(
            snapshot_dir,
            inputs_dir=inputs_dir,
            year=year,
            scenario_id=scenario_id,
            formulation_overrides=formulation_overrides,
        )

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
        return real_run_baseline(
            model, solver=solver, solver_options=solver_options, tee=tee, profile=profile,
        )

    def fake_run_eval(baseline_results, *, outage_spec, designed_system=None,
                      hours=None, slack_penalty=10_000.0, curtailment_penalty=0.0,
                      soc_slack_penalty=1_000.0,
                      min_soc_per_tech=None, n_hours=8760, n_workers=None,
                      solver="highs", solver_options=None, profile_outages=False):
        captured["run_eval"] = dict(
            slack_penalty=slack_penalty,
            curtailment_penalty=curtailment_penalty,
            soc_slack_penalty=soc_slack_penalty,
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
            soc_slack_penalty=soc_slack_penalty,
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

    min_soc = {"Li-Ion": 0.2}

    evaluate_resiliency(
        snapshot_dir=SNAPSHOT_DIR_MEA,
        inputs_dir=INPUTS_DIR_MEA,
        outage_spec=SPEC_SMALL,
        year=YEAR,
        scenario_id=SCENARIO_ID,
        n_hours=24,
        hours=[1],
        min_soc_per_tech=min_soc,
        slack_penalty=999.0,
        curtailment_penalty=1.5,
        n_workers=1,
        solver="highs",
    )

    # Loader received the right snapshot / scenario.
    assert captured["loader"]["snapshot_dir"] == SNAPSHOT_DIR_MEA
    assert captured["loader"]["inputs_dir"] == INPUTS_DIR_MEA
    assert captured["loader"]["year"] == YEAR
    assert captured["loader"]["scenario_id"] == SCENARIO_ID

    # Builder received curtailment_penalty + min_soc + n_hours.
    assert captured["build"]["curtailment_penalty"] == 1.5
    assert captured["build"]["min_soc_per_tech"] == min_soc
    assert captured["build"]["n_hours"] == 24

    # Baseline runner received solver.
    assert captured["run_baseline"]["solver"] == "highs"

    # Resiliency runner received slack_penalty etc.
    assert captured["run_eval"]["slack_penalty"] == 999.0
    assert captured["run_eval"]["curtailment_penalty"] == 1.5
    assert captured["run_eval"]["min_soc_per_tech"] == min_soc
    assert captured["run_eval"]["n_hours"] == 24
    assert captured["run_eval"]["n_workers"] == 1
    assert captured["run_eval"]["solver"] == "highs"
    assert captured["run_eval"]["hours"] == [1]


def test_evaluate_resiliency_default_hours_is_full_horizon(mea_eval_full_horizon):
    """``hours=None`` evaluates every anchor in ``range(1, n_hours + 1)``."""
    results = mea_eval_full_horizon
    assert sorted(results.per_hour.index.tolist()) == [1, 2, 3]


def test_evaluate_resiliency_explicit_hours_subset(mea_eval_subset):
    """``hours=[...]`` restricts evaluation to the requested anchors."""
    results = mea_eval_subset
    assert len(results.per_hour) == 3
    assert sorted(results.per_hour.index.tolist()) == [1, 5, 10]
