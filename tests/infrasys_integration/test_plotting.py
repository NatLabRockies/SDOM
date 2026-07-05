"""Tests for plotting SDOM infrasys System results."""

from __future__ import annotations

import matplotlib
import pandas as pd
import pytest

matplotlib.use("Agg")

pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from sdom import load_data
from sdom.infrasys_integration.make_system import load_system_from_data
from sdom.infrasys_integration.plotting import plot_system_results
from sdom.infrasys_integration.results import add_results_to_system
from sdom.results import OptimizationResults


def _single_run_summary() -> pd.DataFrame:
    """Build a compact summary table for single-run plot tests.

    Returns
    -------
    pandas.DataFrame
        Summary rows containing capacity and generation metrics.

    Examples
    --------
    >>> _single_run_summary()["Metric"].tolist()[:2]
    ['Capacity', 'Capacity']
    """
    return pd.DataFrame(
        [
            {"Metric": "Capacity", "Technology": "Thermal", "Run": None, "Optimal Value": 100.0, "Unit": "MW"},
            {"Metric": "Capacity", "Technology": "Solar PV", "Run": None, "Optimal Value": 40.0, "Unit": "MW"},
            {
                "Metric": "Total generation",
                "Technology": "Thermal",
                "Run": None,
                "Optimal Value": 2400.0,
                "Unit": "MWh",
            },
            {
                "Metric": "Total generation",
                "Technology": "Solar PV",
                "Run": None,
                "Optimal Value": 960.0,
                "Unit": "MWh",
            },
        ]
    )


def _generation_frame(*, scenario: str = "case-a", area: str | None = None) -> pd.DataFrame:
    """Build a 24-hour generation frame for plot tests.

    Parameters
    ----------
    scenario : str, default="case-a"
        Scenario label stored in the frame.
    area : str, optional
        Area label to include when building zonal frames.

    Returns
    -------
    pandas.DataFrame
        Hourly generation data with the columns consumed by SDOM plotters.

    Examples
    --------
    >>> len(_generation_frame())
    24
    """
    frame = pd.DataFrame(
        {
            "Scenario": [scenario] * 24,
            "Hour": list(range(1, 25)),
            "Solar PV Generation (MW)": [4.0] * 24,
            "Solar PV Curtailment (MW)": [0.0] * 24,
            "Wind Generation (MW)": [0.0] * 24,
            "Wind Curtailment (MW)": [0.0] * 24,
            "All Thermal Generation (MW)": [10.0] * 24,
            "Load (MW)": [14.0] * 24,
        }
    )
    if area is not None:
        frame["Area"] = area
    return frame


def _copperplate_results() -> OptimizationResults:
    """Build OptimizationResults with enough data for copperplate plots.

    Returns
    -------
    sdom.results.OptimizationResults
        Optimal copperplate result fixture.

    Examples
    --------
    >>> _copperplate_results().is_optimal
    True
    """
    return OptimizationResults(
        termination_condition="optimal",
        solver_status="ok",
        capacity={"Thermal": 100.0, "Solar PV": 40.0, "All": 140.0},
        generation_totals={"Thermal": 2400.0, "Solar PV": 960.0, "All": 3360.0},
        generation_df=_generation_frame(),
        summary_df=_single_run_summary(),
    )


def _zonal_results() -> OptimizationResults:
    """Build OptimizationResults with enough data for zonal plots.

    Returns
    -------
    sdom.results.OptimizationResults
        Optimal zonal result fixture with two areas and one transmission line.

    Examples
    --------
    >>> _zonal_results().areas
    ['A1', 'A2']
    """
    exchange_rows = [
        {
            "line_id": "L_A1_A2",
            "from_area": "A1",
            "to_area": "A2",
            "hour": hour,
            "flow_signed_MW": 5.0,
            "flow_FT_MW": 5.0,
            "flow_TF_MW": 0.0,
            "cap_FT_MW": 500.0,
            "cap_TF_MW": 500.0,
            "utilization_FT": 0.01,
            "utilization_TF": 0.0,
        }
        for hour in range(1, 25)
    ]
    return OptimizationResults(
        termination_condition="optimal",
        solver_status="ok",
        is_zonal=True,
        areas=["A1", "A2"],
        lines=[{"line_id": "L_A1_A2", "from_area": "A1", "to_area": "A2"}],
        capacity={"Thermal": 200.0, "Solar PV": 80.0, "All": 280.0},
        generation_totals={"Thermal": 4800.0, "Solar PV": 1920.0, "All": 6720.0},
        area_capacity={"A1": {"Thermal": 100.0, "Solar PV": 40.0}, "A2": {"Thermal": 100.0, "Solar PV": 40.0}},
        area_generation_totals={
            "A1": {"Thermal": 2400.0, "Solar PV": 960.0},
            "A2": {"Thermal": 2400.0, "Solar PV": 960.0},
        },
        area_storage_capacity={"A1": {"discharge": {}, "energy": {}}, "A2": {"discharge": {}, "energy": {}}},
        generation_df=_generation_frame(),
        area_generation_df={"A1": _generation_frame(area="A1"), "A2": _generation_frame(area="A2")},
        summary_df=_single_run_summary(),
        area_summary_df={"A1": _single_run_summary(), "A2": _single_run_summary()},
        interregional_exchanges_df=pd.DataFrame(exchange_rows),
    )


def test_plot_system_results_builds_copperplate_single_run_plots(tmp_path):
    """System plot wrapper should create legacy copperplate plot filenames."""
    system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
    add_results_to_system(system, _copperplate_results(), run_id="run-a")

    plot_system_results(system, run_id="run-a", output_dir=tmp_path)

    plots_dir = tmp_path / "plots"
    assert (plots_dir / "capacity_donut.png").is_file()
    assert (plots_dir / "capacity_generation_donuts.png").is_file()
    assert (plots_dir / "heatmap_VRE_Generation_(MW).png").is_file()


def test_plot_system_results_builds_zonal_single_run_plots(tmp_path):
    """System plot wrapper should create legacy and zonal plot filenames."""
    system = load_system_from_data(load_data("Data/zonal_test"))
    add_results_to_system(system, _zonal_results(), run_id="zonal-run")

    plot_system_results(system, run_id="zonal-run", output_dir=tmp_path)

    plots_dir = tmp_path / "plots"
    assert (plots_dir / "capacity_donut.png").is_file()
    assert (plots_dir / "capacity_generation_donuts.png").is_file()
    assert (plots_dir / "area_generation_stacks.png").is_file()
    assert (plots_dir / "area_capacity_stacks.png").is_file()
    assert (plots_dir / "line_flow_heatmap.png").is_file()


def test_plot_system_results_warns_when_summary_inputs_are_missing(tmp_path, caplog):
    """System plot wrapper should keep empty legacy summary columns."""
    system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
    add_results_to_system(
        system,
        OptimizationResults(termination_condition="optimal", solver_status="ok"),
        run_id="empty-run",
    )

    plot_system_results(system, run_id="empty-run", output_dir=tmp_path)

    assert "no capacity, storage, or generation totals" in caplog.text


def test_plot_system_results_requires_existing_run(tmp_path):
    """System plot wrapper should fail clearly when a run is missing."""
    system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))

    with pytest.raises(ValueError, match="No SDOMOptimizationResult"):
        plot_system_results(system, run_id="missing", output_dir=tmp_path)
