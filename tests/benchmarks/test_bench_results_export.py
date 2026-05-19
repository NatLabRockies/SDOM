from __future__ import annotations

import pytest

from sdom import export_results, initialize_model, load_data, run_solver


@pytest.mark.bench_quick
def test_bench_export_results_legacy(
    benchmark,
    tmp_path,
    legacy_data_path,
    highs_solver_config,
):
    """Benchmark CSV export for legacy optimization results."""
    data = load_data(str(legacy_data_path))
    model = initialize_model(data, n_hours=24)
    results = run_solver(model, highs_solver_config, case_name="bench_export_legacy")

    def _export():
        export_results(results, case="bench_export_legacy", output_dir=str(tmp_path / "legacy"))

    benchmark(_export)


@pytest.mark.bench_quick
def test_bench_export_results_zonal(
    benchmark,
    tmp_path,
    zonal_data_path,
    highs_solver_config,
):
    """Benchmark CSV export for zonal optimization results."""
    data = load_data(str(zonal_data_path))
    model = initialize_model(data, n_hours=24)
    results = run_solver(model, highs_solver_config, case_name="bench_export_zonal")

    def _export():
        export_results(results, case="bench_export_zonal", output_dir=str(tmp_path / "zonal"))

    benchmark(_export)
