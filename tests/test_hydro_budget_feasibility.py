"""Tests for pre-solve hydro budget feasibility validation."""

from __future__ import annotations

import copy
import os

import pytest
from pyomo.environ import Constraint, Objective, Var, value
from utils_tests import check_budget_constraint, check_supply_balance_constraint, get_n_eq_ineq_constraints

from sdom import get_default_solver_config_dict, initialize_model, load_data, run_solver
from sdom.constants import DAILY_BUDGET_HOURS_AGGREGATION
from sdom.optimization_main import _validate_hydro_budget_feasibility


def _abs_data_path(relative_path: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", relative_path))


def _set_budget(data: dict, *, start_hour: int, interval: int, budget: float) -> None:
    hours = range(start_hour, start_hour + interval)
    mask = data["large_hydro_data"]["*Hour"].isin(hours)
    data["large_hydro_data"].loc[mask, "LargeHydro"] = budget / interval


def _set_bound(
    data: dict, *, start_hour: int, interval: int, bound_key: str, value: float
) -> None:
    hours = range(start_hour, start_hour + interval)
    mask = data[bound_key]["*Hour"].isin(hours)
    data[bound_key].loc[mask, "LargeHydro"] = value


@pytest.mark.parametrize(
    ("formulation", "interval", "equality"),
    [
        ("DailyBudgetFormulation", 24, True),
        ("DailyBudgetUpperBoundFormulation", 24, False),
        ("MonthlyBudgetFormulation", 730, True),
        ("MonthlyBudgetUpperBoundFormulation", 730, False),
    ],
)
def test_hydro_budget_formulation_selects_energy_constraint(formulation, interval, *, equality):
    data = load_data(
        _abs_data_path("Data/no_exchange_hydro_daily_budget_multiple_balancing_p95")
    )
    selection = data["formulations"]["Component"] == "Hydro"
    data["formulations"].loc[selection, "Formulation"] = formulation
    data["scalars"].loc["AlphaLargHy", "Value"] = 0.5
    _set_budget(data, start_hour=1, interval=interval, budget=10.0 * interval)
    for key, bound in [("large_hydro_min", 2.0), ("large_hydro_max", 40.0)]:
        _set_bound(data, start_hour=1, interval=interval, bound_key=key, value=bound)

    model = initialize_model(data, n_hours=1)
    assert len(model.h) == interval
    assert len(model.hydro.budget_constraint) == 1
    constraint = model.hydro.budget_constraint[1]
    assert constraint.equality == equality
    assert value(constraint.upper) == pytest.approx(10.0 * interval)
    assert constraint.has_lb() == equality

    for dispatch in (5.0, 10.0, 15.0):
        for hour in model.h:
            model.hydro.generation[hour].set_value(dispatch)
        expected = dispatch == 10.0 if equality else dispatch <= 10.0
        assert check_budget_constraint(model)["is_satisfied"] == expected

    for dispatch, expected in [(0.5, False), (1.0, True), (20.0, True), (20.5, False)]:
        model.hydro.generation[1].set_value(dispatch)
        lower = model.hydro.lower_bound_ts_constraint[1]
        upper = model.hydro.upper_bound_ts_constraint[1]
        satisfied = value(lower.body) >= value(lower.lower) and value(upper.body) <= value(upper.upper)
        assert satisfied == expected


@pytest.mark.parametrize(
    ("strict", "flexible", "interval"),
    [
        ("DailyBudgetFormulation", "DailyBudgetUpperBoundFormulation", 24),
        ("MonthlyBudgetFormulation", "MonthlyBudgetUpperBoundFormulation", 730),
    ],
)
@pytest.mark.parametrize("zonal", [False, True], ids=["copperplate", "zonal"])
def test_hydro_budget_choice_changes_only_budget_relations(strict, flexible, *, interval, zonal):
    folder = "Data/zonal_test" if zonal else "Data/no_exchange_hydro_daily_budget_multiple_balancing_p95"
    data = load_data(_abs_data_path(folder))
    if zonal:
        for hydro in data["per_area_hydro"].values():
            hydro["LargeHydro_Min"] = 0.0
            hydro["LargeHydro_Max"] = hydro["LargeHydro"]
    models = []
    for formulation in (strict, flexible):
        data["formulations"].loc[data["formulations"]["Component"] == "Hydro", "Formulation"] = formulation
        models.append(initialize_model(data, n_hours=1))
    equality, upper_bound = models
    expected_periods = 2 if zonal else 1
    equality_counts, upper_counts = (get_n_eq_ineq_constraints(model) for model in models)
    assert equality_counts["equality"] == upper_counts["equality"] + expected_periods
    assert equality_counts["inequality"] == upper_counts["inequality"] - expected_periods
    assert sum(equality_counts.values()) == sum(upper_counts.values())
    for component_type in (Var, Constraint, Objective):
        names = [
            {component.name for component in model.component_data_objects(component_type)}
            for model in models
        ]
        assert names[0] == names[1]
    assert str(equality.Obj.expr) == str(upper_bound.Obj.expr)
    assert len(equality.h) == len(upper_bound.h) == interval
    assert sum(var.is_binary() for var in equality.component_data_objects(Var)) == sum(
        var.is_binary() for var in upper_bound.component_data_objects(Var)
    )


@pytest.mark.parametrize(
    ("formulation", "interval", "equality"),
    [
        ("DailyBudgetFormulation", 24, True),
        ("DailyBudgetUpperBoundFormulation", 24, False),
        ("MonthlyBudgetFormulation", 730, True),
        ("MonthlyBudgetUpperBoundFormulation", 730, False),
    ],
)
def test_zonal_hydro_budgets_enforce_each_area_and_period(formulation, interval, *, equality):
    data = load_data(_abs_data_path("Data/zonal_test"))
    data["formulations"].loc[data["formulations"]["Component"] == "Hydro", "Formulation"] = formulation
    for area, hydro in data["per_area_hydro"].items():
        hydro["LargeHydro_Min"] = 0.0
        hydro["LargeHydro_Max"] = 100.0
        hydro["LargeHydro"] = 10.0 if area == "A1" else 30.0
        hydro.loc[hydro["*Hour"] > interval, "LargeHydro"] *= 2
    model = initialize_model(data, n_hours=interval + 1)
    assert len(model.h) == 2 * interval
    for area in model.A:
        host = model.area[area]
        for hour in host.h:
            host.hydro.generation[hour].set_value(value(host.hydro.ts_parameter[hour]))
        assert check_budget_constraint(host)["is_satisfied"]
        for hour in host.h:
            adjustment = -1.0 if hour <= interval else 1.0
            host.hydro.generation[hour].set_value(value(host.hydro.ts_parameter[hour]) + adjustment)
        check = check_budget_constraint(host)
        assert not check["is_satisfied"]
        assert len(check["violations"]) == (2 if equality else 1)
        assert sum(detail["difference"] for detail in check["budget_details"]) == pytest.approx(0.0)


def test_unsupported_hydro_budget_name_fails_explicitly():
    data = load_data(_abs_data_path("Data/no_exchange_hydro_daily_budget_multiple_balancing_p95"))
    data["formulations"].loc[data["formulations"]["Component"] == "Hydro", "Formulation"] = (
        "DailyBudgetUpperBoundTypo"
    )
    with pytest.raises(ValueError, match=r"Invalid formulation.*DailyBudgetUpperBoundTypo.*Valid options"):
        initialize_model(data, n_hours=24)


@pytest.mark.parametrize(
    ("relative_path", "n_hours"),
    [
        ("Data/no_exchange_hydro_daily_budget_multiple_balancing_p95", 24),
        ("Data/no_exchange_monthly_hydro_budget_multiple_balancing_p50", 730),
    ],
)
def test_hydro_budget_validator_accepts_feasible_daily_and_monthly_data(
    relative_path, n_hours
):
    data = load_data(_abs_data_path(relative_path))

    _validate_hydro_budget_feasibility(data, n_hours=n_hours)


@pytest.mark.parametrize(
    ("formulation", "interval"),
    [
        ("DailyBudgetFormulation", 24),
        ("DailyBudgetUpperBoundFormulation", 24),
        ("MonthlyBudgetFormulation", 730),
        ("MonthlyBudgetUpperBoundFormulation", 730),
    ],
)
def test_hydro_budget_validator_reports_lower_violation_during_initialization(formulation, interval):
    data = load_data(
        _abs_data_path("Data/no_exchange_hydro_daily_budget_multiple_balancing_p95")
    )
    data["formulations"].loc[data["formulations"]["Component"] == "Hydro", "Formulation"] = formulation
    _set_budget(data, start_hour=1, interval=interval, budget=0)

    with pytest.raises(ValueError, match=rf"{formulation}.*bin 1.*lower"):
        initialize_model(data, n_hours=1)


@pytest.mark.parametrize(
    ("formulation", "interval"),
    [("DailyBudgetFormulation", 24), ("MonthlyBudgetFormulation", 730)],
)
@pytest.mark.parametrize("zonal", [False, True], ids=["copperplate", "zonal"])
def test_equality_hydro_budget_rejects_availability_above_scaled_maximum(
    formulation, interval, *, zonal
):
    folder = "Data/zonal_test" if zonal else "Data/no_exchange_hydro_daily_budget_multiple_balancing_p95"
    data = load_data(_abs_data_path(folder))
    data["formulations"].loc[data["formulations"]["Component"] == "Hydro", "Formulation"] = formulation
    data["scalars"].loc["AlphaLargHy", "Value"] = 0.5
    if zonal:
        for hydro in data["per_area_hydro"].values():
            hydro["LargeHydro_Min"] = 0.0
            hydro["LargeHydro_Max"] = 40.0
            hydro["LargeHydro"] = 10.0
        data["per_area_hydro"]["A1"]["LargeHydro"] = 21.0
    else:
        _set_budget(data, start_hour=1, interval=interval, budget=21.0 * interval)
        _set_bound(data, start_hour=1, interval=interval, bound_key="large_hydro_min", value=0.0)
        _set_bound(data, start_hour=1, interval=interval, bound_key="large_hydro_max", value=40.0)

    with pytest.raises(ValueError, match=rf"{formulation}.*bin 1.*upper violation"):
        initialize_model(data, n_hours=1)


@pytest.mark.parametrize(
    ("relative_path", "interval"),
    [
        ("Data/no_exchange_hydro_daily_budget_multiple_balancing_p95", 24),
        ("Data/no_exchange_monthly_hydro_budget_multiple_balancing_p50", 730),
    ],
    ids=["daily", "monthly"],
)
def test_hydro_budget_accepts_unused_availability_builds_and_solves(
    relative_path, interval
):
    data = load_data(_abs_data_path(relative_path))
    selection = data["formulations"]["Component"] == "Hydro"
    data["formulations"].loc[selection, "Formulation"] = (
        "DailyBudgetUpperBoundFormulation" if interval == 24 else "MonthlyBudgetUpperBoundFormulation"
    )
    maximum = data["large_hydro_max"].loc[
        data["large_hydro_max"]["*Hour"] <= interval, "LargeHydro"
    ].sum()
    _set_budget(data, start_hour=1, interval=interval, budget=2.0 * maximum)

    model = initialize_model(data, n_hours=interval)
    constraint = model.hydro.budget_constraint[1]
    assert not constraint.equality
    assert not constraint.has_lb()
    assert constraint.has_ub()
    assert constraint() <= constraint.upper()

    config = get_default_solver_config_dict(solver_name="highs", executable_path="")
    config["solve_keywords"].update(tee=False, report_timing=False, keepfiles=False)
    results = run_solver(model, config)
    assert results.termination_condition == "optimal"
    assert results.total_cost > 0
    assert check_supply_balance_constraint(results)["is_satisfied"]
    check = check_budget_constraint(model)
    assert check["is_satisfied"], check
    detail = check["budget_details"][0]
    assert detail["generation_sum"] <= maximum + 1e-3
    assert detail["generation_sum"] < detail["ts_sum"]


def test_hydro_budget_validator_reports_all_infeasible_bins():
    data = load_data(
        _abs_data_path("Data/no_exchange_hydro_daily_budget_multiple_balancing_p95")
    )
    _set_budget(data, start_hour=1, interval=DAILY_BUDGET_HOURS_AGGREGATION, budget=0)
    _set_budget(data, start_hour=25, interval=DAILY_BUDGET_HOURS_AGGREGATION, budget=0)

    with pytest.raises(ValueError) as excinfo:
        _validate_hydro_budget_feasibility(data, n_hours=48)

    message = str(excinfo.value)
    assert "bin 1" in message
    assert "bin 2" in message
    assert "lower" in message
    assert "upper violation" not in message
    assert "MWh" in message


@pytest.mark.parametrize(
    ("relative_path", "interval"),
    [
        ("Data/no_exchange_hydro_daily_budget_multiple_balancing_p95", 24),
        ("Data/no_exchange_monthly_hydro_budget_multiple_balancing_p50", 730),
    ],
    ids=["daily", "monthly"],
)
@pytest.mark.parametrize(
    ("dispatch", "is_satisfied"),
    [(5.0, True), (10.0, True), (15.0, False)],
    ids=["unused", "binding", "exceeded"],
)
def test_hydro_budget_constraint_and_checker_enforce_upper_bound(
    relative_path, interval, *, dispatch, is_satisfied
):
    data = load_data(_abs_data_path(relative_path))
    selection = data["formulations"]["Component"] == "Hydro"
    data["formulations"].loc[selection, "Formulation"] = (
        "DailyBudgetUpperBoundFormulation" if interval == 24 else "MonthlyBudgetUpperBoundFormulation"
    )
    data["scalars"].loc["AlphaLargHy", "Value"] = 0.5
    _set_budget(data, start_hour=1, interval=interval, budget=10.0 * interval)
    for key, bound in [("large_hydro_min", 0.0), ("large_hydro_max", 40.0)]:
        _set_bound(data, start_hour=1, interval=interval, bound_key=key, value=bound)

    model = initialize_model(data, n_hours=interval)
    for hour in model.h:
        model.hydro.generation[hour].set_value(dispatch)

    constraint = model.hydro.budget_constraint[1]
    assert not constraint.equality
    assert value(constraint.upper) == pytest.approx(10.0 * interval)
    assert (value(constraint.body) <= value(constraint.upper)) == is_satisfied
    check = check_budget_constraint(model)
    assert check["is_satisfied"] == is_satisfied


@pytest.mark.parametrize(
    ("formulation", "interval"),
    [
        ("DailyBudgetFormulation", 24),
        ("DailyBudgetUpperBoundFormulation", 24),
        ("MonthlyBudgetFormulation", 730),
        ("MonthlyBudgetUpperBoundFormulation", 730),
    ],
)
def test_zonal_hydro_budget_validator_reports_offending_area_during_initialization(formulation, interval):
    data = load_data(_abs_data_path("Data/zonal_test"))
    hydro_formulation = data["formulations"]["Component"] == "Hydro"
    data["formulations"].loc[hydro_formulation, "Formulation"] = formulation
    for hydro_data in data["per_area_hydro"].values():
        hydro_data["LargeHydro_Min"] = 0
        hydro_data["LargeHydro_Max"] = float("inf")

    a1_hydro = data["per_area_hydro"]["A1"]
    first_day = a1_hydro["*Hour"].between(1, interval)
    a1_hydro.loc[first_day, "LargeHydro"] = 0
    a1_hydro.loc[first_day, "LargeHydro_Min"] = 1

    with pytest.raises(
        ValueError, match=rf"{formulation}.*area 'A1'.*bin 1.*lower"
    ):
        initialize_model(data, n_hours=1)


@pytest.mark.parametrize(
    ("formulation", "interval"),
    [("DailyBudgetUpperBoundFormulation", 24), ("MonthlyBudgetUpperBoundFormulation", 730)],
)
def test_zonal_hydro_budget_allows_unused_energy_in_each_period(formulation, interval):
    data = load_data(_abs_data_path("Data/zonal_test"))
    selection = data["formulations"]["Component"] == "Hydro"
    data["formulations"].loc[selection, "Formulation"] = formulation
    for hydro_data in data["per_area_hydro"].values():
        hydro_data["LargeHydro_Min"] = 0
        hydro_data["LargeHydro_Max"] = 0

    model = initialize_model(data, n_hours=interval + 1)
    for area_id in model.A:
        hydro = model.area[area_id].hydro
        assert len(hydro.budget_constraint) == 2
        for constraint in hydro.budget_constraint.values():
            assert not constraint.equality
            assert not constraint.has_lb()
            assert value(constraint.upper) > 0
        check = check_budget_constraint(model.area[area_id])
        assert check["is_satisfied"], check
        assert check["n_budget_periods"] == 2


def test_hydro_budget_validator_skips_run_of_river_data():
    data = load_data(_abs_data_path("Data/no_exchange_run_of_river"))
    data_without_hydro_bounds = copy.deepcopy(data)
    data_without_hydro_bounds["large_hydro_max"] = None
    data_without_hydro_bounds["large_hydro_min"] = None

    _validate_hydro_budget_feasibility(data_without_hydro_bounds, n_hours=24)

    data_without_hydro_bounds["scalars"].loc["AlphaLargHy", "Value"] = 0.5
    model = initialize_model(data_without_hydro_bounds, n_hours=25)
    assert len(model.h) == 25
    assert not hasattr(model.hydro, "budget_constraint")
    assert not hasattr(model.hydro, "upper_bound_ts_constraint")
    for hour in model.h:
        expected = 0.5 * value(model.hydro.ts_parameter[hour])
        model.hydro.generation[hour].set_value(expected)
        constraint = model.hydro.run_of_river_constraint[hour]
        assert constraint.equality
        assert value(constraint.body) == pytest.approx(value(constraint.lower))
