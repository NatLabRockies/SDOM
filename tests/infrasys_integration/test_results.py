"""Tests for attaching SDOM results to infrasys systems."""

from __future__ import annotations

import logging
from dataclasses import fields

import pandas as pd
import pytest

infrasys = pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from sdom import load_data  # noqa: E402
from sdom.infrasys_integration.make_system import load_system_from_data  # noqa: E402
from sdom.infrasys_integration.models import (  # noqa: E402
    SDOMArea,
    SDOMAreaDispatchResult,
    SDOMCapacityResult,
    SDOMCostResult,
    SDOMCurtailmentResult,
    SDOMGenerationResult,
    SDOMInstalledCapacityResult,
    SDOMOptimizationResult,
    SDOMScenarioMetadata,
    SDOMSolarGenerator,
    SDOMStorage,
    SDOMStorageDispatchResult,
    SDOMThermalGenerationResult,
    SDOMThermalGenerator,
)
from sdom.infrasys_integration.results import (  # noqa: E402
    add_results_to_system,
    optimization_results_from_system,
    query_result_attributes,
)
from sdom.results import OptimizationResults  # noqa: E402

System = infrasys.System


def _sample_results(data: dict) -> OptimizationResults:
    """Build a compact OptimizationResults fixture for attachment tests."""
    plant_id = str(data["solar_plants"][0])
    storage_technology = str(data["STORAGE_SET_J_TECHS"][0])
    return OptimizationResults(
        termination_condition="optimal",
        solver_status="ok",
        total_cost=123.0,
        gen_mix_target=0.5,
        capacity={"Solar PV": 10.0, "All": 10.0},
        storage_capacity={
            "charge": {storage_technology: 2.0, "All": 2.0},
            "discharge": {storage_technology: 3.0, "All": 3.0},
            "energy": {storage_technology: 4.0, "All": 4.0},
        },
        generation_totals={"Solar PV": 20.0, "All": 20.0},
        cost_breakdown={"capex": {"Solar PV": 30.0, "All": 30.0}, "imports_cost": 0.0},
        generation_df=pd.DataFrame(
            {
                "Scenario": ["case-a", "case-a"],
                "Hour": [1, 2],
                "Solar PV Generation (MW)": [1.0, 2.0],
                "Solar PV Curtailment (MW)": [0.5, 0.25],
                "Wind Generation (MW)": [0.0, 0.0],
                "Wind Curtailment (MW)": [0.0, 0.0],
                "Load (MW)": [3.0, 4.0],
            }
        ),
        installed_plants_df=pd.DataFrame(
            [
                {
                    "Plant ID": plant_id,
                    "Technology": "Solar PV",
                    "Installed Capacity (MW)": 10.0,
                    "Max Capacity (MW)": 20.0,
                    "Capacity Fraction": 0.5,
                }
            ]
        ),
        storage_df=pd.DataFrame(
            {
                "Hour": [1, 2],
                "Technology": [storage_technology, storage_technology],
                "Charging power (MW)": [1.0, 0.0],
                "Discharging power (MW)": [0.0, 1.0],
                "State of charge (MWh)": [2.0, 1.0],
            }
        ),
        summary_df=pd.DataFrame(
            {
                "Metric": ["Total Cost"],
                "Technology": [None],
                "Run": [None],
                "Optimal Value": [123.0],
                "Unit": [None],
            }
        ),
        problem_info={"Number of variables": 10},
    )


def _assert_results_round_trip(actual: OptimizationResults, expected: OptimizationResults) -> None:
    """Assert that every OptimizationResults dataclass field matches."""
    for field in fields(OptimizationResults):
        actual_value = getattr(actual, field.name)
        expected_value = getattr(expected, field.name)
        _assert_payload_value_equal(actual_value, expected_value)


def _assert_payload_value_equal(actual, expected) -> None:
    """Assert equality for nested payload values containing DataFrames."""
    if isinstance(expected, pd.DataFrame):
        pd.testing.assert_frame_equal(actual, expected)
        return
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key, expected_value in expected.items():
            _assert_payload_value_equal(actual[key], expected_value)
        return
    if isinstance(expected, list):
        assert len(actual) == len(expected)
        for actual_value, expected_value in zip(actual, expected, strict=True):
            _assert_payload_value_equal(actual_value, expected_value)
        return
    assert actual == expected


def test_add_results_to_system_attaches_run_metadata_and_component_results():
    """Results should attach to scenario and relevant typed components."""
    data = load_data("Data/no_exchange_run_of_river")
    system = load_system_from_data(data)
    plant_id = str(data["solar_plants"][0])

    results = _sample_results(data)
    thermal = next(system.get_components(SDOMThermalGenerator))
    thermal_plant_id = thermal.name.removeprefix("thermal:")
    results.thermal_generation_df = pd.DataFrame({"Hour": [1, 2], thermal_plant_id: [3.0, 4.0]})

    add_results_to_system(
        system,
        results,
        run_id="run-a",
        scenario_name="baseline",
        case_name="case-a",
        metadata={"solver": "highs"},
    )

    run_attrs = query_result_attributes(system, run_id="run-a")
    assert any(isinstance(attr, SDOMScenarioMetadata) for attr in run_attrs)
    assert any(isinstance(attr, SDOMOptimizationResult) for attr in run_attrs)
    assert query_result_attributes(system, scenario_name="baseline")
    assert query_result_attributes(system, case_name="case-a")

    solar = system.get_component(SDOMSolarGenerator, f"solar:{plant_id}")
    solar_capacity = system.get_supplemental_attributes_with_component(solar, SDOMInstalledCapacityResult)
    assert [attr.installed_capacity_mw for attr in solar_capacity if attr.run_id == "run-a"] == [10.0]

    storage = next(system.get_components(SDOMStorage))
    dispatch = system.get_supplemental_attributes_with_component(storage, SDOMStorageDispatchResult)
    assert len(dispatch) == 1
    assert dispatch[0].hours == [1, 2]
    assert dispatch[0].charge_mw == [1.0, 0.0]
    assert dispatch[0].discharge_mw == [0.0, 1.0]

    generation = query_result_attributes(system, run_id="run-a", attribute_type=SDOMGenerationResult)
    assert [attr.total_mwh for attr in generation if attr.technology == "Solar PV"] == [20.0]

    thermal_generation = system.get_supplemental_attributes_with_component(thermal, SDOMThermalGenerationResult)
    assert [attr.generation_mw for attr in thermal_generation if attr.run_id == "run-a"] == [[3.0, 4.0]]

    costs = query_result_attributes(system, run_id="run-a", attribute_type=SDOMCostResult)
    assert [attr.value for attr in costs if attr.cost_type == "capex" and attr.technology == "Solar PV"] == [30.0]

    curtailment = query_result_attributes(
        system,
        run_id="run-a",
        attribute_type=SDOMCurtailmentResult,
    )
    assert [attr.total_mwh for attr in curtailment if attr.technology == "Solar PV"] == [0.75]

    area_dispatch = query_result_attributes(system, run_id="run-a", attribute_type=SDOMAreaDispatchResult)
    assert len(area_dispatch) == 1
    assert area_dispatch[0].hours == [1, 2]


def test_add_results_to_system_preserves_prior_runs_and_filters_queries():
    """Adding a new run_id should not overwrite previous result attributes."""
    data = load_data("Data/no_exchange_run_of_river")
    system = load_system_from_data(data)

    add_results_to_system(system, _sample_results(data), run_id="run-a", scenario_name="baseline")
    add_results_to_system(system, _sample_results(data), run_id="run-b", scenario_name="sensitivity")

    assert query_result_attributes(system, run_id="run-a")
    assert query_result_attributes(system, run_id="run-b")
    assert all(attr.run_id == "run-a" for attr in query_result_attributes(system, run_id="run-a"))
    assert all(
        attr.scenario_name == "sensitivity"
        for attr in query_result_attributes(system, scenario_name="sensitivity")
    )


def test_zonal_area_results_attach_to_area_components():
    """Zonal aggregate dictionaries should attach to matching area components."""
    system = load_system_from_data(load_data("Data/zonal_test"))
    results = OptimizationResults(
        is_zonal=True,
        areas=["A1"],
        area_capacity={"A1": {"Solar PV": 11.0}},
        area_generation_totals={"A1": {"Solar PV": 22.0}},
        area_cost_breakdown={"A1": {"capex": {"Solar PV": 33.0}}},
    )

    add_results_to_system(system, results, run_id="zonal-run", scenario_name="zonal")

    area = system.get_component(SDOMArea, "A1")
    area_capacity = system.get_supplemental_attributes_with_component(area, SDOMCapacityResult)
    area_generation = system.get_supplemental_attributes_with_component(area, SDOMGenerationResult)
    area_costs = system.get_supplemental_attributes_with_component(area, SDOMCostResult)

    assert [attr.value for attr in area_capacity if attr.run_id == "zonal-run" and attr.area == "A1"] == [11.0]
    assert [attr.total_mwh for attr in area_generation if attr.run_id == "zonal-run" and attr.area == "A1"] == [22.0]
    assert [
        attr.value
        for attr in area_costs
        if attr.run_id == "zonal-run" and attr.area == "A1" and attr.cost_type == "capex"
    ] == [33.0]


def test_optimization_results_from_system_reconstructs_typed_attributes():
    """Attached typed attributes should reconstruct OptimizationResults."""
    data = load_data("Data/no_exchange_run_of_river")
    expected = _sample_results(data)
    system = load_system_from_data(data)

    add_results_to_system(system, expected, run_id="run-a", case_name="case-a")

    actual = optimization_results_from_system(system, run_id="run-a", case_name="case-a")
    _assert_results_round_trip(actual, expected)


def test_optimization_results_from_system_preserves_zonal_lines_and_scenario_without_case_name():
    """Typed attributes should preserve line dictionaries and original scenario labels."""
    system = load_system_from_data(load_data("Data/zonal_test"))
    expected = OptimizationResults(
        termination_condition="optimal",
        solver_status="ok",
        is_zonal=True,
        areas=["A1"],
        lines=[{"line_id": "A1-A2", "from_area": "A1", "to_area": "A2"}],
        area_generation_df={
            "A1": pd.DataFrame(
                {
                    "Scenario": ["stored-scenario"],
                    "Hour": [1],
                    "Load (MW)": [2.0],
                }
            )
        },
    )

    add_results_to_system(system, expected, run_id="zonal-lines")

    actual = optimization_results_from_system(system, run_id="zonal-lines")
    assert actual.lines == expected.lines
    pd.testing.assert_frame_equal(actual.area_generation_df["A1"], expected.area_generation_df["A1"])


def test_missing_area_dispatch_and_curtailment_warns(caplog):
    """Missing explicit result areas should warn before skipping attachments."""
    system = load_system_from_data(load_data("Data/zonal_test"))
    results = OptimizationResults(
        is_zonal=True,
        area_generation_df={
            "missing-area": pd.DataFrame(
                {
                    "Hour": [1],
                    "Solar PV Curtailment (MW)": [0.5],
                    "Load (MW)": [2.0],
                }
            )
        },
    )
    caplog.set_level(logging.WARNING, logger="sdom.infrasys_integration.results")

    add_results_to_system(system, results, run_id="missing-area")

    assert "No SDOMArea matched dispatch result area 'missing-area'" in caplog.text
    assert "No SDOMArea matched curtailment result area 'missing-area'" in caplog.text


    """Unmatched zonal installed plants should fall back to SDOMArea owners."""
    system = load_system_from_data(load_data("Data/zonal_test"))
    expected = OptimizationResults(
        termination_condition="optimal",
        solver_status="ok",
        is_zonal=True,
        areas=["A1"],
        installed_plants_df=pd.DataFrame(
            {
                "Area": ["A1"],
                "Plant ID": ["unknown-plant"],
                "Technology": ["Solar PV"],
                "Installed Capacity (MW)": [1.0],
                "Max Capacity (MW)": [2.0],
                "Capacity Fraction": [0.5],
            }
        ),
    )

    caplog.set_level(logging.WARNING, logger="sdom.infrasys_integration.results")

    add_results_to_system(system, expected, run_id="unmatched-installed")

    assert "attaching capacity result to area 'A1'" in caplog.text
    actual = optimization_results_from_system(system, run_id="unmatched-installed")
    pd.testing.assert_frame_equal(actual.installed_plants_df, expected.installed_plants_df)
    pd.testing.assert_frame_equal(
        actual.area_installed_plants_df["A1"],
        expected.installed_plants_df.drop(columns=["Area"]),
    )


def test_storage_dispatch_requires_matching_storage_component():
    """Storage dispatch should fail fast when no SDOMStorage owner exists."""
    data = load_data("Data/no_exchange_run_of_river")
    system = load_system_from_data(data)
    results = _sample_results(data)
    results.storage_df["Technology"] = "unknown-storage"

    with pytest.raises(ValueError, match="no matching SDOMStorage component exists"):
        add_results_to_system(system, results, run_id="bad-storage")


def test_area_owned_installed_capacity_requires_area_bus():
    """Area-owned installed capacity should require a bus for that area."""
    system = System(name="area-without-bus")
    area = SDOMArea(name="A1")
    system.add_component(area)
    system.add_supplemental_attribute(area, SDOMOptimizationResult(run_id="run-a"))
    system.add_supplemental_attribute(
        area,
        SDOMInstalledCapacityResult(
            run_id="run-a",
            plant_id="unknown-plant",
            technology="Solar PV",
            installed_capacity_mw=1.0,
        ),
    )

    with pytest.raises(ValueError, match="must own at least one SDOMBus"):
        optimization_results_from_system(system, run_id="run-a")


def test_system_serializes_after_results_are_attached(tmp_path):
    """Systems with attached result attributes should round-trip through JSON."""
    data = load_data("Data/no_exchange_run_of_river")
    expected = _sample_results(data)
    system = load_system_from_data(data)
    add_results_to_system(system, expected, run_id="run-a", case_name="case-a")

    path = tmp_path / "system-with-results.json"
    system.to_json(path, overwrite=True)
    loaded = System.from_json(path)

    loaded_attrs = query_result_attributes(loaded, run_id="run-a", case_name="case-a")
    assert any(isinstance(attr, SDOMOptimizationResult) for attr in loaded_attrs)
    _assert_results_round_trip(
        optimization_results_from_system(loaded, run_id="run-a", case_name="case-a"),
        expected,
    )
