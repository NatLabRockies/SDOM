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