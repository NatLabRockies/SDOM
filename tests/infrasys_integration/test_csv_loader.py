"""Tests for SDOM CSV-to-infrasys System conversion."""

from __future__ import annotations

from pathlib import Path

import pytest

infrasys = pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from sdom import load_data  # noqa: E402
from sdom.infrasys_integration.components import (  # noqa: E402
    SDOMArea,
    SDOMBus,
    SDOMLoad,
    SDOMScalarParameter,
    SDOMSolarGenerator,
    SDOMStorage,
    SDOMThermalGenerator,
    SDOMTransmissionInterface,
    SDOMWindGenerator,
)
from sdom.infrasys_integration.csv_loader import (  # noqa: E402
    load_system,
    load_system_from_data,
    system_to_data_dict,
)
from sdom.infrasys_integration.system import load_system as load_system_from_system_module  # noqa: E402


def _count(system: infrasys.System, component_type: type) -> int:
    """Count components of one type in an infrasys system."""
    return sum(1 for _ in system.get_components(component_type))


def test_load_system_from_data_builds_copperplate_components():
    """Copperplate data should convert to typed infrasys components."""
    data = load_data("Data/no_exchange_run_of_river")

    system = load_system_from_data(data, name="copperplate")

    assert system.name == "copperplate"
    assert _count(system, SDOMArea) == len(data["areas"])
    assert _count(system, SDOMBus) == len(data["areas"])
    assert _count(system, SDOMLoad) == len(data["per_area_demand"])
    assert _count(system, SDOMThermalGenerator) == len(data["thermal_data"])
    assert _count(system, SDOMSolarGenerator) == len(data["solar_plants"])
    assert _count(system, SDOMWindGenerator) == len(data["wind_plants"])
    assert _count(system, SDOMStorage) == len(data["STORAGE_SET_J_TECHS"])
    assert _count(system, SDOMScalarParameter) == len(data["scalars"])


def test_load_system_from_csv_builds_zonal_transmission_components():
    """Zonal data should create areas, buses, and transmission interfaces."""
    assert load_system_from_system_module is load_system
    system = load_system(Path("Data/zonal_test"), name="zonal")
    data = system_to_data_dict(system)

    assert _count(system, SDOMArea) == len(data["areas"])
    assert _count(system, SDOMBus) == len(data["areas"])
    assert _count(system, SDOMTransmissionInterface) == len(data["lines"])
    line = system.get_component(SDOMTransmissionInterface, "line:L_A1_A2")
    assert line.from_bus.name == "A1"
    assert line.to_bus.name == "A2"
    assert line.forward_capacity == pytest.approx(float(data["line_cap_ft"]["L_A1_A2"].max()))


def test_time_series_are_discoverable_on_components():
    """Loaded systems should expose attached time series through infrasys APIs."""
    system = load_system("Data/no_exchange_run_of_river")

    load = system.get_component(SDOMLoad, "load:default")
    solar = system.get_component(SDOMSolarGenerator, f"solar:{system_to_data_dict(system)['solar_plants'][0]}")

    assert system.has_time_series(load, name="active_power")
    assert system.has_time_series(solar, name="capacity_factor")
    assert list(system.list_time_series_keys(load))
    assert list(system.list_time_series_metadata(solar))


def test_system_to_data_dict_preserves_existing_builder_data_without_copying_frames():
    """Compatibility conversion should return existing SDOM data objects."""
    data = load_data("Data/no_exchange_run_of_river")
    system = load_system_from_data(data)

    restored = system_to_data_dict(system)

    assert restored is not data
    assert restored["load_data"] is data["load_data"]
    assert restored["storage_data"] is data["storage_data"]


def test_system_to_data_dict_rejects_unmanaged_system():
    """The compatibility adapter should reject systems it did not create."""
    with pytest.raises(ValueError, match="source data"):
        system_to_data_dict(infrasys.System(name="external"))
