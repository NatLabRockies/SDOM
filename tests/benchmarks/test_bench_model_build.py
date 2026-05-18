from __future__ import annotations

import pytest

from sdom import initialize_model, load_data
from sdom.resiliency import build_baseline_dispatch, load_designed_system


@pytest.mark.bench_quick
def test_bench_initialize_model_legacy_24h(benchmark, legacy_data_path):
    """Benchmark legacy model construction on a 24h horizon."""

    def _build():
        data = load_data(str(legacy_data_path))
        return initialize_model(data, n_hours=24)

    model = benchmark(_build)
    assert hasattr(model, "h")


@pytest.mark.bench_quick
def test_bench_initialize_model_zonal_24h(benchmark, zonal_data_path):
    """Benchmark zonal model construction on a 24h horizon."""

    def _build():
        data = load_data(str(zonal_data_path))
        return initialize_model(data, n_hours=24)

    model = benchmark(_build)
    assert hasattr(model, "h")


@pytest.mark.bench_quick
def test_bench_build_baseline_dispatch_24h(
    benchmark,
    resiliency_snapshot_dir,
    resiliency_inputs_dir,
):
    """Benchmark resiliency baseline model build (24h)."""
    designed_system = load_designed_system(
        resiliency_snapshot_dir,
        inputs_dir=resiliency_inputs_dir,
        year=2030,
        scenario_id=1,
    )

    def _build():
        return build_baseline_dispatch(designed_system, n_hours=24)

    model = benchmark(_build)
    assert hasattr(model, "h")
