"""Tests for zonal-aware ``OptimizationResults`` and ``collect_results_from_model``.

Covers the zonal results collector and the new
zonal fields on :class:`sdom.results.OptimizationResults`. Drives the
solver via :func:`sdom.optimization_main.run_solver` end-to-end on
both the legacy single-area fixture and the canonical 2-area fixture.
"""

from __future__ import annotations

import os
import pickle

import pandas as pd
import pyomo.environ as pyo
import pytest

from sdom import initialize_model, load_data
from sdom.optimization_main import (
    get_default_solver_config_dict,
    run_solver,
)
from sdom.results import OptimizationResults


REL_LEGACY_FIXTURE = "Data/no_exchange_run_of_river"
REL_ZONAL_FIXTURE = "Data/zonal_test"


def _abs_data_path(rel: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", rel))


def _highs_available() -> bool:
    """Return True if a HiGHS solver is available on the system."""
    for name in ("appsi_highs", "highs"):
        try:
            s = pyo.SolverFactory(name)
            if s is not None and s.available(exception_flag=False):
                return True
        except Exception:
            continue
    return False


def _highs_config():
    """Build a HiGHS solver-config dict with quiet output."""
    config = get_default_solver_config_dict(solver_name="highs")
    config["solve_keywords"]["tee"] = False
    config["solve_keywords"]["report_timing"] = False
    config["solve_keywords"]["keepfiles"] = False
    return config


# ---------------------------------------------------------------------------
# Module-scoped fixtures (skip whole module if HiGHS unavailable for solves)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def legacy_results():
    if not _highs_available():
        pytest.skip("HiGHS solver not available")
    data = load_data(_abs_data_path(REL_LEGACY_FIXTURE))
    model = initialize_model(data, n_hours=24)
    return run_solver(model, _highs_config(), case_name="legacy_test")


@pytest.fixture(scope="module")
def zonal_data():
    return load_data(_abs_data_path(REL_ZONAL_FIXTURE))


@pytest.fixture(scope="module")
def zonal_model_and_results(zonal_data):
    if not _highs_available():
        pytest.skip("HiGHS solver not available")
    model = initialize_model(zonal_data, n_hours=24)
    results = run_solver(model, _highs_config(), case_name="zonal_test")
    return model, results


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------
def test_results_dataclass_has_zonal_defaults():
    """An empty ``OptimizationResults`` has zonal fields defaulted to empty."""
    r = OptimizationResults()
    assert r.is_zonal is False
    assert r.areas == []
    assert r.lines == []
    assert r.area_capacity == {}
    assert r.area_storage_capacity == {}
    assert r.area_generation_totals == {}
    assert r.area_cost_breakdown == {}
    assert r.area_generation_df == {}
    assert r.area_storage_df == {}
    assert r.area_thermal_generation_df == {}
    assert r.area_installed_plants_df == {}
    assert r.area_summary_df == {}
    assert isinstance(r.interregional_exchanges_df, pd.DataFrame)
    assert r.interregional_exchanges_df.empty


# ---------------------------------------------------------------------------
# Legacy path is untouched
# ---------------------------------------------------------------------------
def test_legacy_path_does_not_populate_zonal_fields(legacy_results):
    """The legacy collector keeps every zonal field at its default."""
    assert legacy_results.is_optimal
    assert legacy_results.is_zonal is False
    assert legacy_results.areas == []
    assert legacy_results.lines == []
    assert legacy_results.interregional_exchanges_df.empty
    assert legacy_results.area_generation_df == {}
    assert legacy_results.area_storage_df == {}
    assert legacy_results.area_summary_df == {}

    # Sanity: legacy collector still works (one numeric scalar > 0).
    assert legacy_results.total_cap_pv >= 0
    assert legacy_results.total_cost > 0
    assert not legacy_results.generation_df.empty
    # Legacy generation_df has no Area column.
    assert "Area" not in legacy_results.generation_df.columns


# ---------------------------------------------------------------------------
# Zonal path: areas + lines
# ---------------------------------------------------------------------------
def test_zonal_path_populates_areas_and_lines(zonal_data, zonal_model_and_results):
    _model, results = zonal_model_and_results
    assert results.is_optimal
    assert results.is_zonal is True
    assert results.areas == [a["area_id"] for a in zonal_data["areas"]]
    assert results.areas == ["A1", "A2"]
    assert len(results.lines) == 1
    line = results.lines[0]
    assert {"line_id", "from_area", "to_area"} <= set(line.keys())
    assert line["from_area"] in {"A1", "A2"}
    assert line["to_area"] in {"A1", "A2"}
    assert line["from_area"] != line["to_area"]


# ---------------------------------------------------------------------------
# Zonal path: per-area DataFrames + concatenated top-level frames
# ---------------------------------------------------------------------------
def test_zonal_path_per_area_dataframes_have_correct_shape(zonal_model_and_results):
    _model, results = zonal_model_and_results
    n_hours = 24

    # Per-area dicts: one entry per area.
    assert set(results.area_generation_df.keys()) == {"A1", "A2"}
    assert set(results.area_storage_df.keys()) == {"A1", "A2"}
    assert set(results.area_installed_plants_df.keys()) == {"A1", "A2"}

    # Each per-area generation_df has 24 rows.
    for a in ("A1", "A2"):
        df = results.area_generation_df[a]
        assert len(df) == n_hours
        assert "Area" not in df.columns

    # Top-level generation_df has 48 rows + Area col at position 0.
    top_gen = results.generation_df
    assert len(top_gen) == 2 * n_hours
    assert top_gen.columns[0] == "Area"
    assert set(top_gen["Area"].unique()) == {"A1", "A2"}

    # Top-level installed_plants_df has the Area column right after Plant ID.
    top_plants = results.installed_plants_df
    if not top_plants.empty:
        assert list(top_plants.columns).index("Area") == 1
        assert set(top_plants["Area"].unique()) <= {"A1", "A2"}


# ---------------------------------------------------------------------------
# Interregional exchanges: PRD §2.4 schema
# ---------------------------------------------------------------------------
def test_zonal_interregional_exchanges_schema(zonal_model_and_results):
    model, results = zonal_model_and_results
    df = results.interregional_exchanges_df

    expected_cols = {
        "line_id",
        "from_area",
        "to_area",
        "hour",
        "flow_signed_MW",
        "flow_FT_MW",
        "flow_TF_MW",
        "cap_FT_MW",
        "cap_TF_MW",
        "utilization_FT",
        "utilization_TF",
    }
    assert set(df.columns) == expected_cols

    n_lines = len(model.L)
    n_hours = len(model.h)
    assert len(df) == n_lines * n_hours

    # signed = FT - TF (within a small tolerance).
    diff = (df["flow_FT_MW"] - df["flow_TF_MW"] - df["flow_signed_MW"]).abs()
    assert diff.max() < 1e-9

    # FT and TF are non-negative; one of them is zero per row (LP optimum).
    assert (df["flow_FT_MW"] >= -1e-9).all()
    assert (df["flow_TF_MW"] >= -1e-9).all()
    assert (df["flow_FT_MW"] * df["flow_TF_MW"] <= 1e-9).all()

    # Flows respect capacity bounds.
    assert (df["flow_FT_MW"] <= df["cap_FT_MW"] + 1e-6).all()
    assert (df["flow_TF_MW"] <= df["cap_TF_MW"] + 1e-6).all()

    # Utilization is NaN-safe: when the cap is positive, utilization is finite.
    pos_ft = df["cap_FT_MW"] > 0
    assert df.loc[pos_ft, "utilization_FT"].notna().all()
    pos_tf = df["cap_TF_MW"] > 0
    assert df.loc[pos_tf, "utilization_TF"].notna().all()


# ---------------------------------------------------------------------------
# Total cost matches model objective
# ---------------------------------------------------------------------------
def test_zonal_path_total_cost_matches_objective(zonal_model_and_results):
    model, results = zonal_model_and_results
    assert results.total_cost == pytest.approx(pyo.value(model.Obj.expr), rel=1e-9)
    assert results.gen_mix_target == pytest.approx(float(model.GenMix_Target.value))


# ---------------------------------------------------------------------------
# Pickle round-trip survives for both legacy and zonal results
# ---------------------------------------------------------------------------
def test_results_pickle_roundtrip(legacy_results, zonal_model_and_results):
    _model, zonal_results = zonal_model_and_results

    for r in (legacy_results, zonal_results):
        blob = pickle.dumps(r)
        r2 = pickle.loads(blob)
        assert isinstance(r2, OptimizationResults)
        assert r2.is_zonal == r.is_zonal
        assert r2.total_cost == pytest.approx(r.total_cost)
        assert r2.areas == r.areas
        assert r2.lines == r.lines
        # DataFrame round-trip preserves shape.
        assert r2.generation_df.shape == r.generation_df.shape
        assert (
            r2.interregional_exchanges_df.shape
            == r.interregional_exchanges_df.shape
        )
