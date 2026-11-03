"""Hourly capacity-margin input, physics, and optimization coverage."""

from pathlib import Path

import pandas as pd
import pytest
from pyomo.core.expr.visitor import identify_variables
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
        "Hourly capacity margin",
    ]
    if isinstance(margin, str):
        data["scalars"]["Value"] = data["scalars"]["Value"].astype(object)
    data["scalars"].loc["capacity_marging_fraction", "Value"] = margin
    return data


def test_capacity_margin_builds_with_direct_nonnegative_storage_capacity():
    data = enable_reserves(load_data(str(ROOT / "Data" / "no_exchange_run_of_river")))
    model = initialize_model(data, n_hours=24)

    assert len(model.reserves.Capability) == 24
    contribution = model.reserves.storage_capacity_contribution
    assert isinstance(contribution, Var)
    assert contribution.is_indexed()
    assert all(variable.lb == 0 for variable in contribution.values())
    assert not hasattr(model.reserves, "storage_upward_capability")
    assert not hasattr(model.reserves, "storage_activated_net_output")
    assert not list(model.reserves.component_objects(Expression))
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
    ("charge", "discharge", "beginning_soc", "efficiency", "expected_capacity"),
    [
        (50, 0, 100, 1, 100),
        (50, 0, 0, 1, 0),
        (50, 0, 20, 1, 20),
        (0, 40, 100, 1, 100),
        (50, 0, 100, 0.81, 90),
        (0, 0, 20, 1, 20),
        (0, 10, 20, 1, 20),
    ],
)
def test_storage_capacity_uses_power_and_beginning_soc_not_baseline_operation(
    charge, discharge, *, beginning_soc, efficiency, expected_capacity
):
    model = capability_snapshot(efficiency=efficiency)
    storage = model.storage
    for h in model.h:
        storage.PC[h, "battery"].fix(charge)
        storage.PD[h, "battery"].fix(discharge)
        storage.SOC[h, "battery"].fix(beginning_soc if h == 2 else 1000)
    storage.Pdis["battery"].fix(100)
    model.objective = Objective(expr=model.reserves.storage_capacity_contribution[1, "battery"], sense=maximize)
    result = SolverFactory("highs").solve(model)
    assert str(result.solver.termination_condition) == "optimal"
    assert value(model.objective) == pytest.approx(expected_capacity)
    assert len(list(model.component_data_objects(Var))) == 10
    assert len(list(model.reserves.component_data_objects(Constraint))) == 6
    assert all(not c.equality for c in model.component_data_objects(Constraint))


def test_storage_capacity_formulation_is_linear_and_has_no_dispatch_terms():
    model = capability_snapshot()
    storage = model.storage
    contribution = model.reserves.storage_capacity_contribution[1, "battery"]
    dispatch = {id(v) for component in (storage.PC, storage.PD) for v in component.values()}
    for constraint in (
        model.reserves.Capability[1],
        model.reserves.StoragePower[1, "battery"],
        model.reserves.StorageEnergy[1, "battery"],
    ):
        variables = list(identify_variables(constraint.body))
        assert any(variable is contribution for variable in variables)
        assert not any(id(variable) in dispatch for variable in variables)
        assert constraint.body.polynomial_degree() == 1


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


@pytest.mark.parametrize("flow", [-100.0, 0.0, 100.0], ids=["reverse", "zero", "forward"])
def test_zonal_capability_credits_imports_and_debits_exports(flow):
    data = enable_reserves(load_data(str(ROOT / "Data" / "zonal_test")))
    model = initialize_model(data, n_hours=2)
    for variable in model.component_data_objects(Var):
        variable.set_value(0, skip_validation=True)
    before = {a: value(model.area[a].reserves.Capability[1].body) for a in model.A}
    line = next(iter(model.L))
    origin, destination = value(model.line_from[line]), value(model.line_to[line])
    model.f[line, 1].set_value(flow)
    after = {a: value(model.area[a].reserves.Capability[1].body) for a in model.A}
    assert after[origin] - before[origin] == pytest.approx(-flow)
    assert after[destination] - before[destination] == pytest.approx(flow)
    assert sum(after.values()) == pytest.approx(sum(before.values()))
    for a in model.A:
        assert value(model.area[a].reserves.Capability[1].lower) == pytest.approx(
            1.04 * value(model.area[a].demand.ts_parameter[1])
        )


def test_zonal_capability_without_lines_retains_local_resource_accounting():
    data = enable_reserves(load_data(str(ROOT / "Data" / "zonal_test")))
    data["lines"] = []
    model = initialize_model(data, n_hours=2)
    assert len(model.L) == 0
    for variable in model.component_data_objects(Var):
        variable.set_value(0, skip_validation=True)
    for a in model.A:
        host = model.area[a]
        fixed_injections = value(
            host.hydro.generation[1]
            + host.nuclear.alpha * host.nuclear.ts_parameter[1]
            + host.other_renewables.alpha * host.other_renewables.ts_parameter[1]
        )
        assert value(host.reserves.Capability[1].body) == pytest.approx(fixed_injections)


@pytest.mark.parametrize("margin", [0.0, 0.04])
def test_demand_only_zonal_area_can_use_scheduled_imports_but_not_reserve_transfers(margin):
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
    assert all(
        -value(baseline.LineCap_TF[line, h])
        < value(baseline.f[line, h])
        < value(baseline.LineCap_FT[line, h])
        for line in baseline.L
        for h in baseline.h
    )

    model = initialize_model(enable_reserves(data, margin=margin), n_hours=24)
    assert len(model.area["A2"].reserves.Capability) == 24
    assert len(model.area["A2"].storage.j) == 0
    result = SolverFactory("highs").solve(model, load_solutions=margin == 0)
    assert str(result.solver.termination_condition) == ("optimal" if margin == 0 else "infeasible")
    if margin == 0:
        for h in model.h:
            net_imports = sum(value(model.f[line, h]) for line in model.L_in["A2"]) - sum(
                value(model.f[line, h]) for line in model.L_out["A2"]
            )
            assert net_imports == pytest.approx(10)
            assert value(model.area["A2"].reserves.Capability[h].body) == pytest.approx(10)


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
