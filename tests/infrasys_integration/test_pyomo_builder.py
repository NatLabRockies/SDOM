"""Tests for Pyomo builders from SDOM infrasys systems."""

from __future__ import annotations

import pytest
from pyomo.environ import AbstractModel, value
from pyomo.opt import SolverFactory

pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from sdom import get_default_solver_config_dict, initialize_model, load_data, run_solver
from sdom.infrasys_integration.make_system import load_system, load_system_from_data
from sdom.infrasys_integration.pyomo_builder import (
    initialize_copperplate_model_from_system,
    initialize_model_from_system,
)


def _highs_available() -> bool:
    """Return whether the HiGHS appsi solver is available."""
    return SolverFactory("appsi_highs").available(exception_flag=False)


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


@pytest.mark.skipif(not _highs_available(), reason="appsi_highs solver is not available")
def test_system_path_solves_with_highs_and_matches_dict_path_objective():
    """System and dict paths should solve to matching objectives with HiGHS."""
    data = load_data("Data/no_exchange_run_of_river")
    system = load_system_from_data(data)
    solver_config = get_default_solver_config_dict(solver_name="highs")
    solver_config["solve_keywords"]["tee"] = False
    solver_config["solve_keywords"]["keepfiles"] = False
    solver_config["solve_keywords"]["report_timing"] = False

    system_instance = initialize_model_from_system(system, n_hours=24).create_instance()
    direct_instance = initialize_model(data, n_hours=24)
    system_results = run_solver(system_instance, solver_config, case_name="system")
    direct_results = run_solver(direct_instance, solver_config, case_name="dict")

    assert system_results.is_optimal
    assert direct_results.is_optimal
    assert system_results.total_cost == pytest.approx(direct_results.total_cost)
    assert system_results.capacity == pytest.approx(direct_results.capacity)


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
