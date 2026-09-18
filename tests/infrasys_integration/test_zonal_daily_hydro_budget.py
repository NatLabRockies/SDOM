"""Daily hydro-budget coverage through the zonal infrasys System API."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from utils_tests import (
    check_budget_constraint,
    check_hydro_budget_matches_csv,
    check_supply_balance_constraint,
    get_n_eq_ineq_constraints,
)

from sdom import OptimizationResults, get_default_solver_config_dict, run_solver
from sdom.infrasys_integration.make_system import load_system
from sdom.infrasys_integration.pyomo_builder import initialize_model_from_system

REPO_ROOT = Path(__file__).resolve().parents[2]
ZONAL_FIXTURE = REPO_ROOT / "Data" / "zonal_test"


def _daily_budget_fixture(tmp_path: Path) -> Path:
    """Create a daily-budget variant without changing the canonical RoR fixture."""
    fixture_dir = tmp_path / "zonal_daily_hydro_budget"
    shutil.copytree(ZONAL_FIXTURE, fixture_dir)

    formulations_path = fixture_dir / "formulations.csv"
    formulations = pd.read_csv(formulations_path)
    formulations.loc[formulations["Component"] == "Hydro", "Formulation"] = (
        "DailyBudgetFormulation"
    )
    formulations.to_csv(formulations_path, index=False)

    hydro = pd.read_csv(fixture_dir / "lahy_hourly.csv")
    tagged_hydro = [column for column in hydro.columns if column.startswith("LargeHydro@")]
    max_bounds = hydro[["*Hour", *tagged_hydro]].rename(
        columns={column: column.replace("LargeHydro", "LargeHydro_Max", 1) for column in tagged_hydro}
    )
    min_bounds = max_bounds.copy()
    min_bounds.loc[:, min_bounds.columns != "*Hour"] = 0.0
    max_bounds.to_csv(fixture_dir / "lahy_max_hourly.csv", index=False)
    min_bounds.to_csv(fixture_dir / "lahy_min_hourly.csv", index=False)
    return fixture_dir


def _highs_config() -> dict:
    """Return quiet HiGHS configuration for deterministic integration tests."""
    config = get_default_solver_config_dict(solver_name="highs", executable_path="")
    config["solve_keywords"].update(tee=False, report_timing=False, keepfiles=False)
    return config


def test_zonal_daily_hydro_budget_system_builds_and_solves(tmp_path):
    """System-built zonal daily budgets should match direct public API invariants."""
    fixture_dir = _daily_budget_fixture(tmp_path)
    system = load_system(fixture_dir)

    model = initialize_model_from_system(system, n_hours=168).create_instance()
    counts = get_n_eq_ineq_constraints(model)
    assert counts["equality"] > 0
    assert counts["inequality"] > 0

    results = run_solver(model, _highs_config(), case_name="zonal_daily_hydro_system")
    assert results.termination_condition == "optimal"
    assert results.total_cost > 0
    assert results.total_cap_wind >= 0
    assert results.total_cap_pv >= 0

    supply_balance = check_supply_balance_constraint(results)
    assert supply_balance["is_satisfied"], supply_balance

    for area_id in model.A:
        budget = check_budget_constraint(model.area[area_id])
        assert budget["is_satisfied"], budget
        assert budget["n_budget_periods"] == 7
        assert budget["budget_scalar"] == 24

    csv_budget = check_hydro_budget_matches_csv(results, fixture_dir, budget_hours=24)
    assert csv_budget["is_satisfied"], csv_budget
    assert csv_budget["n_budget_periods"] == 7


@pytest.mark.parametrize(
    ("source_columns", "expected_sum"),
    [
        (["LargeHydro"], 24.0),
        (["LargeHydro@A1@", "LargeHydro@A2@"], 72.0),
    ],
    ids=["literal", "tagged-zonal"],
)
def test_hydro_budget_csv_check_supports_literal_and_tagged_columns(
    tmp_path, source_columns, expected_sum
):
    """CSV matching should accept the legacy column and sum zonal tagged columns."""
    hours = pd.DataFrame({"*Hour": [1, 2]})
    for index, column in enumerate(source_columns, start=1):
        hours[column] = [12.0 * index, 12.0 * index]
    hours.to_csv(tmp_path / "lahy_hourly.csv", index=False)

    results = OptimizationResults(
        generation_df=pd.DataFrame(
            {"Hour": [1, 2], "Hydro Generation (MW)": [expected_sum / 2] * 2}
        )
    )
    check = check_hydro_budget_matches_csv(results, tmp_path, budget_hours=2)

    assert check["is_satisfied"], check
    assert check["budget_details"][0]["csv_parameter_sum"] == expected_sum
