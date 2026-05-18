from __future__ import annotations

import pytest

from sdom import load_data


@pytest.mark.bench_quick
def test_bench_load_data_legacy(benchmark, legacy_data_path):
    """Benchmark legacy-folder data load/parsing."""
    result = benchmark(load_data, str(legacy_data_path))
    assert isinstance(result, dict)


@pytest.mark.bench_quick
def test_bench_load_data_zonal(benchmark, zonal_data_path):
    """Benchmark zonal-folder data load/parsing."""
    result = benchmark(load_data, str(zonal_data_path))
    assert isinstance(result, dict)
