"""Tests for optional VRE minimum installed capacity inputs."""

from __future__ import annotations

import copy
import os

import numpy as np
import pytest
from pyomo.environ import SolverFactory, value

from sdom import get_default_solver_config_dict, initialize_model, load_data, run_solver


def _data_path(relative_path: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", relative_path))


@pytest.mark.parametrize(
    ("capacity_key", "block_name"),
    [("cap_solar", "pv"), ("cap_wind", "wind")],
)
def test_vre_min_capacity_sets_capacity_fraction_lower_bound(capacity_key, block_name):
    """VRE MinCapacity should become a per-plant Pyomo lower bound."""
    data = load_data(_data_path("Data/no_exchange_run_of_river"))
    capacity = data[capacity_key].copy()
    plant_id = str(capacity.loc[0, "sc_gid"])
    maximum = float(capacity.loc[0, "capacity"])
    capacity.loc[0, "MinCapacity"] = maximum * 0.25
    data[capacity_key] = capacity
    per_area_key = "per_area_pv_plants" if block_name == "pv" else "per_area_wind_plants"
    data[per_area_key]["default"] = capacity.copy()

    model = initialize_model(data, n_hours=24, with_resilience_constraints=False)

    assert getattr(model, block_name).capacity_fraction[plant_id].lb == pytest.approx(0.25)


@pytest.mark.parametrize("invalid_minimum", [-1.0, "not-a-number", np.inf])
def test_vre_min_capacity_rejects_invalid_values(invalid_minimum):
    """Negative, nonnumeric, and nonfinite VRE minimums should fail clearly."""
    data = load_data(_data_path("Data/no_exchange_run_of_river"))
    capacity = data["cap_solar"].copy()
    plant_id = str(capacity.loc[0, "sc_gid"])
    capacity.loc[0, "MinCapacity"] = invalid_minimum
    data["cap_solar"] = capacity
    data["per_area_pv_plants"]["default"] = capacity.copy()

    with pytest.raises(ValueError, match=rf"cap_solar.*solar.*{plant_id}.*MinCapacity"):
        initialize_model(data, n_hours=24, with_resilience_constraints=False)


def test_vre_min_capacity_rejects_value_above_capacity_and_zero_capacity_conflict():
    """VRE minimums must not exceed their capacity or require a zero-capacity plant."""
    data = load_data(_data_path("Data/no_exchange_run_of_river"))
    capacity = data["cap_wind"].copy()
    plant_id = str(capacity.loc[0, "sc_gid"])
    capacity.loc[0, "MinCapacity"] = float(capacity.loc[0, "capacity"]) + 1.0
    data["cap_wind"] = capacity
    data["per_area_wind_plants"]["default"] = capacity.copy()

    with pytest.raises(ValueError, match=rf"cap_wind.*wind.*{plant_id}.*MinCapacity"):
        initialize_model(data, n_hours=24, with_resilience_constraints=False)

    capacity.loc[0, "capacity"] = 0.0
    capacity.loc[0, "MinCapacity"] = 1.0
    data["cap_wind"] = capacity
    data["per_area_wind_plants"]["default"] = capacity.copy()

    with pytest.raises(ValueError, match=rf"cap_wind.*wind.*{plant_id}.*MinCapacity"):
        initialize_model(data, n_hours=24, with_resilience_constraints=False)


@pytest.mark.parametrize("minimum", ["", np.nan])
def test_vre_blank_or_nan_min_capacity_defaults_to_zero(minimum):
    """Blank and NaN VRE minimums should preserve the legacy zero lower bound."""
    data = load_data(_data_path("Data/no_exchange_run_of_river"))
    capacity = data["cap_solar"].copy()
    plant_id = str(capacity.loc[0, "sc_gid"])
    capacity.loc[0, "MinCapacity"] = minimum
    data["cap_solar"] = capacity
    data["per_area_pv_plants"]["default"] = capacity.copy()

    model = initialize_model(data, n_hours=24, with_resilience_constraints=False)

    assert model.pv.capacity_fraction[plant_id].lb == 0.0


def test_vre_zero_capacity_accepts_zero_min_capacity():
    """A zero-capacity VRE candidate should retain the zero lower bound."""
    data = load_data(_data_path("Data/no_exchange_run_of_river"))
    capacity = data["cap_solar"].copy()
    plant_id = str(capacity.loc[0, "sc_gid"])
    capacity.loc[0, "capacity"] = 0.0
    capacity.loc[0, "MinCapacity"] = 0.0
    data["cap_solar"] = capacity
    data["per_area_pv_plants"]["default"] = capacity.copy()

    model = initialize_model(data, n_hours=24, with_resilience_constraints=False)

    assert model.pv.capacity_fraction[plant_id].lb == 0.0


@pytest.mark.skipif(
    not SolverFactory("appsi_highs").available(exception_flag=False),
    reason="appsi_highs solver is not available",
)
def test_vre_min_capacity_is_respected_after_highs_solve():
    """A HiGHS solution should install at least each VRE minimum capacity."""
    data = load_data(_data_path("Data/no_exchange_run_of_river"))
    expected_minimums = {}
    for capacity_key, per_area_key, block_name in (
        ("cap_solar", "per_area_pv_plants", "pv"),
        ("cap_wind", "per_area_wind_plants", "wind"),
    ):
        capacity = data[capacity_key].copy()
        plant_id = str(capacity.loc[0, "sc_gid"])
        minimum = float(capacity.loc[0, "capacity"]) * 0.2
        capacity.loc[0, "MinCapacity"] = minimum
        data[capacity_key] = capacity
        data[per_area_key]["default"] = capacity.copy()
        expected_minimums[block_name] = (plant_id, minimum)

    model = initialize_model(data, n_hours=24, with_resilience_constraints=False)
    solver_config = get_default_solver_config_dict(solver_name="highs", executable_path="")
    results = run_solver(model, solver_config, case_name="vre_min_capacity")

    assert results.is_optimal
    for block_name, (plant_id, minimum) in expected_minimums.items():
        installed_capacity = value(getattr(model, block_name).plant_installed_capacity[plant_id])
        assert installed_capacity >= minimum - 1e-6


def test_zonal_vre_min_capacity_sets_area_block_lower_bound():
    """Per-area VRE tables should enforce minimums in zonal area blocks."""
    data = load_data(_data_path("Data/zonal_test"))
    area_id = next(iter(data["per_area_pv_plants"]))
    capacity = data["per_area_pv_plants"][area_id].copy()
    plant_id = str(capacity.loc[0, "sc_gid"])
    maximum = float(capacity.loc[0, "capacity"])
    capacity.loc[0, "MinCapacity"] = maximum * 0.5
    data["per_area_pv_plants"][area_id] = capacity
    data["cap_solar"] = data["cap_solar"].copy()
    data["cap_solar"].loc[data["cap_solar"]["sc_gid"].astype(str) == plant_id, "MinCapacity"] = maximum * 0.5

    model = initialize_model(data, n_hours=24, with_resilience_constraints=False)

    assert model.area[area_id].pv.capacity_fraction[plant_id].lb == pytest.approx(0.5)