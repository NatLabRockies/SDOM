"""Tests for attaching SDOM results to infrasys systems."""

from __future__ import annotations

import pandas as pd
import pytest

infrasys = pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from sdom import load_data  # noqa: E402
from sdom.infrasys_integration.make_system import load_system_from_data  # noqa: E402
from sdom.infrasys_integration.models import (  # noqa: E402
    SDOMCapacityResult,
    SDOMCurtailmentResult,
    SDOMOptimizationResult,
    SDOMScenarioMetadata,
    SDOMSolarGenerator,
    SDOMStorage,
    SDOMStorageDispatchResult,
)
from sdom.infrasys_integration.results import add_results_to_system, query_result_attributes  # noqa: E402
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
                "Scenario": ["case", "case"],
                "Hour": [1, 2],
                "Solar PV Curtailment (MW)": [0.5, 0.25],
                "Wind Curtailment (MW)": [0.0, 0.0],
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
    )


def test_add_results_to_system_attaches_run_metadata_and_component_results():
    """Results should attach to scenario and relevant typed components."""
    data = load_data("Data/no_exchange_run_of_river")
    system = load_system_from_data(data)
    plant_id = str(data["solar_plants"][0])

    add_results_to_system(
        system,
        _sample_results(data),
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
    solar_capacity = system.get_supplemental_attributes_with_component(solar, SDOMCapacityResult)
    assert [attr.value for attr in solar_capacity if attr.run_id == "run-a"] == [10.0]

    storage = next(system.get_components(SDOMStorage))
    dispatch = system.get_supplemental_attributes_with_component(storage, SDOMStorageDispatchResult)
    assert len(dispatch) == 1
    assert dispatch[0].charge_mw == [1.0, 0.0]
    assert dispatch[0].discharge_mw == [0.0, 1.0]

    curtailment = query_result_attributes(
        system,
        run_id="run-a",
        attribute_type=SDOMCurtailmentResult,
    )
    assert [attr.total_mwh for attr in curtailment if attr.technology == "Solar PV"] == [0.75]


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


def test_system_serializes_after_results_are_attached(tmp_path):
    """Systems with attached result attributes should round-trip through JSON."""
    data = load_data("Data/no_exchange_run_of_river")
    system = load_system_from_data(data)
    add_results_to_system(system, _sample_results(data), run_id="run-a", case_name="case-a")

    path = tmp_path / "system-with-results.json"
    system.to_json(path, overwrite=True)
    loaded = System.from_json(path)

    loaded_attrs = query_result_attributes(loaded, run_id="run-a", case_name="case-a")
    assert any(isinstance(attr, SDOMOptimizationResult) for attr in loaded_attrs)
