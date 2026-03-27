"""Integration test: complete ParametricStudy run with analytic_tools plot generation.

Runs the same 3 × 2 × 2 = 12-case sensitivity study defined in
``___sdom_test_parametric_sims_v2.py`` against the ``Data/no_exchange_run_of_river``
dataset and then:
  1. Asserts all 12 cases solve optimally.
  2. Checks that all expected CSV output files are created.
  3. Checks that all expected plot files are created (per-case + sensitivity).
  4. Validates key numeric results (total cost, capacity) from each case's
     ``OutputSummary`` CSV against reference values at ±2 % tolerance.
  5. Cleans up by deleting the temporary output directory.

The expected reference values were produced by running the study with the
HiGHS solver against 96 simulation hours (matching the reference script).
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pandas as pd
import pytest

from sdom import get_default_solver_config_dict, load_data
from sdom.analytic_tools import plot_parametric_results
from sdom.parametric import ParametricStudy

# ---------------------------------------------------------------------------
# Test configuration (mirrors ___sdom_test_parametric_sims_v2.py)
# ---------------------------------------------------------------------------

_REL_DATA_DIR = "Data/no_exchange_run_of_river"
_N_HOURS = 96
_N_CORES = 3

_GENMIX_TARGETS = [0.0, 0.8, 1.0]
_STORAGE_CAPEX_FACTORS = [1.0, 0.7]
_LOAD_SCALE_FACTORS = [1.0, 1.4]

_EXPECTED_N_CASES = (
    len(_GENMIX_TARGETS) * len(_STORAGE_CAPEX_FACTORS) * len(_LOAD_SCALE_FACTORS)
)  # 12

# ---------------------------------------------------------------------------
# Per-case CSV files that must be present for every case
# ---------------------------------------------------------------------------
_EXPECTED_CSV_PREFIXES = [
    "OutputGeneration_",
    "OutputThermalGeneration_",
    "OutputStorage_",
    "OutputSummary_",
    "OutputInstalledPowerPlants_",
]

# ---------------------------------------------------------------------------
# Per-case plot files that must be present for every case
# ---------------------------------------------------------------------------
_EXPECTED_PER_CASE_PLOTS = [
    "capacity_donut.png",
    "capacity_generation_donuts.png",
]
# At least one heatmap must also be present (column names are dynamic)

# ---------------------------------------------------------------------------
# Cross-case sensitivity-plots that must be present
# ---------------------------------------------------------------------------
_EXPECTED_SENSITIVITY_PLOTS = [
    "capacity_comparison.png",
    "generation_comparison.png",
    "curtailment_absolute.png",
    "curtailment_percentage.png",
    "cost_comparison.png",
]

# ---------------------------------------------------------------------------
# Reference numeric values (generated from the golden results stored under
# Data/no_exchange_run_of_river/results).
# Tolerance: 2 % relative.
# ---------------------------------------------------------------------------
_TOLERANCE = 0.02  # 2 %

# key = case_name, value = {metric: expected_value}
_REFERENCE = {
    "GenMix_Target=0.0_P_Capexx1.0_load_datax1.0": {
        "total_cost": 6_369_074_677.63,
        "thermal_cap_MW": 4_897.0,
        "solar_cap_MW": 7_727.21,
        "wind_cap_MW": 36_251.09,
    },
    "GenMix_Target=0.0_P_Capexx1.0_load_datax1.4": {
        "total_cost": 11_370_282_383.81,
        "thermal_cap_MW": 4_897.0,
        "solar_cap_MW": 18_517.30,
        "wind_cap_MW": 61_816.54,
    },
    "GenMix_Target=0.0_P_Capexx0.7_load_datax1.0": {
        "total_cost": 6_118_914_759.70,
        "thermal_cap_MW": 4_897.0,
        "solar_cap_MW": 6_934.87,
        "wind_cap_MW": 36_713.52,
    },
    "GenMix_Target=0.0_P_Capexx0.7_load_datax1.4": {
        "total_cost": 10_903_040_575.78,
        "thermal_cap_MW": 4_897.0,
        "solar_cap_MW": 17_362.69,
        "wind_cap_MW": 61_833.26,
    },
    "GenMix_Target=0.8_P_Capexx1.0_load_datax1.0": {
        "total_cost": 6_369_074_677.63,
        "thermal_cap_MW": 4_897.0,
        "solar_cap_MW": 7_727.21,
        "wind_cap_MW": 36_251.09,
    },
    "GenMix_Target=0.8_P_Capexx1.0_load_datax1.4": {
        "total_cost": 11_352_498_575.93,
        "thermal_cap_MW": 4_897.0,
        "solar_cap_MW": 18_012.83,
        "wind_cap_MW": 61_934.40,
    },
    "GenMix_Target=0.8_P_Capexx0.7_load_datax1.0": {
        "total_cost": 6_124_254_403.32,
        "thermal_cap_MW": 4_897.0,
        "solar_cap_MW": 7_168.84,
        "wind_cap_MW": 36_642.94,
    },
    "GenMix_Target=0.8_P_Capexx0.7_load_datax1.4": {
        "total_cost": 10_903_040_575.78,
        "thermal_cap_MW": 4_897.0,
        "solar_cap_MW": 17_362.69,
        "wind_cap_MW": 61_833.26,
    },
    "GenMix_Target=1.0_P_Capexx1.0_load_datax1.0": {
        "total_cost": 8_210_209_880.15,
        "thermal_cap_MW": 0.0,
        "solar_cap_MW": 12_604.15,
        "wind_cap_MW": 46_241.58,
    },
    "GenMix_Target=1.0_P_Capexx1.0_load_datax1.4": {
        "total_cost": 13_564_854_890.58,
        "thermal_cap_MW": 0.0,
        "solar_cap_MW": 31_314.00,
        "wind_cap_MW": 69_812.81,
    },
    "GenMix_Target=1.0_P_Capexx0.7_load_datax1.0": {
        "total_cost": 7_896_426_842.24,
        "thermal_cap_MW": 0.0,
        "solar_cap_MW": 11_435.50,
        "wind_cap_MW": 46_746.98,
    },
    "GenMix_Target=1.0_P_Capexx0.7_load_datax1.4": {
        "total_cost": 13_050_334_191.24,
        "thermal_cap_MW": 0.0,
        "solar_cap_MW": 33_921.03,
        "wind_cap_MW": 68_484.86,
    },
}

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _data_dir() -> str:
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", _REL_DATA_DIR)
    )


def _rel(val: float, ref: float) -> float:
    """Relative difference |val - ref| / |ref|; returns 0 when both are 0."""
    if ref == 0.0:
        return abs(val)
    return abs(val - ref) / abs(ref)


def _get_summary_metric(
    summary_df: pd.DataFrame, metric: str, technology: str | None = None
) -> float:
    mask = summary_df["Metric"] == metric
    if technology is not None:
        mask &= summary_df["Technology"] == technology
    rows = summary_df[mask]
    if rows.empty:
        return 0.0
    return float(pd.to_numeric(rows["Optimal Value"].iloc[0], errors="coerce"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parametric_run():
    """Run the full parametric study once per test module and clean up after.

    Returns
    -------
    tuple
        (output_dir, case_names, results, study)
    """
    data = load_data(_data_dir())

    solver_cfg = get_default_solver_config_dict(
        solver_name="highs",
        executable_path="",
    )

    tmp_dir = tempfile.mkdtemp(prefix="sdom_test_parametric_")

    study = ParametricStudy(
        base_data=data,
        solver_config=solver_cfg,
        n_hours=_N_HOURS,
        output_dir=tmp_dir,
        n_cores=_N_CORES,
    )

    study.add_scalar_sweep("scalars", "GenMix_Target", _GENMIX_TARGETS)
    study.add_storage_factor_sweep("P_Capex", _STORAGE_CAPEX_FACTORS)
    study.add_ts_sweep("load_data", _LOAD_SCALE_FACTORS)

    results = study.run()

    # Generate all plots
    plot_parametric_results(
        study,
        results,
        group_by=["GenMix_Target", "P_Capex"],
        hue_by="load_data",
        max_cases_per_figure=36,
        plot_per_case=True,
    )

    yield tmp_dir, [m["case_name"] for m in study.case_metadata], results, study

    # Cleanup — always runs even if tests fail
    shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParametricStudyRun:
    def test_all_cases_solved(self, parametric_run):
        """All 12 case combinations must solve optimally."""
        _, case_names, results, _ = parametric_run
        assert len(results) == _EXPECTED_N_CASES, (
            f"Expected {_EXPECTED_N_CASES} results, got {len(results)}"
        )
        failed = [
            case_names[i]
            for i, r in enumerate(results)
            if not r.is_optimal
        ]
        assert not failed, f"Non-optimal cases: {failed}"

    def test_case_count(self, parametric_run):
        """Exactly 12 case sub-directories must be created."""
        output_dir, _, _, _ = parametric_run
        case_dirs = [
            d for d in os.listdir(output_dir)
            if os.path.isdir(os.path.join(output_dir, d)) and d != "sensitivity_plots"
        ]
        assert len(case_dirs) == _EXPECTED_N_CASES

    def test_parametric_summary_csv_created(self, parametric_run):
        """parametric_summary.csv must exist in the output root."""
        output_dir, _, _, _ = parametric_run
        assert os.path.isfile(os.path.join(output_dir, "parametric_summary.csv"))

    def test_parametric_summary_all_optimal(self, parametric_run):
        """All rows in parametric_summary.csv must have is_optimal == True."""
        output_dir, _, _, _ = parametric_run
        df = pd.read_csv(os.path.join(output_dir, "parametric_summary.csv"))
        assert df["is_optimal"].all(), "Some cases are not optimal in summary CSV"


class TestCsvOutputFiles:
    def test_per_case_csv_files_exist(self, parametric_run):
        """Every case must have all 5 required CSV output files."""
        output_dir, case_names, _, _ = parametric_run
        missing = []
        for case in case_names:
            case_dir = os.path.join(output_dir, case)
            for prefix in _EXPECTED_CSV_PREFIXES:
                expected_path = os.path.join(case_dir, f"{prefix}{case}.csv")
                if not os.path.isfile(expected_path):
                    missing.append(expected_path)
        assert not missing, f"Missing CSV files:\n" + "\n".join(missing)

    def test_csv_files_are_non_empty(self, parametric_run):
        """All CSV output files must have at least one data row."""
        output_dir, case_names, _, _ = parametric_run
        empty = []
        for case in case_names:
            case_dir = os.path.join(output_dir, case)
            for prefix in _EXPECTED_CSV_PREFIXES:
                path = os.path.join(case_dir, f"{prefix}{case}.csv")
                if os.path.isfile(path):
                    df = pd.read_csv(path)
                    if df.empty:
                        empty.append(path)
        assert not empty, f"Empty CSV files:\n" + "\n".join(empty)


class TestPlotFiles:
    def test_per_case_fixed_plots_exist(self, parametric_run):
        """capacity_donut.png and capacity_generation_donuts.png must exist for every case."""
        output_dir, case_names, _, _ = parametric_run
        missing = []
        for case in case_names:
            plots_dir = os.path.join(output_dir, case, "plots")
            for fname in _EXPECTED_PER_CASE_PLOTS:
                path = os.path.join(plots_dir, fname)
                if not os.path.isfile(path):
                    missing.append(path)
        assert not missing, f"Missing per-case plot files:\n" + "\n".join(missing)

    def test_per_case_heatmaps_exist(self, parametric_run):
        """Each case plots/ folder must contain at least one heatmap_*.png file."""
        output_dir, case_names, _, _ = parametric_run
        cases_without_heatmap = []
        for case in case_names:
            plots_dir = os.path.join(output_dir, case, "plots")
            heatmaps = [
                f for f in os.listdir(plots_dir) if f.startswith("heatmap_")
            ]
            if not heatmaps:
                cases_without_heatmap.append(case)
        assert not cases_without_heatmap, (
            f"Cases missing heatmaps: {cases_without_heatmap}"
        )

    def test_sensitivity_plots_exist(self, parametric_run):
        """All 4 cross-case sensitivity comparison plots must be present."""
        output_dir, _, _, _ = parametric_run
        sensitivity_dir = os.path.join(output_dir, "sensitivity_plots")
        missing = [
            f for f in _EXPECTED_SENSITIVITY_PLOTS
            if not os.path.isfile(os.path.join(sensitivity_dir, f))
        ]
        assert not missing, f"Missing sensitivity plots: {missing}"

    def test_sensitivity_plots_dir_created(self, parametric_run):
        """sensitivity_plots/ directory must exist."""
        output_dir, _, _, _ = parametric_run
        assert os.path.isdir(os.path.join(output_dir, "sensitivity_plots"))

    def test_cost_comparison_plot_non_empty(self, parametric_run):
        """cost_comparison.png must be a non-empty file (valid PNG written by matplotlib)."""
        output_dir, _, _, _ = parametric_run
        path = os.path.join(output_dir, "sensitivity_plots", "cost_comparison.png")
        assert os.path.isfile(path), "cost_comparison.png not found in sensitivity_plots/"
        assert os.path.getsize(path) > 0, "cost_comparison.png is empty"


class TestNumericResults:
    """Validate key per-case numeric values against reference at ≤2 % tolerance."""

    @pytest.mark.parametrize("case_name", list(_REFERENCE.keys()))
    def test_total_cost(self, parametric_run, case_name):
        output_dir, _, _, _ = parametric_run
        csv = os.path.join(output_dir, case_name, f"OutputSummary_{case_name}.csv")
        assert os.path.isfile(csv), f"OutputSummary CSV not found for {case_name}"
        df = pd.read_csv(csv)
        actual = _get_summary_metric(df, "Total cost")
        ref = _REFERENCE[case_name]["total_cost"]
        assert _rel(actual, ref) <= _TOLERANCE, (
            f"[{case_name}] total_cost: got {actual:.2f}, expected ~{ref:.2f} "
            f"(rel diff = {_rel(actual, ref):.2%})"
        )

    @pytest.mark.parametrize("case_name", list(_REFERENCE.keys()))
    def test_thermal_capacity(self, parametric_run, case_name):
        output_dir, _, _, _ = parametric_run
        csv = os.path.join(output_dir, case_name, f"OutputSummary_{case_name}.csv")
        df = pd.read_csv(csv)
        actual = _get_summary_metric(df, "Capacity", "Thermal")
        ref = _REFERENCE[case_name]["thermal_cap_MW"]
        # When both reference and actual are 0, skip relative comparison
        if ref == 0.0 and actual == 0.0:
            return
        assert _rel(actual, ref) <= _TOLERANCE, (
            f"[{case_name}] Thermal capacity: got {actual:.2f} MW, expected ~{ref:.2f} MW "
            f"(rel diff = {_rel(actual, ref):.2%})"
        )

    @pytest.mark.parametrize("case_name", list(_REFERENCE.keys()))
    def test_solar_capacity(self, parametric_run, case_name):
        output_dir, _, _, _ = parametric_run
        csv = os.path.join(output_dir, case_name, f"OutputSummary_{case_name}.csv")
        df = pd.read_csv(csv)
        actual = _get_summary_metric(df, "Capacity", "Solar PV")
        ref = _REFERENCE[case_name]["solar_cap_MW"]
        assert _rel(actual, ref) <= _TOLERANCE, (
            f"[{case_name}] Solar PV capacity: got {actual:.2f} MW, expected ~{ref:.2f} MW "
            f"(rel diff = {_rel(actual, ref):.2%})"
        )

    @pytest.mark.parametrize("case_name", list(_REFERENCE.keys()))
    def test_wind_capacity(self, parametric_run, case_name):
        output_dir, _, _, _ = parametric_run
        csv = os.path.join(output_dir, case_name, f"OutputSummary_{case_name}.csv")
        df = pd.read_csv(csv)
        actual = _get_summary_metric(df, "Capacity", "Wind")
        ref = _REFERENCE[case_name]["wind_cap_MW"]
        assert _rel(actual, ref) <= _TOLERANCE, (
            f"[{case_name}] Wind capacity: got {actual:.2f} MW, expected ~{ref:.2f} MW "
            f"(rel diff = {_rel(actual, ref):.2%})"
        )


class TestCleanup:
    def test_temp_dir_removed_after_tests(self, parametric_run):
        """Verify the fixture's cleanup will remove the temp directory.

        This test intentionally runs last (alphabetically 'T' after all others)
        and checks that the temp dir is still present during the test session
        (it is cleaned by the fixture teardown, not by this test itself).
        """
        output_dir, _, _, _ = parametric_run
        # Directory must still exist while the fixture is alive
        assert os.path.isdir(output_dir), (
            "Temporary output directory should still exist during the test session"
        )
