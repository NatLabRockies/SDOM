"""Tests for pre-solve hydro budget feasibility validation."""

from __future__ import annotations

import copy
import os

import pytest

from sdom import initialize_model, load_data
from sdom.constants import (
    DAILY_BUDGET_HOURS_AGGREGATION,
    MONTHLY_BUDGET_HOURS_AGGREGATION,
)
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


def test_hydro_budget_validator_reports_upper_violation_during_initialization():
    data = load_data(
        _abs_data_path("Data/no_exchange_monthly_hydro_budget_multiple_balancing_p50")
    )
    _set_bound(
        data,
        start_hour=1,
        interval=MONTHLY_BUDGET_HOURS_AGGREGATION,
        bound_key="large_hydro_max",
        value=0,
    )

    with pytest.raises(ValueError, match=r"MonthlyBudgetFormulation.*bin 1.*upper"):
        initialize_model(data, n_hours=730)


def test_hydro_budget_validator_reports_all_infeasible_bins():
    data = load_data(
        _abs_data_path("Data/no_exchange_hydro_daily_budget_multiple_balancing_p95")
    )
    _set_budget(data, start_hour=1, interval=DAILY_BUDGET_HOURS_AGGREGATION, budget=0)
    _set_bound(
        data,
        start_hour=25,
        interval=DAILY_BUDGET_HOURS_AGGREGATION,
        bound_key="large_hydro_max",
        value=0,
    )

    with pytest.raises(ValueError) as excinfo:
        _validate_hydro_budget_feasibility(data, n_hours=48)

    message = str(excinfo.value)
    assert "bin 1" in message
    assert "bin 2" in message
    assert "lower" in message
    assert "upper" in message
    assert "MWh" in message


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


def test_hydro_budget_validator_skips_run_of_river_data():
    data = load_data(_abs_data_path("Data/no_exchange_run_of_river"))
    data_without_hydro_bounds = copy.deepcopy(data)
    data_without_hydro_bounds["large_hydro_max"] = None
    data_without_hydro_bounds["large_hydro_min"] = None

    _validate_hydro_budget_feasibility(data_without_hydro_bounds, n_hours=24)
