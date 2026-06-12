"""Smoke tests for opt-in profiling on resiliency builders.

The profiler is reused from :mod:`sdom.utils_performance_meassure`. These
tests check that:

* ``profile=False`` (default) does not attach a profiler.
* ``profile=True`` attaches a populated :class:`ModelInitProfiler` and the
  printed summary uses the requested title.
"""

from __future__ import annotations

import logging

from sdom.resiliency import (
    BaselineState,  # noqa: F401 - ensure package is importable
    OutageSpec,
    build_baseline_dispatch,
    build_outage_dispatch,
    run_baseline_dispatch,
)
from sdom.utils_performance_meassure import ModelInitProfiler



def _designed_system():
    """Standalone loader to avoid pulling pytest fixtures across modules."""
    from sdom.resiliency import load_designed_system

    from _resiliency_fixtures import (
        INPUTS_DIR_MEA,
        SCENARIO_ID,
        SNAPSHOT_DIR_MEA,
        YEAR,
    )

    return load_designed_system(
        SNAPSHOT_DIR_MEA,
        inputs_dir=INPUTS_DIR_MEA,
        year=YEAR,
        scenario_id=SCENARIO_ID,
    )


def test_baseline_build_no_profiler_by_default(caplog):
    ds = _designed_system()
    with caplog.at_level(logging.INFO, logger="sdom.resiliency.dispatch_model"):
        build_baseline_dispatch(ds, n_hours=24)
    # The CEM builder always attaches its own ``profiler`` to the model, so
    # ``hasattr(model, "profiler")`` is no longer a reliable signal. What the
    # resiliency wrapper guarantees when ``profile=False`` is that *its own*
    # baseline-build summary is not printed.
    full_log = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "BASELINE DISPATCH BUILD PROFILING SUMMARY" not in full_log


def test_baseline_build_attaches_profiler(caplog):
    ds = _designed_system()
    with caplog.at_level(logging.INFO, logger="sdom.resiliency.dispatch_model"):
        model = build_baseline_dispatch(ds, n_hours=24, profile=True)

    assert hasattr(model, "profiler")
    assert isinstance(model.profiler, ModelInitProfiler)
    assert len(model.profiler.steps) >= 5
    assert model.profiler.get_total_time() > 0.0
    full_log = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "BASELINE DISPATCH BUILD PROFILING SUMMARY" in full_log


def test_run_baseline_dispatch_profile_metadata(caplog):
    ds = _designed_system()
    model = build_baseline_dispatch(ds, n_hours=24)
    with caplog.at_level(logging.INFO, logger="sdom.resiliency.dispatch_model"):
        results = run_baseline_dispatch(model, profile=True)
    assert "profiler" in results.metadata
    assert isinstance(results.metadata["profiler"], ModelInitProfiler)
    full_log = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "BASELINE DISPATCH SOLVE PROFILING SUMMARY" in full_log


def test_outage_build_attaches_profiler(caplog):
    ds = _designed_system()
    base_model = build_baseline_dispatch(ds, n_hours=24)
    baseline = run_baseline_dispatch(base_model)
    spec = OutageSpec(
        duration_hours=2,
        recovery_hours=2,
        outaged_assets={"imports": "all"},
    )
    with caplog.at_level(logging.INFO, logger="sdom.resiliency.outage_dispatch"):
        outage_model = build_outage_dispatch(
            baseline,
            start_hour=1,
            outage_spec=spec,
            designed_system=ds,
            n_hours=24,
            profile=True,
        )

    assert hasattr(outage_model, "profiler")
    assert isinstance(outage_model.profiler, ModelInitProfiler)
    assert len(outage_model.profiler.steps) >= 5
    full_log = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "OUTAGE DISPATCH BUILD PROFILING SUMMARY" in full_log
