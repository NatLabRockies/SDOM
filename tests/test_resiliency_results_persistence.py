"""Phase 6 - Deliverable B: ResiliencyResults.save / load round-trip."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from sdom.resiliency import ResiliencyResults
from sdom.resiliency.outage_scenarios import OutageSpec

pyarrow = pytest.importorskip("pyarrow")


def _make_results(*, n=5):
    df = pd.DataFrame(
        {
            "EUE": [0.0, 1.0, 0.0, 5.0, 10.0],
            "USE_hours": [0, 1, 0, 2, 3],
            "max_unserved_MW": [0.0, 1.0, 0.0, 5.0, 10.0],
            "objective_value": [100.0] * n,
            "solver_status": ["optimal"] * n,
            "solve_time_s": [0.01] * n,
            "truncated": [False] * n,
            "error_message": [""] * n,
        },
        index=pd.Index(list(range(1, n + 1)), name="hour"),
    )
    spec = OutageSpec(
        duration_hours=24,
        recovery_hours=24,
        outaged_assets={"balancing_units": "all"},
    )
    return ResiliencyResults(
        per_hour=df,
        metadata={
            "n_workers_used": 3,
            "n_hours": n,
            "solver": "highs",
            "outage_spec": spec,
        },
    )


def test_save_default_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    results = _make_results()

    results.save()

    assert (tmp_path / "results_resiliency" / "per_hour.parquet").exists()
    assert (tmp_path / "results_resiliency" / "summary.json").exists()


def test_save_explicit_path(tmp_path):
    results = _make_results()
    out = tmp_path / "out"

    results.save(out)

    assert (out / "per_hour.parquet").exists()
    assert (out / "summary.json").exists()


def test_load_round_trip(tmp_path):
    original = _make_results()
    original.save(tmp_path)

    loaded = ResiliencyResults.load(tmp_path)

    pd.testing.assert_frame_equal(loaded.per_hour, original.per_hour)
    # Aggregate metrics survive the round-trip.
    assert loaded.metrics(level="aggregate") == original.metrics(level="aggregate")
    # JSON-safe metadata slice survives.
    assert loaded.metadata["n_workers_used"] == 3
    assert loaded.metadata["n_hours"] == 5
    assert loaded.metadata["solver"] == "highs"


def test_summary_json_contents(tmp_path):
    results = _make_results()
    results.save(tmp_path)

    payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    assert set(payload.keys()) == {"version", "aggregate_metrics", "metadata"}
    assert payload["version"] == "1"
    assert "LOLP" in payload["aggregate_metrics"]
    assert "outage_spec_summary" in payload["metadata"]
    summary = payload["metadata"]["outage_spec_summary"]
    assert summary["duration_hours"] == 24
    assert summary["recovery_hours"] == 24
    assert summary["outaged_assets_components"] == ["balancing_units"]
    # The full OutageSpec object must NOT be persisted.
    assert "outage_spec" not in payload["metadata"]


def test_load_missing_files_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="per_hour.parquet"):
        ResiliencyResults.load(tmp_path / "nonexistent")


def test_summary_contains_expected_metric_keys(tmp_path):
    """summary.json includes the probability-weighted expected metrics (#69)."""
    results = _make_results()
    results.save(tmp_path)

    payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    agg = payload["aggregate_metrics"]

    assert "EUE_expected" in agg
    assert "USE_hours_expected" in agg
    assert isinstance(agg["EUE_expected"], float)
    assert isinstance(agg["USE_hours_expected"], float)


def test_load_summary_missing_expected_keys_is_backward_compatible(tmp_path):
    """An older ``summary.json`` without expected keys still loads cleanly."""
    original = _make_results()
    original.save(tmp_path)

    # Rewrite summary.json with the legacy aggregate_metrics shape (no
    # ``EUE_expected`` / ``USE_hours_expected``), mimicking a pre-#69 file.
    summary_path = tmp_path / "summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["aggregate_metrics"] = {
        k: v
        for k, v in payload["aggregate_metrics"].items()
        if k not in {"EUE_expected", "USE_hours_expected"}
    }
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = ResiliencyResults.load(tmp_path)
    # Loader must not raise; recomputed metrics expose the new keys.
    m = loaded.metrics(level="aggregate")
    assert "EUE_expected" in m
    assert "USE_hours_expected" in m
