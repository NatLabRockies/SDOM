"""Tests for pre-solve hydro budget feasibility validation."""

from __future__ import annotations

import copy
import os

import pytest
from pyomo.environ import value
from utils_tests import check_budget_constraint, check_supply_balance_constraint

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


def test_hydro_budget_validator_reports_lower_violation_during_initialization():
    data = load_data(
        _abs_data_path("Data/no_exchange_hydro_daily_budget_multiple_balancing_p95")
    )
    _set_budget(data, start_hour=1, interval=DAILY_BUDGET_HOURS_AGGREGATION, budget=0)

    with pytest.raises(ValueError, match=r"DailyBudgetFormulation.*bin 1.*lower"):
        initialize_model(data, n_hours=24)


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


def test_zonal_hydro_budget_validator_reports_offending_area_during_initialization():
    data = load_data(_abs_data_path("Data/zonal_test"))
    hydro_formulation = data["formulations"]["Component"] == "Hydro"
    data["formulations"].loc[hydro_formulation, "Formulation"] = (
        "DailyBudgetFormulation"
    )
    for hydro_data in data["per_area_hydro"].values():
        hydro_data["LargeHydro_Min"] = 0
        hydro_data["LargeHydro_Max"] = float("inf")

    a1_hydro = data["per_area_hydro"]["A1"]
    first_day = a1_hydro["*Hour"].between(1, DAILY_BUDGET_HOURS_AGGREGATION)
    a1_hydro.loc[first_day, "LargeHydro"] = 0
    a1_hydro.loc[first_day, "LargeHydro_Min"] = 1

    with pytest.raises(
        ValueError, match=r"DailyBudgetFormulation.*area 'A1'.*bin 1.*lower"
    ):
        initialize_model(data, n_hours=24)


def test_zonal_hydro_budget_allows_unused_energy_in_each_period():
    data = load_data(_abs_data_path("Data/zonal_test"))
    selection = data["formulations"]["Component"] == "Hydro"
    data["formulations"].loc[selection, "Formulation"] = "DailyBudgetFormulation"
    for hydro_data in data["per_area_hydro"].values():
        hydro_data["LargeHydro_Min"] = 0
        hydro_data["LargeHydro_Max"] = 0

    model = initialize_model(data, n_hours=48)
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
