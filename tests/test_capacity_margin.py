"""Hourly capacity-margin input, physics, and optimization coverage."""

from pathlib import Path

import pandas as pd
import pytest
from pyomo.core.base.expression import ExpressionData
from pyomo.core.expr.visitor import identify_components
from pyomo.environ import (
    Block,
    ConcreteModel,
    Constraint,
    Expression,
    NonNegativeReals,
    Objective,
    Param,
    Set,
    SolverFactory,
    Var,
    maximize,
    value,
)

from sdom import initialize_model, load_data
from sdom.models.formulations_reserves import add_capacity_margin_constraints, adequacy_duration_hours

ROOT = Path(__file__).resolve().parents[1]


def enable_reserves(data, *, margin=0.04):
    """Select capacity margins without changing the source dataset."""
    data["formulations"].loc[len(data["formulations"])] = [
        "Reserves",
        "CapacityMarginFormulation",
        "Hourly local capability margin",
    ]
    if isinstance(margin, str):
        data["scalars"]["Value"] = data["scalars"]["Value"].astype(object)
    data["scalars"].loc["capacity_marging_fraction", "Value"] = margin
    return data


def test_capacity_margin_builds_with_named_storage_expression():
    data = enable_reserves(load_data(str(ROOT / "Data" / "no_exchange_run_of_river")))
    model = initialize_model(data, n_hours=24)

    assert len(model.reserves.Capability) == 24
    expression = model.reserves.storage_activated_net_output
    assert isinstance(expression, Expression)
    assert expression.is_indexed()
    assert value(model.reserves.capacity_marging_fraction) == 0.04


@pytest.mark.parametrize(
    "selection", [None, "notModel", "NotModel", "Other", "capacitymarginformulation", float("nan"), pd.NA]
)
def test_nonmatching_selection_preserves_legacy_structure(selection):
    data = load_data(str(ROOT / "Data" / "no_exchange_run_of_river"))
    baseline = initialize_model(data, n_hours=2)
    enable_reserves(data, margin="invalid-but-inactive")
    if selection is None:
        data["formulations"] = data["formulations"].iloc[:-1]
    else:
        data["formulations"].loc[data["formulations"]["Component"] == "Reserves", "Formulation"] = selection
    model = initialize_model(data, n_hours=2)
    assert not hasattr(model, "reserves")
    for kind in (Constraint, Var):
        assert len(list(model.component_data_objects(kind))) == len(
            list(baseline.component_data_objects(kind))
        )


@pytest.mark.parametrize("margin", ["", "not-a-number", None, float("nan"), float("inf"), -0.01])
def test_enabled_margin_rejects_invalid_scalar(margin):
    data = enable_reserves(load_data(str(ROOT / "Data" / "no_exchange_run_of_river")))
    data["scalars"]["Value"] = data["scalars"]["Value"].astype(object)
    data["scalars"].loc["capacity_marging_fraction", "Value"] = margin
    with pytest.raises(ValueError, match=r"capacity_marging_fraction.*finite nonnegative fraction"):
        initialize_model(data, n_hours=2)


@pytest.mark.parametrize("margin", [None, 0.0, 0.04, 15.0])
def test_enabled_margin_defaults_to_zero_without_percent_conversion(margin):
    data = enable_reserves(load_data(str(ROOT / "Data" / "no_exchange_run_of_river")), margin=margin)
    if margin is None:
        data["scalars"] = data["scalars"].drop("capacity_marging_fraction")
    model = initialize_model(data, n_hours=2)
    assert value(model.reserves.capacity_marging_fraction) == (margin or 0.0)
    assert len(model.reserves.Capability) == 2
    assert adequacy_duration_hours == 1


def capability_snapshot(*, efficiency=1.0, with_storage=True):
    """Build only the owning components needed for isolated capability physics."""
    model = ConcreteModel()
    model.h = Set(initialize=[1, 2], ordered=True)
    model.storage = Block()
    storage = model.storage
    storage.j = Set(initialize=["battery"] if with_storage else [])
    storage.data = Param(["Eff"], storage.j, initialize=efficiency)
    for name in ("PC", "PD", "SOC"):
        setattr(storage, name, Var(model.h, storage.j, domain=NonNegativeReals, initialize=0))
    storage.Pdis = Var(storage.j, domain=NonNegativeReals, initialize=100)
    model.thermal = Block()
    model.thermal.installed = Var(bounds=(0, 0), initialize=0)
    model.thermal.total_installed_capacity = Expression(expr=model.thermal.installed)
    for name in ("pv", "wind"):
        vre = Block()
        setattr(model, name, vre)
        vre.plants_set = Set(initialize=["plant"])
        vre.capacity_factor = Param(
            model.h, vre.plants_set, initialize={(1, "plant"): 0.5, (2, "plant"): 0.1}
        )
        vre.plant_installed_capacity = Param(vre.plants_set, initialize=10)
    model.hydro = Block()
    model.hydro.generation = Param(model.h, initialize=2)
    for name in ("nuclear", "other_renewables", "demand"):
        block = Block()
        setattr(model, name, block)
        block.ts_parameter = Param(model.h, initialize=1 if name != "demand" else 0, mutable=True)
        block.alpha = Param(initialize=1)
    data = {
        "formulations": pd.DataFrame(
            {"Component": ["Reserves"], "Formulation": ["CapacityMarginFormulation"]}
        ),
        "scalars": pd.DataFrame({"Value": [0.0]}, index=["capacity_marging_fraction"]),
    }
    add_capacity_margin_constraints(model, data)
    return model


@pytest.mark.parametrize(
    ("charge", "discharge", "beginning_soc", "efficiency", "expected_up"),
    [
        (50, 0, 100, 1, 150),
        (50, 0, 0, 1, 50),
        (50, 0, 20, 1, 70),
        (0, 40, 100, 1, 60),
        (50, 0, 100, 0.81, 140),
    ],
)
def test_storage_upward_capability_uses_beginning_energy_and_allows_switching(
    charge, discharge, *, beginning_soc, efficiency, expected_up
):
    model = capability_snapshot(efficiency=efficiency)
    storage = model.storage
    for h in model.h:
        storage.PC[h, "battery"].fix(charge)
        storage.PD[h, "battery"].fix(discharge)
        storage.SOC[h, "battery"].fix(beginning_soc if h == 2 else 1000)
    storage.Pdis["battery"].fix(100)
    model.objective = Objective(expr=model.reserves.storage_upward_capability[1, "battery"], sense=maximize)
    result = SolverFactory("highs").solve(model)
    assert str(result.solver.termination_condition) == "optimal"
    assert value(model.objective) == pytest.approx(expected_up)
    assert value(model.reserves.storage_activated_net_output[1, "battery"]) == pytest.approx(
        discharge - charge + expected_up
    )
    assert len(list(model.component_data_objects(Var))) == 10
    assert all(not c.equality for c in model.component_data_objects(Constraint))


@pytest.mark.parametrize("upward", [0, 50, 70])
def test_named_expression_is_reused_and_supports_signed_output(upward):
    model = capability_snapshot()
    storage = model.storage
    storage.PC[1, "battery"].set_value(50)
    storage.PD[1, "battery"].set_value(0)
    model.reserves.storage_upward_capability[1, "battery"].set_value(upward)
    expression = model.reserves.storage_activated_net_output[1, "battery"]
    assert value(expression) == upward - 50
    for constraint in (
        model.reserves.Capability[1],
        model.reserves.StoragePower[1, "battery"],
        model.reserves.StorageEnergy[1, "battery"],
    ):
        assert any(node is expression for node in identify_components(constraint.body, {ExpressionData}))


def test_capability_counts_resources_once_in_every_hour_without_storage():
    model = capability_snapshot(with_storage=False)
    assert len(model.reserves.StoragePower) == 0
    assert len(model.reserves.Capability) == 2
    assert value(model.reserves.Capability[1].body) == 14
    assert value(model.reserves.Capability[2].body) == 6


def test_low_vre_nonpeak_hour_is_infeasible_despite_sufficient_peak_capability():
    model = capability_snapshot(with_storage=False)
    model.demand.ts_parameter[1] = 10
    model.demand.ts_parameter[2] = 8
    model.objective = Objective(expr=model.thermal.installed)
    result = SolverFactory("highs").solve(model, load_solutions=False)
    assert str(result.solver.termination_condition) == "infeasible"


def test_demand_only_zonal_area_cannot_use_imported_capability():
    data = load_data(str(ROOT / "Data" / "zonal_test"))
    for key in (
        "per_area_pv_plants",
        "per_area_wind_plants",
        "per_area_capacity_factors_pv",
        "per_area_capacity_factors_wind",
        "per_area_storage",
        "per_area_balancing_units",
        "per_area_nuclear",
        "per_area_other_renewables",
        "per_area_hydro",
    ):
        data[key].pop("A2", None)
    data["per_area_demand"]["A2"]["Load"] = 10.0
    baseline = initialize_model(data, n_hours=24)
    result = SolverFactory("highs").solve(baseline)
    assert str(result.solver.termination_condition) == "optimal"
    assert any(value(baseline.f[line, h]) != 0 for line in baseline.L for h in baseline.h)

    model = initialize_model(enable_reserves(data, margin=0.0), n_hours=24)
    assert len(model.area["A2"].reserves.Capability) == 24
    assert len(model.area["A2"].storage.j) == 0
    result = SolverFactory("highs").solve(model, load_solutions=False)
    assert str(result.solver.termination_condition) == "infeasible"


@pytest.mark.parametrize("folder", ["no_exchange_run_of_river", "zonal_test"])
def test_inactive_scalar_preserves_legacy_objective_capacities_and_feasibility(folder):
    from utils_tests import check_supply_balance_constraint, get_n_eq_ineq_constraints

    from sdom import get_default_solver_config_dict, run_solver

    data = load_data(str(ROOT / "Data" / folder))
    baseline = initialize_model(data, n_hours=24)
    enable_reserves(data, margin=float("nan"))
    data["formulations"].loc[data["formulations"]["Component"] == "Reserves", "Formulation"] = "notModel"
    inactive = initialize_model(data, n_hours=24)
    assert get_n_eq_ineq_constraints(inactive) == get_n_eq_ineq_constraints(baseline)
    config = get_default_solver_config_dict(solver_name="highs", executable_path="")
    config["solve_keywords"].update(tee=False, report_timing=False, keepfiles=False)
    before, after = (run_solver(model, config) for model in (baseline, inactive))
    assert before.is_optimal and after.is_optimal
    assert after.total_cost == pytest.approx(before.total_cost, abs=1e-3, rel=0)
    assert after.total_cap_wind == pytest.approx(before.total_cap_wind)
    assert after.total_cap_pv == pytest.approx(before.total_cap_pv)
    assert after.storage_capacity == before.storage_capacity
    assert check_supply_balance_constraint(before)["is_satisfied"]
    assert check_supply_balance_constraint(after)["is_satisfied"]
    hosts = [inactive.area[a] for a in inactive.A] if hasattr(inactive, "A") else [inactive]
    assert all(not hasattr(host, "reserves") for host in hosts)


def test_csv_input_and_scalar_sweep_propagate_margin(tmp_path):
    import shutil

    from sdom import ParametricStudy, get_default_solver_config_dict

    path = tmp_path / "reserve_case"
    shutil.copytree(ROOT / "Data" / "no_exchange_run_of_river", path)
    data = enable_reserves(load_data(str(path)), margin=0.0)
    data["formulations"].to_csv(path / "formulations.csv", index=False)
    data["scalars"].to_csv(path / "scalars.csv")
    loaded = load_data(str(path))
    assert value(initialize_model(loaded, n_hours=24).reserves.capacity_marging_fraction) == 0
    config = get_default_solver_config_dict(solver_name="highs", executable_path="")
    config["solve_keywords"].update(tee=False, report_timing=False, keepfiles=False)
    study = ParametricStudy(loaded, config, n_hours=24, n_cores=1)
    study.add_scalar_sweep("scalars", "capacity_marging_fraction", [0.0, 0.5])
    results = study.run()
    assert all(result.is_optimal for result in results)
    assert results[1].total_cost >= results[0].total_cost - 10
    assert results[1].total_cost > results[0].total_cost + 100
    assert loaded["scalars"].loc["capacity_marging_fraction", "Value"] == 0.0
