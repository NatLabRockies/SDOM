"""Tests for Pyomo builders from SDOM infrasys systems."""

from __future__ import annotations

import pytest
from pyomo.environ import AbstractModel, value
from pyomo.opt import SolverFactory

pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from utils_tests import (
    check_budget_constraint,
    check_hydro_budget_matches_csv,
    check_supply_balance_constraint,
)

from sdom import get_default_solver_config_dict, initialize_model, load_data, run_solver
from sdom.infrasys_integration.make_system import load_system, load_system_from_data
from sdom.infrasys_integration.pyomo_builder import (
    initialize_copperplate_model_from_system,
    initialize_model_from_system,
)


def _highs_available() -> bool:
    """Return whether the HiGHS appsi solver is available."""
    return SolverFactory("appsi_highs").available(exception_flag=False)


def _highs_solver_config() -> dict:
    """Return a quiet HiGHS solver config for parity tests."""
    solver_config = get_default_solver_config_dict(solver_name="highs")
    solver_config["solve_keywords"]["tee"] = False
    solver_config["solve_keywords"]["keepfiles"] = False
    solver_config["solve_keywords"]["report_timing"] = False
    return solver_config


def test_initialize_model_from_system_returns_abstract_model_builder():
    """System-based Pyomo construction should expose an AbstractModel builder."""
    system = load_system("Data/no_exchange_run_of_river")

    abstract_model = initialize_model_from_system(system, n_hours=24)

    assert isinstance(abstract_model, AbstractModel)
    assert not abstract_model.is_constructed()


def test_copperplate_abstract_model_instantiates_existing_compatibility_path():
    """The AbstractModel builder should instantiate the legacy copperplate body."""
    data = load_data("Data/no_exchange_run_of_river")
    system = load_system_from_data(data)

    abstract_model = initialize_copperplate_model_from_system(system, n_hours=24)
    instance = abstract_model.create_instance()
    direct = initialize_model(data, n_hours=24)

    assert instance.is_constructed()
    assert list(instance.h) == list(direct.h)
    assert list(instance.storage.j) == list(direct.storage.j)
    assert list(instance.thermal.plants_set) == list(direct.thermal.plants_set)
    assert value(instance.GenMix_Target) == pytest.approx(value(direct.GenMix_Target))


def test_exchange_dataset_instantiates_from_system():
    """Exchange copperplate data should instantiate from the System path."""
    system = load_system("Data/exchange_hydro_daily_budget_multiple_balancing_p95")

    instance = initialize_model_from_system(system, n_hours=24).create_instance()

    assert instance.is_constructed()
    assert hasattr(instance, "imports")
    assert hasattr(instance, "exports")
    assert len(list(instance.h)) == 24


def test_builder_options_propagate_to_instance():
    """Builder options should be applied when create_instance() is called."""
    system = load_system("Data/no_exchange_run_of_river")

    instance = initialize_model_from_system(
        system,
        n_hours=24,
        with_resilience_constraints=True,
        model_name="Custom_SDOM",
    ).create_instance()

    assert instance.name == "Custom_SDOM"
    assert hasattr(instance, "resiliency")


@pytest.mark.skipif(not _highs_available(), reason="appsi_highs solver is not available")
def test_system_path_solves_with_highs_and_matches_dict_path_objective():
    """System and dict paths should solve to matching objectives with HiGHS."""
    data = load_data("Data/no_exchange_run_of_river")
    system = load_system_from_data(data)
    solver_config = _highs_solver_config()

    system_instance = initialize_model_from_system(system, n_hours=24).create_instance()
    direct_instance = initialize_model(data, n_hours=24)
    system_results = run_solver(system_instance, solver_config, case_name="system")
    direct_results = run_solver(direct_instance, solver_config, case_name="dict")

    assert system_results.is_optimal
    assert direct_results.is_optimal
    assert system_results.total_cost == pytest.approx(direct_results.total_cost)
    assert system_results.capacity == pytest.approx(direct_results.capacity)


@pytest.mark.skipif(not _highs_available(), reason="appsi_highs solver is not available")
def test_exchange_system_path_solves_with_highs_and_matches_dict_path_assertions():
    """Exchange System path should solve like the legacy dict API path."""
    data = load_data("Data/exchange_hydro_daily_budget_multiple_balancing_p95")
    system = load_system_from_data(data)
    solver_config = _highs_solver_config()

    system_instance = initialize_model_from_system(system, n_hours=168).create_instance()
    direct_instance = initialize_model(data, n_hours=168)
    system_results = run_solver(system_instance, solver_config, case_name="system_exchange")
    direct_results = run_solver(direct_instance, solver_config, case_name="dict_exchange")

    assert system_results.is_optimal
    assert direct_results.is_optimal
    assert system_results.total_cost == pytest.approx(direct_results.total_cost)
    assert system_results.capacity == pytest.approx(direct_results.capacity)
    assert system_results.storage_capacity.keys() == direct_results.storage_capacity.keys()
    for capacity_type, capacities in system_results.storage_capacity.items():
        assert capacities == pytest.approx(direct_results.storage_capacity[capacity_type])

    system_supply_balance = check_supply_balance_constraint(system_results)
    direct_supply_balance = check_supply_balance_constraint(direct_results)
    assert system_supply_balance["is_satisfied"], system_supply_balance["violations"]
    assert direct_supply_balance["is_satisfied"], direct_supply_balance["violations"]
    assert bool(system_supply_balance["has_exports"])
    assert system_supply_balance["has_imports"] == direct_supply_balance["has_imports"]
    assert system_supply_balance["has_exports"] == direct_supply_balance["has_exports"]

    system_budget = check_budget_constraint(system_instance, block_name="hydro")
    direct_budget = check_budget_constraint(direct_instance, block_name="hydro")
    assert system_budget["is_satisfied"], system_budget["violations"]
    assert direct_budget["is_satisfied"], direct_budget["violations"]
    assert system_budget["n_budget_periods"] == direct_budget["n_budget_periods"] == 7

    csv_budget = check_hydro_budget_matches_csv(
        system_results,
        "Data/exchange_hydro_daily_budget_multiple_balancing_p95",
        budget_hours=24,
    )
    assert csv_budget["is_satisfied"], csv_budget["violations"]
    assert csv_budget["n_budget_periods"] == 7


def test_zonal_system_rejected_by_copperplate_builder():
    """The issue-58 builder should fail clearly for zonal systems."""
    system = load_system("Data/zonal_test")

    with pytest.raises(NotImplementedError, match="single-area CopperPlateNetwork"):
        initialize_model_from_system(system, n_hours=24)


def test_invalid_horizon_rejected():
    """System model construction should reject invalid horizons."""
    system = load_system("Data/no_exchange_run_of_river")

    with pytest.raises(ValueError, match="n_hours must be positive"):
        initialize_model_from_system(system, n_hours=0)
