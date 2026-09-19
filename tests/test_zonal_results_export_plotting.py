"""Regression tests for zonal result exports and standard plotting."""

from __future__ import annotations

import os
import shutil

import matplotlib

matplotlib.use("Agg")

import pandas as pd
import pyomo.environ as pyo
import pytest

from sdom import export_results, initialize_model, load_data
from sdom.analytic_tools import plot_parametric_results, plot_results
from sdom.optimization_main import get_default_solver_config_dict, run_solver
from sdom.parametric import ParametricStudy
from sdom.results import OptimizationResults


REL_ZONAL_FIXTURE = "Data/zonal_test"
N_HOURS = 24


def _abs_data_path(rel: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", rel))


def _highs_available() -> bool:
    for name in ("appsi_highs", "highs"):
        try:
            solver = pyo.SolverFactory(name)
            if solver is not None and solver.available(exception_flag=False):
                return True
        except Exception:
            continue
    return False


def _solver_config() -> dict:
    config = get_default_solver_config_dict(solver_name="highs")
    config["solve_keywords"].update(
        tee=False, report_timing=False, keepfiles=False
    )
    return config


def _load_zonal_data_without_optional_assets(tmp_path) -> dict:
    """Load a zonal case where A1 has demand and transmission only."""
    fixture_path = tmp_path / "zonal_data"
    shutil.copytree(_abs_data_path(REL_ZONAL_FIXTURE), fixture_path)

    scalars_path = fixture_path / "scalars.csv"
    scalars = pd.read_csv(scalars_path)
    scalars.loc[scalars["Parameter"] == "GenMix_Target", "Value"] = 0.0
    scalars.to_csv(scalars_path, index=False)

    for filename in ("Data_BalancingUnits.csv", "CapSolar.csv", "CapWind.csv"):
        path = fixture_path / filename
        data = pd.read_csv(path)
        data[data["area_id"] != "A1"].to_csv(path, index=False)

    balancing_units_path = fixture_path / "Data_BalancingUnits.csv"
    balancing_units = pd.read_csv(balancing_units_path)
    balancing_units.loc[balancing_units["area_id"] == "A2", "MaxCapacity"] = 100_000.0
    balancing_units.to_csv(balancing_units_path, index=False)

    for filename in ("LineCap_FT.csv", "LineCap_TF.csv"):
        path = fixture_path / filename
        line_capacities = pd.read_csv(path)
        line_capacities.loc[:, line_capacities.columns != "*Hour"] = 100_000.0
        line_capacities.to_csv(path, index=False)

    for filename in (
        "lahy_hourly.csv",
        "Nucl_hourly.csv",
        "otre_hourly.csv",
        "StorageData.csv",
    ):
        path = fixture_path / filename
        data = pd.read_csv(path)
        data.loc[:, ~data.columns.str.endswith("@A1@")].to_csv(path, index=False)

    return load_data(str(fixture_path))


pytestmark = pytest.mark.skipif(
    not _highs_available(), reason="HiGHS solver not available"
)


def test_zonal_system_export_and_standard_heatmap_use_hourly_aggregate(
    tmp_path, monkeypatch
):
    """Standard zonal outputs aggregate by hour while retaining area detail."""
    result = OptimizationResults(
        termination_condition="optimal",
        is_zonal=True,
        generation_df=pd.DataFrame(
            {
                "Area": ["A1", "A2", "A1", "A2"],
                "Scenario": ["run"] * 4,
                "Hour": [2, 2, 1, 1],
                "Load (MW)": [40.0, 60.0, 50.0, 50.0],
                "Solar PV Generation (MW)": [5.0, 10.0, 0.0, 20.0],
            }
        ),
    )
    captured_heatmap_frames = []

    from sdom.analytic_tools import _single

    monkeypatch.setattr(_single, "_plot_capacity_donut", lambda *_args: None)
    monkeypatch.setattr(
        _single, "_plot_capacity_generation_donuts", lambda *_args: None
    )
    monkeypatch.setattr(
        _single,
        "_plot_heatmaps",
        lambda frame, _plots_dir: captured_heatmap_frames.append(frame.copy()),
    )

    export_results(result, "zonal_system", output_dir=str(tmp_path))
    plot_results(result, plots_dir=str(tmp_path / "plots"))

    system_export = pd.read_csv(tmp_path / "OutputGeneration_zonal_system.csv")
    per_area_export = pd.read_csv(
        tmp_path / "OutputGenerationPerArea_zonal_system.csv"
    )
    assert list(system_export["Hour"]) == [1, 2]
    assert list(system_export["Load (MW)"]) == [100.0, 100.0]
    assert list(system_export["Solar PV Generation (MW)"]) == [20.0, 15.0]
    assert len(per_area_export) == 4
    assert "Area" in per_area_export.columns
    assert len(captured_heatmap_frames) == 1
    assert list(captured_heatmap_frames[0]["Hour"]) == [1, 2]
    assert "Area" not in captured_heatmap_frames[0].columns


def test_zonal_full_year_heatmap_receives_365_day_system_chronology(
    tmp_path, monkeypatch
):
    """Standard heatmaps receive one 8,760-hour system series, not area blocks."""
    hours = list(range(1, 8761))
    generation_df = pd.concat(
        [
            pd.DataFrame(
                {
                    "Area": area,
                    "Hour": hours,
                    "Load (MW)": 100.0,
                    "Solar PV Generation (MW)": solar_generation,
                }
            )
            for area, solar_generation in (("A1", 20.0), ("A2", 10.0))
        ],
        ignore_index=True,
    )
    result = OptimizationResults(
        termination_condition="optimal",
        is_zonal=True,
        generation_df=generation_df,
    )

    from sdom.analytic_tools import _single

    monkeypatch.setattr(_single, "_plot_capacity_donut", lambda *_args: None)
    monkeypatch.setattr(
        _single, "_plot_capacity_generation_donuts", lambda *_args: None
    )
    captured_day_counts = []
    monkeypatch.setattr(
        _single,
        "_plot_heatmaps",
        lambda frame, _plots_dir: captured_day_counts.append(len(frame) // 24),
    )

    plot_results(result, plots_dir=str(tmp_path / "plots"))

    assert captured_day_counts == [365]


def test_zonal_no_optional_assets_exports_summary_and_standard_plots(tmp_path):
    """A demand-and-line-only area supports result export and standard plots."""
    data = _load_zonal_data_without_optional_assets(tmp_path)
    result = run_solver(
        initialize_model(data, n_hours=N_HOURS),
        _solver_config(),
        case_name="no_optional_assets",
    )

    assert result.is_optimal
    assert not result.summary_df.empty

    output_dir = tmp_path / "single"
    export_results(result, "no_optional_assets", output_dir=str(output_dir))
    plot_results(result, output_dir=str(output_dir))

    expected_files = (
        output_dir / "OutputGeneration_no_optional_assets.csv",
        output_dir / "OutputSummary_no_optional_assets.csv",
        output_dir / "OutputInterregionalExchanges_no_optional_assets.csv",
        output_dir / "plots" / "capacity_donut.png",
        output_dir / "plots" / "capacity_generation_donuts.png",
    )
    for path in expected_files:
        assert path.is_file() and path.stat().st_size > 0, path


def test_zonal_no_optional_assets_parametric_exports_and_sensitivity_plots(tmp_path):
    """Zonal parametric cases export summaries and generate sensitivity plots."""
    data = _load_zonal_data_without_optional_assets(tmp_path)
    output_dir = tmp_path / "parametric"
    study = ParametricStudy(
        base_data=data,
        solver_config=_solver_config(),
        n_hours=N_HOURS,
        output_dir=str(output_dir),
        n_cores=1,
    )
    study.add_scalar_sweep("scalars", "r", [0.04, 0.08])

    results = study.run()
    assert len(results) == 2
    assert all(result.is_optimal for result in results)
    assert all(not result.summary_df.empty for result in results)

    plot_parametric_results(
        study,
        results,
        group_by="r",
        output_dir=str(output_dir),
    )

    for metadata in study.case_metadata:
        case_dir = output_dir / metadata["case_name"]
        summary_csv = case_dir / f"OutputSummary_{metadata['case_name']}.csv"
        donut_png = case_dir / "plots" / "capacity_donut.png"
        assert summary_csv.is_file() and summary_csv.stat().st_size > 0
        assert donut_png.is_file() and donut_png.stat().st_size > 0

    sensitivity_dir = output_dir / "sensitivity_plots"
    sensitivity_plots = list(sensitivity_dir.glob("*.png"))
    assert sensitivity_plots
    assert all(path.stat().st_size > 0 for path in sensitivity_plots)