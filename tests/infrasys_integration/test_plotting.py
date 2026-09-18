"""Tests for plotting SDOM infrasys System results."""

from __future__ import annotations

import matplotlib
import pandas as pd
import pytest

matplotlib.use("Agg")

pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from sdom import load_data
from sdom.infrasys_integration import plot_system_parametric_results
from sdom.infrasys_integration.make_system import load_system_from_data
from sdom.infrasys_integration.parametric import SystemParametricStudy, add_parametric_results_to_system
from sdom.infrasys_integration.plotting import (  # noqa: E402
    _ensure_single_plot_summary,
    _system_parametric_plot_data,
    plot_system_results,
)
from sdom.infrasys_integration.models import SDOMScenarioMetadata
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
            {"Metric": "Total VRE curtailment", "Technology": "All", "Run": None, "Optimal Value": 10.0, "Unit": "MWh"},
            {"Metric": "VRE curtailment percentage", "Technology": "All", "Run": None, "Optimal Value": 1.0, "Unit": "%"},
            {"Metric": "CAPEX", "Technology": "Thermal", "Run": None, "Optimal Value": 1000.0, "Unit": "USD"},
            {"Metric": "OPEX", "Technology": "Thermal", "Run": None, "Optimal Value": 100.0, "Unit": "USD"},
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


def test_plot_system_parametric_results_builds_chunked_sensitivity_plots(tmp_path):
    """System parametric plot wrapper should rebuild every attached case."""
    system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
    study = SystemParametricStudy(system, solver_config={})
    study._study._case_metadata = [
        {"case_name": "GenMix_Target=0.8", "case_index": 0, "GenMix_Target": 0.8},
        {"case_name": "GenMix_Target=1.0", "case_index": 1, "GenMix_Target": 1.0},
    ]
    add_parametric_results_to_system(
        system,
        study,
        results=[_copperplate_results(), _copperplate_results()],
        run_id="param-run",
    )

    plot_system_parametric_results(
        system,
        run_id="param-run",
        group_by="GenMix_Target",
        output_dir=tmp_path,
        max_cases_per_figure=1,
    )

    sensitivity_dir = tmp_path / "sensitivity_plots"
    for plot_name in (
        "capacity_comparison",
        "generation_comparison",
        "cost_comparison",
        "curtailment_absolute",
        "curtailment_percentage",
    ):
        assert (sensitivity_dir / f"{plot_name}_part1.png").is_file()
        assert (sensitivity_dir / f"{plot_name}_part2.png").is_file()


def test_plot_system_parametric_results_builds_zonal_per_case_plots(tmp_path):
    """System parametric plots should support reconstructed zonal cases."""
    system = load_system_from_data(load_data("Data/zonal_test"))
    study = SystemParametricStudy(system, solver_config={})
    study._study._case_metadata = [
        {"case_name": "GenMix_Target=0.8", "case_index": 0, "GenMix_Target": 0.8},
        {"case_name": "GenMix_Target=1.0", "case_index": 1, "GenMix_Target": 1.0},
    ]
    add_parametric_results_to_system(
        system,
        study,
        results=[_zonal_results(), _zonal_results()],
        run_id="zonal-param-run",
    )
    _, reconstructed_results = _system_parametric_plot_data(system, run_id="zonal-param-run")
    _ensure_single_plot_summary(reconstructed_results[0])

    curtailment_percentage = reconstructed_results[0].summary_df.loc[
        (reconstructed_results[0].summary_df["Metric"] == "VRE curtailment percentage")
        & (reconstructed_results[0].summary_df["Technology"] == "All"),
        "Optimal Value",
    ].item()
    assert curtailment_percentage == pytest.approx(20.0 / 1940.0 * 100.0)

    plot_system_parametric_results(
        system,
        run_id="zonal-param-run",
        group_by="GenMix_Target",
        output_dir=tmp_path,
    )

    assert (tmp_path / "GenMix_Target=0.8" / "plots" / "capacity_donut.png").is_file()
    assert (tmp_path / "sensitivity_plots" / "capacity_comparison.png").is_file()


def test_plot_system_parametric_results_requires_existing_run(tmp_path):
    """System parametric plot wrapper should fail clearly when a run is missing."""
    system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))

    with pytest.raises(ValueError, match="No SDOMScenarioMetadata"):
        plot_system_parametric_results(
            system,
            run_id="missing",
            group_by="GenMix_Target",
            output_dir=tmp_path,
        )


def test_system_parametric_plot_data_requires_non_empty_run_id():
    """Parametric plot reconstruction should reject an empty run identifier."""
    system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))

    with pytest.raises(ValueError, match="run_id must be a non-empty string"):
        _system_parametric_plot_data(system, run_id="")


def test_system_parametric_plot_data_requires_scenario_identity(monkeypatch):
    """Parametric plot reconstruction should require stored scenario identity."""
    system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
    metadata = SDOMScenarioMetadata(
        run_id="param-run",
        case_name="case-without-identity",
        scenario_name="",
        metadata={"case_index": 0},
    )
    monkeypatch.setattr(
        "sdom.infrasys_integration.plotting.query_result_attributes",
        lambda *args, **kwargs: [metadata],
    )

    with pytest.raises(ValueError, match="has no scenario identifier"):
        _system_parametric_plot_data(system, run_id="param-run")


def test_system_parametric_plot_data_orders_case_specific_reconstructions(monkeypatch):
    """Parametric plot reconstruction should sort metadata and fetch each case."""
    system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
    later_case = SDOMScenarioMetadata(
        run_id="param-run",
        case_name="later",
        scenario_name="stored-later",
        metadata={"case_index": 2, "sweep_values": {"GenMix_Target": 1.0}},
    )
    first_case = SDOMScenarioMetadata(
        run_id="param-run",
        case_name="first",
        scenario_name="stored-first",
        metadata={"case_index": 1, "scenario_id": "metadata-first", "sweep_values": {"GenMix_Target": 0.8}},
    )
    reconstructed_results = {
        "metadata-first": OptimizationResults(total_cost=80.0, capacity={"Solar PV": 8.0}),
        "stored-later": OptimizationResults(total_cost=100.0, capacity={"Solar PV": 10.0}),
    }
    monkeypatch.setattr(
        "sdom.infrasys_integration.plotting.query_result_attributes",
        lambda *args, **kwargs: [later_case, first_case],
    )
    monkeypatch.setattr(
        "sdom.infrasys_integration.plotting.optimization_results_from_system",
        lambda _system, *, run_id, scenario_name: reconstructed_results[scenario_name],
    )

    study, results = _system_parametric_plot_data(system, run_id="param-run")

    assert [case["case_name"] for case in study.case_metadata] == ["first", "later"]
    assert [case["GenMix_Target"] for case in study.case_metadata] == [0.8, 1.0]
    assert [result.total_cost for result in results] == [80.0, 100.0]
    assert [result.capacity["Solar PV"] for result in results] == [8.0, 10.0]
