"""Hourly thermal minimum-dispatch contracts."""

import copy
import logging
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pyomo.environ import Constraint, SolverFactory, Var, value

from sdom import initialize_model, load_data
from sdom.io_manager import get_formulation, get_network_formulation, validate_thermal_min_dispatch

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "thermal_min_dispatch_fraction"
FILENAME = "Thermal_MinDispatchFraction.csv"
NEW = "NoRampsMinDispatchFormulation"
OLD = "NoRampsDispatchFormulation"


def enable(data, *, hours=4, fraction=0.25):
    rows = data["formulations"]["Component"].str.lower() == "thermal"
    data["formulations"].loc[rows, "Formulation"] = NEW
    data[PROFILE] = pd.DataFrame(
        {
            "Hour": np.arange(1, hours + 1),
            **{str(k): np.full(hours, fraction) for k in data["thermal_data"]["Plant_id"]},
        }
    )
    return data


@pytest.fixture
def data():
    return enable(load_data(str(ROOT / "Data" / "no_exchange_run_of_river")))


def test_thermal_selection_defaults_and_preserves_other_lookup(data):
    data["formulations"] = data["formulations"].loc[
        data["formulations"]["Component"].str.lower() != "thermal"
    ]
    assert get_formulation(data, "Thermal") == OLD
    data["formulations"] = pd.DataFrame({"Component": ["Hydro", "hydro"], "Formulation": ["a", "b"]})
    assert get_formulation(data) == "a"


@pytest.mark.parametrize("selection", ["", None, np.nan, pd.NA, "typo", NEW.lower()])
def test_invalid_thermal_selection_fails(data, selection):
    data["formulations"].loc[data["formulations"]["Component"].str.lower() == "thermal", "Formulation"] = (
        selection
    )
    with pytest.raises(
        ValueError, match=r"Thermal.*NoRampsDispatchFormulation.*NoRampsMinDispatchFormulation"
    ):
        initialize_model(data, n_hours=2)


def test_duplicate_thermal_selection_fails(data):
    data["formulations"].loc[len(data["formulations"])] = ["tHeRmAl", OLD, "duplicate"]
    with pytest.raises(ValueError, match=r"Thermal.*duplicate"):
        get_formulation(data, "Thermal")


@pytest.mark.parametrize(
    ("component", "expected"), [("tHeRmAl", OLD), ("NETWORK", "CopperPlateNetwork"), ("Reserves", "notModel")]
)
def test_generic_lookup_uses_registered_defaults(component, expected):
    data = {"formulations": pd.DataFrame(columns=["Component", "Formulation"])}
    assert get_formulation(data, component) == expected
    assert get_formulation(data, component, default="explicit") == "explicit"
    assert get_formulation(data, component, default=None) is None


@pytest.mark.parametrize("component", ["Hydro", "Imports", "Exports", "Unknown"])
def test_generic_lookup_does_not_invent_defaults(component):
    data = {"formulations": pd.DataFrame(columns=["Component", "Formulation"])}
    with pytest.raises(IndexError):
        get_formulation(data, component)


@pytest.mark.parametrize("selection", ["", None, "typo"])
def test_generic_lookup_rejects_invalid_thermal_rows_without_falling_back(selection):
    data = {"formulations": pd.DataFrame({"Component": ["Thermal"], "Formulation": [selection]})}
    with pytest.raises(ValueError, match=r"Thermal.*supported choices"):
        get_formulation(data, "Thermal", default=OLD)


def test_network_accessor_remains_compatible():
    data = {"formulations": pd.DataFrame(columns=["Component", "Formulation"])}
    assert get_network_formulation(data) == get_formulation(data, "Network")


def test_profiled_thermal_builder_includes_floor_construction(data, monkeypatch):
    from sdom import optimization_main

    original = optimization_main.add_thermal_constraints

    def checked_builder(host):
        original(host)
        assert hasattr(host.thermal, "min_dispatch_constraint")

    monkeypatch.setattr(optimization_main, "add_thermal_constraints", checked_builder)
    initialize_model(data, n_hours=2)


def test_thermal_fraction_parameter_helper_is_used(data, monkeypatch):
    from sdom.models import formulations_thermal

    original = formulations_thermal._add_thermal_min_dispatch_fraction_parameters
    seen = []

    def checked_helper(host, inputs, *, df):
        seen.append(df)
        original(host, inputs, df=df)

    monkeypatch.setattr(formulations_thermal, "_add_thermal_min_dispatch_fraction_parameters", checked_helper)
    model = initialize_model(data, n_hours=2)
    assert len(seen) == 1
    assert len(model.thermal.min_dispatch_fraction) == 2 * len(model.thermal.plants_set)


@pytest.mark.parametrize("bad", [-1e-12, 1 + 1e-12, np.inf, np.nan, "", None, True, "20%", "bad"])
def test_invalid_fraction_fails_with_cell_context(data, bad):
    plant = data["thermal_data"]["Plant_id"].astype(str).iloc[0]
    data[PROFILE][plant] = data[PROFILE][plant].astype(object)
    data[PROFILE].loc[0, plant] = bad
    with pytest.raises(ValueError, match=rf"{FILENAME}.*{plant}.*Hour=1.*finite fraction"):
        validate_thermal_min_dispatch(data)


@pytest.mark.parametrize(
    "hours",
    [
        [1, 1, 2, 3],
        [0, 1, 2, 3],
        [1, 2, 3, 5],
        [1, 2, 3, 4.5],
        [1, 2, 3, np.inf],
        [1, 2, 3, True],
        [1, 2, 3, "bad"],
    ],
)
def test_invalid_hour_labels_fail(data, hours):
    data[PROFILE]["Hour"] = hours
    with pytest.raises(ValueError, match=rf"{FILENAME}.*Hour"):
        validate_thermal_min_dispatch(data)


def test_profile_alignment_precision_and_horizon(data):
    plant = str(data["thermal_data"]["Plant_id"].iloc[0])
    data[PROFILE][plant] = [1e-9, 0.3, 0.5, 1]
    data[PROFILE] = data[PROFILE].iloc[::-1]
    frame = validate_thermal_min_dispatch(data, n_hours=2)
    assert frame["Hour"].tolist() == [1, 2, 3, 4]
    model = initialize_model(data, n_hours=2)
    assert value(model.thermal.min_dispatch_fraction[1, plant]) == 1e-9
    assert len(model.thermal.min_dispatch_fraction) == 2 * len(model.thermal.plants_set)
    with pytest.raises(ValueError, match=r"effective.*5"):
        initialize_model(data, n_hours=5)


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "hour_first"])
def test_profile_columns_must_match_all_plants(data, change):
    frame = data[PROFILE]
    if change == "missing":
        data[PROFILE] = frame.iloc[:, :-1]
    elif change == "extra":
        data[PROFILE]["unknown"] = 0
    elif change == "duplicate":
        data[PROFILE] = pd.concat([frame, frame.iloc[:, -1:]], axis=1)
    else:
        data[PROFILE] = frame.iloc[:, ::-1]
    with pytest.raises(ValueError, match=FILENAME):
        validate_thermal_min_dispatch(data)


@pytest.mark.parametrize("change", ["blank", "duplicate", "bounds", "infinite"])
def test_enabled_thermal_identity_and_bounds_fail(data, change):
    table = data["thermal_data"]
    if change == "blank":
        table.loc[0, "Plant_id"] = " "
    elif change == "duplicate":
        data["thermal_data"] = pd.concat([table, table.iloc[:1]], ignore_index=True)
    elif change == "bounds":
        table.loc[0, "MinCapacity"] = float(table.loc[0, "MaxCapacity"]) + 1
    else:
        table["MaxCapacity"] = table["MaxCapacity"].astype(float)
        table.loc[0, "MaxCapacity"] = np.inf
    with pytest.raises(ValueError, match=r"Data_BalancingUnits.csv"):
        validate_thermal_min_dispatch(data)


def test_conditional_loading_and_raw_headers(tmp_path, caplog):
    folder = tmp_path / "inputs"
    shutil.copytree(ROOT / "Data" / "no_exchange_run_of_river", folder)
    stale = folder / FILENAME
    stale.write_text("malformed", encoding="utf-8")
    with caplog.at_level(logging.INFO):
        legacy = load_data(str(folder))
    assert PROFILE not in legacy
    assert "ignores" in caplog.text
    enabled = enable(legacy)
    enabled["formulations"].to_csv(folder / "formulations.csv", index=False)
    stale.unlink()
    with pytest.raises(FileNotFoundError, match=FILENAME):
        load_data(str(folder))
    plant = str(enabled["thermal_data"]["Plant_id"].iloc[0])
    stale.write_text(f"Hour,{plant},{plant}\n1,0,0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_data(str(folder))
    enabled[PROFILE].to_csv(stale, index=False)
    loaded = load_data(str(folder))
    pd.testing.assert_frame_equal(loaded[PROFILE], enabled[PROFILE])


def controlled_data(
    data,
    *,
    minimum=100,
    maximum=100,
    fractions=(0.4, 0.3, 0.5, 0.6),
    demand=(80, 60, 100, 120),
    nuclear=0,
    clean_share=0,
):
    """Isolate must-run physics where real scenarios cannot provide binding floors."""
    data = copy.deepcopy(data)
    plant = data["thermal_data"].iloc[:1].copy()
    plant["Plant_id"] = "unit"
    plant["MinCapacity"] = minimum
    plant["MaxCapacity"] = maximum
    data["thermal_data"] = plant
    data[PROFILE] = pd.DataFrame({"Hour": range(1, len(fractions) + 1), "unit": fractions})
    for key in ("cap_solar", "cap_wind"):
        data[key] = data[key].iloc[:0]
    data["storage_data"] = data["storage_data"].iloc[:, :0]
    data["STORAGE_SET_J_TECHS"] = []
    data["STORAGE_SET_B_TECHS"] = []
    for key, values in (
        ("load_data", demand),
        ("nuclear_data", nuclear),
        ("large_hydro_data", 0),
        ("other_renewables_data", 0),
    ):
        frame = data[key].iloc[: len(fractions)].copy()
        frame.iloc[:, 1] = values
        data[key] = frame
    data["scalars"].loc["GenMix_Target", "Value"] = clean_share
    return data


def test_binding_floors_total_expansion_and_capacity_factor(data):
    data = controlled_data(data, minimum=20, maximum=300)
    model = initialize_model(data, n_hours=4)
    result = SolverFactory("highs").solve(model)
    assert str(result.solver.termination_condition) == "optimal"
    installed = value(model.thermal.plant_installed_capacity["unit"])
    assert installed == pytest.approx(120)
    generation = np.array([value(model.thermal.generation[h, "unit"]) for h in model.h])
    np.testing.assert_allclose(generation, [80, 60, 100, 120])
    assert generation[2] == pytest.approx(0.5 * installed + 40)
    assert generation.sum() / (4 * installed) >= np.mean([0.4, 0.3, 0.5, 0.6])
    fixed = initialize_model(controlled_data(data, minimum=200, maximum=200), n_hours=4)
    assert str(SolverFactory("highs").solve(fixed).solver.termination_condition) == "optimal"
    assert [value(fixed.thermal.generation[h, "unit"]) for h in fixed.h] == pytest.approx([80, 60, 100, 120])
    assert value(fixed.thermal.total_generation) == pytest.approx(360)
    assert len(fixed.thermal.min_dispatch_constraint) == 4
    assert all(c.body.polynomial_degree() == 1 for c in fixed.thermal.min_dispatch_constraint.values())
    assert not any(v.is_binary() for v in fixed.thermal.component_data_objects(Var))


@pytest.mark.parametrize(
    ("fractions", "demand", "nuclear", "clean_share"),
    [
        ((0.5, 0.5), (40, 100), 0, 0),
        ((0.5, 0.5), (60, 60), 20, 0),
        ((0.5, 0.5), (100, 100), 0, 1),
    ],
)
def test_must_run_surplus_and_clean_share_are_infeasible(data, fractions, demand, nuclear, clean_share):
    model = initialize_model(
        controlled_data(data, fractions=fractions, demand=demand, nuclear=nuclear, clean_share=clean_share),
        n_hours=2,
    )
    result = SolverFactory("highs").solve(model, load_solutions=False)
    assert str(result.solver.termination_condition) == "infeasible"


def test_zero_rows_optional_assets_and_legacy_components(data):
    data[PROFILE].iloc[:, 1:] = 0
    enabled = initialize_model(data, n_hours=2)
    assert len(enabled.thermal.min_dispatch_constraint) == 0
    data["formulations"].loc[data["formulations"]["Component"].str.lower() == "thermal", "Formulation"] = OLD
    legacy = initialize_model(data, n_hours=2)
    assert not hasattr(legacy.thermal, "min_dispatch_fraction")
    assert not hasattr(legacy.thermal, "min_dispatch_constraint")
    assert len(list(enabled.component_data_objects(Constraint))) == len(
        list(legacy.component_data_objects(Constraint))
    )
    enable(data)
    data["thermal_data"] = data["thermal_data"].iloc[:0]
    data[PROFILE] = data[PROFILE][["Hour"]]
    empty = initialize_model(data, n_hours=2)
    assert len(empty.thermal.min_dispatch_fraction) == 0


def test_zonal_profile_routes_by_ownership():
    data = enable(load_data(str(ROOT / "Data" / "zonal_test")))
    model = initialize_model(data, n_hours=2)
    for area in model.A:
        block = model.area[area].thermal
        for plant in block.plants_set:
            assert value(block.min_dispatch_fraction[2, plant]) == 0.25
        assert len(block.min_dispatch_constraint) == 2 * len(block.plants_set)


def test_hydro_rounded_horizon_requires_full_coverage(data):
    data["formulations"].loc[data["formulations"]["Component"].str.lower() == "hydro", "Formulation"] = (
        "DailyBudgetFormulation"
    )
    data["large_hydro_max"] = data["large_hydro_data"].copy()
    data["large_hydro_min"] = data["large_hydro_data"].copy()
    with pytest.raises(ValueError, match=r"effective.*24"):
        initialize_model(data, n_hours=2)


@pytest.mark.parametrize(
    ("minimum", "maximum", "demand", "fractions", "capacity"),
    [
        (20, 300, (100, 50), (0, 0.5), 100),
        (0, 300, (0, 0), (1, 1), 0),
        (0, 0, (0, 0), (1, 1), 0),
        (100, 100, (100, 100), (1, 1), 100),
    ],
)
def test_floor_basis_is_optimized_capacity_not_bounds(data, minimum, maximum, demand, fractions, capacity):
    model = initialize_model(
        controlled_data(data, minimum=minimum, maximum=maximum, demand=demand, fractions=fractions), n_hours=2
    )
    assert str(SolverFactory("highs").solve(model).solver.termination_condition) == "optimal"
    assert value(model.thermal.plant_installed_capacity["unit"]) == pytest.approx(capacity)
    assert value(model.thermal.generation[2, "unit"]) == pytest.approx(fractions[1] * capacity)
    assert len(model.thermal.min_dispatch_constraint) == sum(q > 0 for q in fractions)
    thermal = model.thermal
    expected_fuel = sum(demand) * value(thermal.fuel_price["unit"] * thermal.heat_rate["unit"])
    assert value(thermal.total_fuel_cost_expr) == pytest.approx(expected_fuel)


@pytest.mark.parametrize("margin", [0, 0.25])
def test_capacity_margin_credits_full_mw_and_can_induce_surplus(data, margin):
    from tests.test_capacity_margin import enable_reserves

    data = controlled_data(data, minimum=0, maximum=300, demand=(40, 100), fractions=(0.4, 0))
    enable_reserves(data, margin=margin)
    model = initialize_model(data, n_hours=2)
    result = SolverFactory("highs").solve(model, load_solutions=False)
    assert str(result.solver.termination_condition) == ("optimal" if margin == 0 else "infeasible")
    capability = model.reserves.Capability[2]
    model.thermal.plant_installed_capacity["unit"].value = 100
    assert value(capability.body) == pytest.approx(100)
    assert value(capability.lower) == pytest.approx(100 * (1 + margin))


def test_supported_parametric_mutations_preserve_profile(data):
    from sdom.parametric.mutations import (
        TS_KEY_TO_COLUMN,
        _apply_scalar_mutation,
        _apply_storage_factor_mutation,
        _apply_ts_mutation,
    )

    original = data[PROFILE].copy()
    for kind in ("scalar", "storage", "time_series"):
        changed = copy.deepcopy(data)
        if kind == "scalar":
            _apply_scalar_mutation(changed, "scalars", "GenMix_Target", 0.5)
        elif kind == "storage":
            _apply_storage_factor_mutation(changed, "P_Capex", 0.5)
        else:
            _apply_ts_mutation(changed, "load_data", 1.1)
        model = initialize_model(changed, n_hours=2)
        assert hasattr(model.thermal, "min_dispatch_fraction")
        pd.testing.assert_frame_equal(changed[PROFILE], original)
        changed[PROFILE].iloc[0, 1] = 0.9
        pd.testing.assert_frame_equal(data[PROFILE], original)
    assert PROFILE not in TS_KEY_TO_COLUMN


@pytest.mark.parametrize("plant_ids", [("000", "001"), ("NA", "NULL"), ("NaN", "N/A")])
def test_string_ids_and_one_hour_parser_preserve_exact_keys(tmp_path, plant_ids):
    folder = tmp_path / "inputs"
    shutil.copytree(ROOT / "Data" / "no_exchange_run_of_river", folder)
    data = load_data(str(folder))
    thermal_path = next(folder.glob("Data_BalancingUnits_2030*"))
    thermal = pd.read_csv(thermal_path)
    thermal["Plant_id"] = plant_ids
    thermal.to_csv(thermal_path, index=False)
    data["thermal_data"] = thermal
    enable(data, hours=1)
    data["formulations"].to_csv(folder / "formulations.csv", index=False)
    data[PROFILE].to_csv(folder / FILENAME, index=False)
    loaded = load_data(str(folder))
    assert loaded["thermal_data"]["Plant_id"].tolist() == thermal["Plant_id"].tolist()
    assert validate_thermal_min_dispatch(loaded, n_hours=1).shape == (1, len(thermal) + 1)


@pytest.mark.parametrize("bound", ["MinCapacity", "MaxCapacity"])
def test_csv_thermal_ids_preserve_numeric_missing_value_validation(tmp_path, bound):
    folder = tmp_path / "inputs"
    shutil.copytree(ROOT / "Data" / "no_exchange_run_of_river", folder)
    data = load_data(str(folder))
    thermal = data["thermal_data"].copy()
    thermal["Plant_id"] = ["NA", "NULL"]
    thermal[bound] = thermal[bound].astype(float)
    thermal.loc[0, bound] = np.nan
    thermal.to_csv(next(folder.glob("Data_BalancingUnits_2030*")), index=False)
    data["thermal_data"] = thermal
    enable(data, hours=2)
    data["formulations"].to_csv(folder / "formulations.csv", index=False)
    data[PROFILE].to_csv(folder / FILENAME, index=False)
    with pytest.raises(ValueError, match=rf"{bound}.*finite"):
        load_data(str(folder))


def test_aggregation_preserves_individual_profiles(tmp_path):
    from tests.test_zonal_aggregation_fallback import _zonal_copper_plate_folder

    folder = _zonal_copper_plate_folder(tmp_path)
    data = enable(load_data(str(folder)))
    for i, plant in enumerate(data[PROFILE].columns[1:]):
        data[PROFILE][plant] = i / len(data[PROFILE].columns)
    data["formulations"].to_csv(folder / "formulations.csv", index=False)
    data[PROFILE].to_csv(folder / FILENAME, index=False)
    loaded = load_data(str(folder))
    pd.testing.assert_frame_equal(loaded[PROFILE], data[PROFILE])
    assert len(initialize_model(loaded, n_hours=2).thermal.plants_set) == len(data["thermal_data"])


def test_stale_profile_cannot_substitute_for_required_static_table(tmp_path):
    shutil.copytree(ROOT / "Data" / "no_exchange_run_of_river", tmp_path / "inputs")
    folder = tmp_path / "inputs"
    next(folder.glob("Data_BalancingUnits_2030*")).unlink()
    (folder / FILENAME).write_text("Hour,unit\n1,0.2\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="thermal data"):
        load_data(str(folder))


@pytest.mark.parametrize("line_limit", [80, 79])
def test_zonal_empty_thermal_area_receives_surplus_only_with_sufficient_transfer(line_limit):
    data = enable(load_data(str(ROOT / "Data" / "zonal_test")), hours=2, fraction=1)
    thermal = data["thermal_data"].iloc[:1].copy()
    thermal[["MinCapacity", "MaxCapacity"]] = 100
    data["thermal_data"] = thermal
    data["per_area_balancing_units"] = {"A1": thermal}
    plant = str(thermal["Plant_id"].iloc[0])
    data[PROFILE] = pd.DataFrame({"Hour": [1, 2], plant: [1, 1]})
    for area in ("A1", "A2"):
        for key in ("per_area_pv_plants", "per_area_wind_plants"):
            data[key][area] = data[key][area].iloc[:0]
        data["per_area_storage"][area] = data["per_area_storage"][area].iloc[:, :0]
        data["per_area_demand"][area].iloc[:2, 1] = [20, 100] if area == "A1" else [80, 0]
        for key in ("per_area_nuclear", "per_area_hydro", "per_area_other_renewables"):
            data[key][area].iloc[:2, 1:] = 0
    data["line_cap_ft"].iloc[:2, :] = line_limit
    data["scalars"].loc["GenMix_Target", "Value"] = 0
    model = initialize_model(data, n_hours=2)
    assert len(model.area["A2"].thermal.plants_set) == 0
    assert len(model.area["A2"].thermal.min_dispatch_constraint) == 0
    result = SolverFactory("highs").solve(model, load_solutions=False)
    assert str(result.solver.termination_condition) == ("optimal" if line_limit == 80 else "infeasible")
    if line_limit == 80:
        model.solutions.load_from(result)
        assert value(model.f["L_A1_A2", 1]) == pytest.approx(80)
        assert value(model.area["A1"].thermal.generation[1, plant]) == pytest.approx(100)


@pytest.mark.parametrize("mode", ["CapacityPriceNetLoadFormulation", "WithoutNetLoadConstraints"])
def test_existing_export_gate_cannot_silently_dump_thermal_surplus(data, mode):
    data = controlled_data(data, demand=(40, 100), fractions=(0.5, 0), nuclear=(0, 10))
    data["formulations"].loc[data["formulations"]["Component"].str.lower() == "exports", "Formulation"] = mode
    data["cap_exports"] = pd.DataFrame({"*Hour": [1, 2], "Exports": [10, 0]})
    data["price_exports"] = pd.DataFrame({"*Hour": [1, 2], "Exports_price": [0, 0]})
    model = initialize_model(data, n_hours=2)
    result = SolverFactory("highs").solve(model, load_solutions=False)
    assert str(result.solver.termination_condition) == (
        "infeasible" if mode == "CapacityPriceNetLoadFormulation" else "optimal"
    )


def test_zonal_thermal_ownership_views_must_agree():
    data = enable(load_data(str(ROOT / "Data" / "zonal_test")), hours=2)
    data["per_area_balancing_units"]["A1"] = data["per_area_balancing_units"]["A2"]
    with pytest.raises(ValueError, match=r"thermal.*ownership|thermal.*per_area"):
        initialize_model(data, n_hours=2)


@pytest.mark.parametrize("change", ["identity", "capacity", "duplicate"])
def test_single_area_zonal_thermal_views_must_agree(data, change):
    data["formulations"].loc[len(data["formulations"]), ["Component", "Formulation"]] = (
        "Network", "AreaTransportationModelNetwork"
    )
    area = data["areas"][0]["area_id"]
    table = data["per_area_balancing_units"][area].copy()
    if change == "identity":
        table.loc[0, "Plant_id"] = "unknown"
    elif change == "capacity":
        table.loc[0, "MaxCapacity"] += 1
    else:
        table = pd.concat([table, table.iloc[:1]], ignore_index=True)
    data["per_area_balancing_units"][area] = table
    with pytest.raises(ValueError, match=r"thermal.*ownership"):
        initialize_model(data, n_hours=2)


def test_single_area_zonal_accepts_legacy_thermal_schema(data):
    data["formulations"].loc[len(data["formulations"]), ["Component", "Formulation"]] = (
        "Network", "AreaTransportationModelNetwork"
    )
    assert "area_id" not in data["thermal_data"]
    original = data["thermal_data"].copy()
    model = initialize_model(data, n_hours=2)
    host = model.area[data["areas"][0]["area_id"]]
    assert len(host.thermal.min_dispatch_constraint) == 2 * len(original)
    pd.testing.assert_frame_equal(data["thermal_data"], original)


@pytest.mark.parametrize("empty_view", [False, True])
def test_zonal_thermal_owners_must_be_declared(empty_view):
    data = enable(load_data(str(ROOT / "Data" / "zonal_test")), hours=2)
    if empty_view:
        data["per_area_balancing_units"]["X"] = data["thermal_data"].iloc[:0]
    else:
        data["thermal_data"]["area_id"] = "X"
        data["per_area_balancing_units"] = {"X": data["thermal_data"].copy()}
    with pytest.raises(ValueError, match=r"undeclared.*X"):
        initialize_model(data, n_hours=2)


@pytest.mark.parametrize("dangling_views", [False, True])
def test_zonal_empty_fleet_without_area_column(dangling_views):
    data = enable(load_data(str(ROOT / "Data" / "zonal_test")), hours=2)
    data["thermal_data"] = data["thermal_data"].iloc[:0].drop(columns="area_id")
    data[PROFILE] = data[PROFILE][["Hour"]]
    if dangling_views:
        with pytest.raises(ValueError, match=r"thermal.*ownership"):
            initialize_model(data, n_hours=2)
    else:
        data["per_area_balancing_units"] = {
            area["area_id"]: data["thermal_data"].copy() for area in data["areas"]
        }
        model = initialize_model(data, n_hours=2)
        assert all(len(model.area[area].thermal.plants_set) == 0 for area in model.A)
        assert "area_id" not in data["thermal_data"]


@pytest.mark.parametrize("max_power", [0, 10])
def test_storage_is_a_bounded_sink_for_thermal_surplus(data, max_power):
    storage = data["storage_data"].iloc[:, :1].copy()
    storage.loc["Max_P"] = max_power
    storage.loc["Eff"] = 1.0
    data = controlled_data(data, demand=(40, 100), fractions=(0.5, 0))
    data["storage_data"] = storage
    data["STORAGE_SET_J_TECHS"] = storage.columns.tolist()
    data["STORAGE_SET_B_TECHS"] = storage.columns[storage.loc["Coupled"] == 1].tolist()
    model = initialize_model(data, n_hours=2)
    result = SolverFactory("highs").solve(model, load_solutions=False)
    assert str(result.solver.termination_condition) == ("optimal" if max_power == 10 else "infeasible")
    if max_power:
        model.solutions.load_from(result)
        tech = next(iter(model.storage.j))
        assert value(model.storage.PC[1, tech]) == pytest.approx(10)


def test_exhausted_vre_curtailment_cannot_dump_thermal_surplus(data):
    solar = data["cap_solar"].iloc[:1].copy()
    solar["MinCapacity"] = solar["capacity"] = 100
    data = controlled_data(data, demand=(40, 100), fractions=(0.5, 0))
    data["cap_solar"] = solar
    plant = str(solar["sc_gid"].iloc[0])
    data["cf_solar"][plant] = 1
    model = initialize_model(data, n_hours=2)
    result = SolverFactory("highs").solve(model, load_solutions=False)
    assert str(result.solver.termination_condition) == "infeasible"


@pytest.mark.parametrize("column", ["Hour", "plant"])
def test_nullable_boolean_columns_are_not_numeric_fractions_or_hours(data, column):
    column = data[PROFILE].columns[1] if column == "plant" else column
    data[PROFILE][column] = pd.Series([True] * 4, dtype="boolean")
    with pytest.raises(ValueError, match=r"MinDispatchFraction.*finite"):
        validate_thermal_min_dispatch(data)


@pytest.mark.parametrize("plant_count", [1, 2])
def test_result_schema_and_thermal_reporting_are_unchanged(data, plant_count):
    from sdom import get_default_solver_config_dict, run_solver

    data = controlled_data(data, demand=(100, 100), fractions=(0.5, 0.5))
    if plant_count == 2:
        second = data["thermal_data"].copy()
        second["Plant_id"] = "second"
        data["thermal_data"] = pd.concat([data["thermal_data"], second], ignore_index=True)
        data[PROFILE]["second"] = 0.5
    columns = None
    for selected in (OLD, NEW):
        data["formulations"].loc[
            data["formulations"]["Component"].str.lower() == "thermal", "Formulation"
        ] = selected
        model = initialize_model(data, n_hours=2)
        config = get_default_solver_config_dict(solver_name="highs", executable_path="")
        config["solve_keywords"].update(tee=False, report_timing=False, keepfiles=False)
        result = run_solver(model, config)
        assert result.is_optimal
        assert result.total_gen_thermal == pytest.approx(200)
        assert result.total_cap_thermal == pytest.approx(100 * plant_count)
        frame = result.get_generation_dataframe()
        if columns is None:
            columns = list(frame.columns)
        assert list(frame.columns) == columns
        assert frame["All Thermal Generation (MW)"].sum() == pytest.approx(200)
        disaggregated = result.get_thermal_generation_dataframe()
        assert list(disaggregated.columns) == ["Hour", "Area", "Plant ID", "Generation (MW)"]
        assert len(disaggregated) == 2 * plant_count
        assert set(disaggregated["Area"]) == {"copperplate"}
        assert disaggregated["Generation (MW)"].sum() == pytest.approx(200)
