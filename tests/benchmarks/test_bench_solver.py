from __future__ import annotations

import pytest

from sdom import initialize_model, load_data, run_solver
from sdom.resiliency import (
    build_baseline_dispatch,
    load_designed_system,
    run_baseline_dispatch,
)


@pytest.mark.bench_deep
def test_bench_run_solver_legacy_24h(benchmark, legacy_data_path, highs_solver_config):
    """Benchmark end-to-end legacy solve (build + solve + result collection)."""

    def _solve():
        data = load_data(str(legacy_data_path))
        model = initialize_model(data, n_hours=24)
        return run_solver(model, highs_solver_config, case_name="bench_legacy")

    result = benchmark(_solve)
    assert result.is_optimal


@pytest.mark.bench_deep
def test_bench_run_solver_zonal_24h(benchmark, zonal_data_path, highs_solver_config):
    """Benchmark end-to-end zonal solve (build + solve + result collection)."""

    def _solve():
        data = load_data(str(zonal_data_path))
        model = initialize_model(data, n_hours=24)
        return run_solver(model, highs_solver_config, case_name="bench_zonal")

    result = benchmark(_solve)
    assert result.is_optimal


@pytest.mark.bench_deep
def test_bench_run_baseline_dispatch_24h(
    benchmark,
    resiliency_snapshot_dir,
    resiliency_inputs_dir,
):
    """Benchmark resiliency baseline solve after model build."""
    designed_system = load_designed_system(
        resiliency_snapshot_dir,
        inputs_dir=resiliency_inputs_dir,
        year=2030,
        scenario_id=1,
    )

    def _solve():
        model = build_baseline_dispatch(designed_system, n_hours=24)
        return run_baseline_dispatch(model, solver="highs")

    result = benchmark(_solve)
    assert result.solver_status is not None
    assert result.objective_value is not None
