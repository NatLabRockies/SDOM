"""Tests for attaching SDOM results to infrasys systems."""

from __future__ import annotations

import logging
from dataclasses import fields
from pathlib import Path

import pandas as pd
import pytest

infrasys = pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from test_curtailment_costs import METRICS, RATES, TECHNOLOGIES, assign_dispatch, collect, cost_data  # noqa: E402
from test_hydro_curtailment_results import _hydro_rows, _reporting_data  # noqa: E402

from sdom import export_results, get_default_solver_config_dict, load_data, run_solver  # noqa: E402
from sdom.infrasys_integration.make_system import load_system_from_data  # noqa: E402
from sdom.infrasys_integration.models import (  # noqa: E402
    SDOMArea,
    SDOMAreaDispatchResult,
    SDOMCapacityResult,
    SDOMCostResult,
    SDOMCurtailmentResult,
    SDOMGenerationResult,
    SDOMInstalledCapacityResult,
    SDOMInterregionalExchangeResult,
    SDOMOptimizationResult,
    SDOMScenarioMetadata,
    SDOMSolarGenerator,
    SDOMStorage,
    SDOMStorageDispatchResult,
    SDOMSummaryMetricResult,
    SDOMThermalGenerationResult,
    SDOMThermalGenerator,
)
from sdom.infrasys_integration.pyomo_builder import initialize_model_from_system  # noqa: E402
from sdom.infrasys_integration.results import (  # noqa: E402
    add_results_to_system,
    optimization_results_from_system,
    query_result_attributes,
)
from sdom.results import OptimizationResults  # noqa: E402

System = infrasys.System


@pytest.mark.parametrize("zonal", [False, True])
@pytest.mark.parametrize("signed", [False, True])
def test_curtailment_costs_forward_through_system_and_persist_without_new_fields(tmp_path, zonal, signed):
    rates = tuple(zip(RATES, (-5, 10, -20) if signed else (5, 10, 20), strict=True))
    system = load_system_from_data(cost_data(rates=rates, zonal=zonal))
    model = initialize_model_from_system(system, n_hours=24).create_instance()
    assign_dispatch(model)
    results = collect(model)
    expected = dict(zip(TECHNOLOGIES, (-240, 720, -2880) if signed else (240, 720, 2880), strict=True))
    if zonal:
        expected = dict(zip(TECHNOLOGIES, (-480, 1440, -15360) if signed else (480, 1440, 15360), strict=True))
    assert results.cost_breakdown["curtailment_cost"] == expected

    add_results_to_system(system, results, run_id="curtailment")
    costs = query_result_attributes(system, run_id="curtailment", attribute_type=SDOMCostResult)
    system_costs = {
        attr.technology: attr.value
        for attr in costs
        if isinstance(attr, SDOMCostResult) and attr.cost_type == "curtailment_cost" and attr.area is None
    }
    assert system_costs == expected
    path = tmp_path / "curtailment.json"
    system.to_json(path, overwrite=True)
    reconstructed = optimization_results_from_system(System.from_json(path), run_id="curtailment")
    assert reconstructed.cost_breakdown == results.cost_breakdown
    assert reconstructed.area_cost_breakdown == results.area_cost_breakdown
    pd.testing.assert_frame_equal(reconstructed.summary_df, results.summary_df)
    for area, summary in results.area_summary_df.items():
        pd.testing.assert_frame_equal(reconstructed.area_summary_df[area], summary)
    export_results(reconstructed, case="curtailment", output_dir=str(tmp_path))
    exported = pd.read_csv(tmp_path / "OutputSummary_curtailment.csv")
    assert exported.loc[exported["Metric"].isin(METRICS), "Optimal Value"].tolist() == list(expected.values())


def test_legacy_cost_dictionary_without_curtailment_survives_round_trip(tmp_path):
    system = load_system_from_data(load_data(str(Path(__file__).resolve().parents[2] / "Data" / "no_exchange_run_of_river")))
    results = OptimizationResults(cost_breakdown={"capex": {"Solar PV": 12.0}})
    add_results_to_system(system, results, run_id="legacy-costs")
    path = tmp_path / "legacy-costs.json"
    system.to_json(path, overwrite=True)
    restored = optimization_results_from_system(System.from_json(path), run_id="legacy-costs")
    assert restored.cost_breakdown == results.cost_breakdown
    assert restored.summary_df.empty


@pytest.mark.parametrize("zonal", [False, True], ids=["copperplate", "zonal"])
def test_long_thermal_dispatch_round_trip_preserves_ownership_single_plants_and_zeros(tmp_path, zonal):
    system = load_system_from_data(load_data("Data/zonal_test" if zonal else "Data/no_exchange_run_of_river"))
    selected = {}
    for thermal in system.get_components(SDOMThermalGenerator):
        area = thermal.bus.area.name if zonal else "copperplate"
        selected.setdefault(area, thermal)
    rows = [
        {"Hour": hour, "Area": area, "Plant ID": plant.name.removeprefix("thermal:"), "Generation (MW)": 0.0}
        for area, plant in selected.items()
        for hour in (1, 2)
    ]
    expected = pd.DataFrame(rows)
    results = OptimizationResults(
        is_zonal=zonal, areas=list(selected) if zonal else [], thermal_generation_df=expected
    )
    add_results_to_system(system, results, run_id="thermal")
    attributes = query_result_attributes(system, run_id="thermal", attribute_type=SDOMThermalGenerationResult)
    assert len(attributes) == len(selected)
    assert all(attribute.hours == [1, 2] and attribute.generation_mw == [0.0, 0.0] for attribute in attributes)
    path = tmp_path / "thermal.json"
    system.to_json(path, overwrite=True)
    restored = optimization_results_from_system(System.from_json(path), run_id="thermal")
    keys = ["Area", "Hour", "Plant ID"]
    pd.testing.assert_frame_equal(
        restored.thermal_generation_df.sort_values(keys).reset_index(drop=True),
        expected.sort_values(keys).reset_index(drop=True),
    )
    if zonal:
        assert set(restored.area_thermal_generation_df) == set(selected)
        for area, frame in restored.area_thermal_generation_df.items():
            assert list(frame.columns) == ["Hour", "Plant ID", "Generation (MW)"]
            assert set(frame["Plant ID"]) == {selected[area].name.removeprefix("thermal:")}


@pytest.mark.parametrize(
    ("invalid", "message"),
    [
        ("nan", "missing values"),
        ("infinity", "finite generation"),
        ("duplicate", "one row per hour"),
        ("wrong-area", "does not belong"),
        ("unknown-plant", "No SDOM thermal generator"),
        ("missing-column", "missing columns"),
    ],
)
def test_long_thermal_dispatch_rejects_invalid_attachment(invalid, message):
    system = load_system_from_data(load_data("Data/zonal_test"))
    plant = next(system.get_components(SDOMThermalGenerator))
    frame = pd.DataFrame(
        {
            "Hour": [1],
            "Area": [plant.bus.area.name],
            "Plant ID": [plant.name.removeprefix("thermal:")],
            "Generation (MW)": [0.0],
        }
    )
    if invalid == "nan":
        frame["Generation (MW)"] = float("nan")
    elif invalid == "infinity":
        frame["Generation (MW)"] = float("inf")
    elif invalid == "duplicate":
        frame = pd.concat([frame, frame], ignore_index=True)
    elif invalid == "wrong-area":
        frame["Area"] = "not-the-owning-area"
    elif invalid == "unknown-plant":
        frame["Plant ID"] = "not-a-plant"
    else:
        frame = frame.drop(columns="Area")
    with pytest.raises(ValueError, match=message):
        add_results_to_system(system, OptimizationResults(thermal_generation_df=frame), run_id="invalid")


@pytest.mark.parametrize("zonal", [False, True], ids=["copperplate", "zonal"])
@pytest.mark.parametrize(
    ("formulation", "hours"),
    [("DailyBudgetUpperBoundFormulation", 24), ("MonthlyBudgetUpperBoundFormulation", 730)],
)
def test_hydro_summary_from_system_solve_survives_serialization_and_export(
    tmp_path, formulation, *, hours, zonal
):
    """Persist full solved results, including zonal thermal dispatch and hydro."""
    system = load_system_from_data(_reporting_data(formulation, zonal=zonal))
    model = initialize_model_from_system(system, n_hours=hours).create_instance()
    config = get_default_solver_config_dict(solver_name="highs", executable_path="")
    config["solve_keywords"].update(tee=False, report_timing=False, keepfiles=False)

    results = run_solver(model, config)
    assert results.is_optimal
    expected = _hydro_rows(results.summary_df)
    assert expected["Technology"].tolist() == ["Hydro", "Hydro"]
    assert expected["Unit"].tolist() == ["TWh", "%"]
    assert expected["Optimal Value"].gt(0).all()

    add_results_to_system(system, results, run_id="hydro")
    path = tmp_path / "hydro.json"
    system.to_json(path, overwrite=True)
    restored = System.from_json(path)
    attributes = query_result_attributes(restored, run_id="hydro", attribute_type=SDOMSummaryMetricResult)
    hydro_attributes = {
        attribute.metric: attribute
        for attribute in attributes
        if attribute.technology == "Hydro" and attribute.metric in expected["Metric"].values
    }
    assert set(hydro_attributes) == {"Total Hydro curtailment", "Hydro curtailment percentage"}
    assert all(attribute.scope == "system" for attribute in hydro_attributes.values())
    assert hydro_attributes["Total Hydro curtailment"].unit == "TWh"
    assert hydro_attributes["Hydro curtailment percentage"].unit == "%"

    reconstructed = optimization_results_from_system(restored, run_id="hydro")
    pd.testing.assert_frame_equal(_hydro_rows(reconstructed.summary_df), expected)
    keys = ["Area", "Hour", "Plant ID"]
    pd.testing.assert_frame_equal(
        reconstructed.thermal_generation_df.sort_values(keys).reset_index(drop=True),
        results.thermal_generation_df.sort_values(keys).reset_index(drop=True),
    )
    export_results(reconstructed, case="hydro", output_dir=str(tmp_path))
    exported = pd.read_csv(tmp_path / "OutputSummary_hydro.csv")
    pd.testing.assert_frame_equal(_hydro_rows(exported), expected)


def test_zonal_summary_round_trip_distinguishes_system_and_area_scopes(tmp_path):
    system = load_system_from_data(load_data("Data/zonal_test"))
    system_summary = pd.DataFrame(
        {
            "Metric": ["Total Hydro curtailment", "Hydro curtailment percentage"],
            "Technology": ["Hydro", "Hydro"],
            "Run": [1, 1],
            "Optimal Value": [6.0, 25.0],
            "Unit": ["TWh", "%"],
        }
    )
    area_summary = pd.DataFrame(
        {"Metric": ["Capacity"], "Technology": ["Thermal"], "Run": [1], "Optimal Value": [10.0], "Unit": ["MW"]}
    )
    results = OptimizationResults(
        is_zonal=True, areas=["A1", "A2"], summary_df=system_summary, area_summary_df={"A1": area_summary}
    )
    add_results_to_system(system, results, run_id="scoped")
    path = tmp_path / "scoped.json"
    system.to_json(path, overwrite=True)

    reconstructed = optimization_results_from_system(System.from_json(path), run_id="scoped")

    pd.testing.assert_frame_equal(reconstructed.summary_df, system_summary)
    assert set(reconstructed.area_summary_df) == {"A1"}
    pd.testing.assert_frame_equal(reconstructed.area_summary_df["A1"], area_summary)


def test_legacy_summary_without_explicit_scope_keeps_owner_based_area(tmp_path):
    system = load_system_from_data(load_data("Data/zonal_test"))
    add_results_to_system(system, OptimizationResults(is_zonal=True, areas=["A1", "A2"]), run_id="legacy")
    attribute = SDOMSummaryMetricResult(
        run_id="legacy", row_order=0, metric="Capacity", technology="Thermal", optimal_value=10.0, unit="MW"
    )
    system.add_supplemental_attribute(system.get_component(SDOMArea, "A2"), attribute)

    reconstructed = optimization_results_from_system(system, run_id="legacy")

    assert reconstructed.summary_df.empty
    assert set(reconstructed.area_summary_df) == {"A2"}
    assert reconstructed.area_summary_df["A2"]["Optimal Value"].tolist() == [10.0]
    path = tmp_path / "legacy.json"
    system.to_json(path, overwrite=True)
    restored = optimization_results_from_system(System.from_json(path), run_id="legacy")
    assert restored.summary_df.empty
    pd.testing.assert_frame_equal(restored.area_summary_df["A2"], reconstructed.area_summary_df["A2"])


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
    results.thermal_generation_df = pd.DataFrame(
        {
            "Hour": [1, 2],
            "Area": ["copperplate", "copperplate"],
            "Plant ID": [thermal_plant_id, thermal_plant_id],
            "Generation (MW)": [3.0, 4.0],
        }
    )

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


def test_unmatched_zonal_installed_capacity_preserves_area_owner(caplog):
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


def test_interregional_exchange_results_missing_columns_warns(caplog):
    """Incomplete interregional exchange frames should warn and skip attachment."""
    system = load_system_from_data(load_data("Data/zonal_test"))
    results = OptimizationResults(
        is_zonal=True,
        interregional_exchanges_df=pd.DataFrame({"line_id": ["A1-A2"], "hour": [1]}),
    )
    caplog.set_level(logging.WARNING, logger="sdom.infrasys_integration.results")

    add_results_to_system(system, results, run_id="missing-exchange-columns")

    assert "Interregional exchange results are missing required columns" in caplog.text
    assert query_result_attributes(system, run_id="missing-exchange-columns", attribute_type=SDOMInterregionalExchangeResult) == []


def test_storage_dispatch_unknown_technology_leaves_system_unmodified():
    """Storage dispatch should fail fast when no SDOMStorage owner exists."""
    data = load_data("Data/no_exchange_run_of_river")
    system = load_system_from_data(data)
    results = _sample_results(data)
    results.storage_df["Technology"] = "unknown-storage"

    with pytest.raises(ValueError, match="no matching SDOMStorage component exists"):
        add_results_to_system(system, results, run_id="bad-storage")

    assert query_result_attributes(system, run_id="bad-storage") == []


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
