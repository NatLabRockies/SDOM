"""Tests for VRE minimum-capacity conversion through infrasys."""

from __future__ import annotations

import pytest

infrasys = pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from sdom import load_data  # noqa: E402
from sdom.infrasys_integration.make_system import load_system_from_data, system_to_data_dict  # noqa: E402
from sdom.infrasys_integration.models import SDOMSolarGenerator, SDOMWindGenerator  # noqa: E402
from sdom.infrasys_integration.pyomo_builder import initialize_model_from_system  # noqa: E402
from sdom.infrasys_integration.validation import validate_sdom_system  # noqa: E402


@pytest.mark.parametrize(
    ("capacity_key", "per_area_key", "component_type", "component_prefix"),
    [
        ("cap_solar", "per_area_pv_plants", SDOMSolarGenerator, "solar"),
        ("cap_wind", "per_area_wind_plants", SDOMWindGenerator, "wind"),
    ],
)
def test_vre_min_capacity_maps_to_system_and_back(
    capacity_key,
    per_area_key,
    component_type,
    component_prefix,
):
    """VRE minimums should map to components and authoritatively project back."""
    data = load_data("Data/no_exchange_run_of_river")
    capacity = data[capacity_key].copy()
    plant_id = str(capacity.loc[0, "sc_gid"])
    minimum = float(capacity.loc[0, "capacity"]) * 0.2
    capacity.loc[0, "MinCapacity"] = minimum
    data[capacity_key] = capacity
    data[per_area_key]["default"] = capacity.copy()

    system = load_system_from_data(data)
    generator = system.get_component(component_type, f"{component_prefix}:{plant_id}")
    assert generator.min_active_power == pytest.approx(minimum)
    assert "MinCapacity" not in generator.ext

    generator.min_active_power = minimum * 2
    restored = system_to_data_dict(system)
    assert restored[capacity_key] is not data[capacity_key]
    assert restored[per_area_key]["default"] is not data[per_area_key]["default"]
    assert restored[capacity_key].loc[0, "MinCapacity"] == pytest.approx(minimum * 2)
    assert restored[per_area_key]["default"].loc[0, "MinCapacity"] == pytest.approx(minimum * 2)
    assert restored["load_data"] is data["load_data"]


def test_vre_system_min_capacity_is_used_by_pyomo_builder():
    """System-originated VRE minimums should constrain the constructed Pyomo model."""
    data = load_data("Data/no_exchange_run_of_river")
    capacity = data["cap_solar"].copy()
    plant_id = str(capacity.loc[0, "sc_gid"])
    minimum = float(capacity.loc[0, "capacity"]) * 0.3
    capacity.loc[0, "MinCapacity"] = minimum
    data["cap_solar"] = capacity
    data["per_area_pv_plants"]["default"] = capacity.copy()

    system = load_system_from_data(data)
    model = initialize_model_from_system(system, n_hours=24).create_instance()

    assert model.pv.capacity_fraction[plant_id].lb == pytest.approx(0.3)


def test_zonal_vre_system_min_capacity_is_used_by_pyomo_builder():
    """A System-built zonal model should retain the owning area's VRE lower bound."""
    data = load_data("Data/zonal_test")
    area_id = next(iter(data["per_area_pv_plants"]))
    capacity = data["per_area_pv_plants"][area_id].copy()
    plant_id = str(capacity.loc[0, "sc_gid"])
    minimum = float(capacity.loc[0, "capacity"]) * 0.4
    capacity.loc[0, "MinCapacity"] = minimum
    data["per_area_pv_plants"][area_id] = capacity
    data["cap_solar"] = data["cap_solar"].copy()
    data["cap_solar"].loc[
        data["cap_solar"]["sc_gid"].astype(str) == plant_id,
        "MinCapacity",
    ] = minimum

    system = load_system_from_data(data)
    model = initialize_model_from_system(system, n_hours=24).create_instance()

    assert model.area[area_id].pv.capacity_fraction[plant_id].lb == pytest.approx(0.4)


def test_vre_system_validation_rejects_minimum_above_maximum():
    """System validation should reject VRE components with inverted capacity bounds."""
    system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
    generator = next(system.get_components(SDOMSolarGenerator))
    generator.min_active_power = float(generator.max_active_power) + 1.0

    with pytest.raises(ValueError, match=r"VRE solar generator.*MinCapacity"):
        validate_sdom_system(system)