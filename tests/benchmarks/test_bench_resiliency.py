from __future__ import annotations

import pytest

from sdom.resiliency import (
    build_baseline_dispatch,
    evaluate_resiliency,
    load_designed_system,
    run_baseline_dispatch,
    run_resiliency_evaluation,
)


@pytest.mark.bench_deep
def test_bench_run_resiliency_evaluation_serial(
    benchmark,
    resiliency_snapshot_dir,
    resiliency_inputs_dir,
    outage_spec_small,
):
    """Benchmark per-hour outage runner in serial mode (n_workers=1)."""
    designed_system = load_designed_system(
        resiliency_snapshot_dir,
        inputs_dir=resiliency_inputs_dir,
        year=2030,
        scenario_id=1,
    )
    baseline_model = build_baseline_dispatch(designed_system, n_hours=24)
    baseline_results = run_baseline_dispatch(baseline_model, solver="highs")

    def _run():
        return run_resiliency_evaluation(
            baseline_results,
            outage_spec=outage_spec_small,
            hours=[1, 6, 12, 18, 24],
            n_hours=24,
            n_workers=1,
            solver="highs",
            profile_outages=False,
        )

    results = benchmark(_run)
    assert len(results.per_hour) == 5


@pytest.mark.bench_deep
def test_bench_evaluate_resiliency_end_to_end(
    benchmark,
    resiliency_snapshot_dir,
    resiliency_inputs_dir,
    outage_spec_small,
):
    """Benchmark top-level resiliency helper on a small smoke configuration."""

    def _run():
        return evaluate_resiliency(
            resiliency_snapshot_dir,
            inputs_dir=resiliency_inputs_dir,
            outage_spec=outage_spec_small,
            year=2030,
            scenario_id=1,
            n_hours=24,
            hours=[1, 6, 12, 18, 24],
            n_workers=1,
            solver="highs",
            profile_baseline=False,
            profile_outages=False,
        )

    results = benchmark(_run)
    assert len(results.per_hour) == 5
