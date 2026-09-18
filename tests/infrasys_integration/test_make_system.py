"""Tests for SDOM CSV-to-infrasys System conversion."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

infrasys = pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from sdom import load_data  # noqa: E402
from sdom.infrasys_integration.make_system import (  # noqa: E402
    drop_system_source_data,
    load_system,
    load_system_from_data,
    system_to_data_dict,
)
from sdom.infrasys_integration.models import (  # noqa: E402
    GeographicInfo,
    SDOMArea,
    SDOMBus,
    SDOMHydroGenerator,
    SDOMLoad,
    SDOMScalarParameter,
    SDOMSolarGenerator,
    SDOMStorage,
    SDOMThermalGenerator,
    SDOMTransmissionInterface,
    SDOMWindGenerator,
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
    thermal = next(system.get_components(SDOMThermalGenerator))
    storage = next(system.get_components(SDOMStorage))
    assert thermal.ext["asset_status"] == "candidate"
    assert thermal.ext["location_status"] == "allowed_area"
    assert storage.ext["asset_status"] == "candidate"
    assert storage.ext["location_status"] == "allowed_area"


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


@pytest.mark.parametrize(
    ("data_path", "expected_budget_period"),
    [
        ("Data/no_exchange_run_of_river", None),
        ("Data/no_exchange_hydro_daily_budget_multiple_balancing_p95", "daily"),
        ("Data/no_exchange_monthly_hydro_budget_multiple_balancing_p50", "monthly"),
    ],
)
def test_hydro_generators_expose_budget_period_from_formulation(data_path, expected_budget_period):
    """Hydro components should retain the selected budget formulation metadata."""
    system = load_system(data_path)

    hydro_generators = list(system.get_components(SDOMHydroGenerator))

    assert hydro_generators
    assert {generator.budget_period for generator in hydro_generators} == {expected_budget_period}


def test_geographic_supplemental_attributes_are_attached_to_generators_and_buses():
    """Loaded systems should attach geographic metadata where coordinates exist."""
    system = load_system("Data/no_exchange_run_of_river")
    data = system_to_data_dict(system)

    bus = system.get_component(SDOMBus, "default")
    solar = system.get_component(SDOMSolarGenerator, f"solar:{data['solar_plants'][0]}")
    thermal = next(system.get_components(SDOMThermalGenerator))

    bus_attrs = list(system.get_supplemental_attributes_with_component(bus, GeographicInfo))
    solar_attrs = list(system.get_supplemental_attributes_with_component(solar, GeographicInfo))
    thermal_attrs = list(system.get_supplemental_attributes_with_component(thermal, GeographicInfo))

    assert bus_attrs
    assert solar_attrs
    assert thermal_attrs
    assert bus_attrs[0].geo_json.type == "Point"
    assert len(bus_attrs[0].geo_json.coordinates) == 2
    assert solar_attrs[0].source == "per_area_pv_plants"
    assert thermal_attrs[0].source == "derived_area_centroid"


def test_time_series_with_missing_values_raise_clear_error():
    """Missing values should fail instead of shortening time series alignment."""
    data = load_data("Data/no_exchange_run_of_river")
    data["per_area_demand"]["default"].loc[0, "Load"] = float("nan")

    with pytest.raises(ValueError, match=r"Time series 'active_power'.*per_area_demand.*Load"):
        load_system_from_data(data)


def test_missing_thermal_required_attribute_raises_clear_error():
    """Missing thermal required attributes should fail instead of defaulting to zero."""
    data = load_data("Data/no_exchange_run_of_river")
    frame = data["per_area_balancing_units"]["default"]
    plant_id = str(frame.loc[0, "Plant_id"])
    frame.loc[0, "FuelCost"] = float("nan")

    with pytest.raises(
        ValueError,
        match=rf"per_area_balancing_units thermal candidate '{plant_id}'.*requires finite FuelCost",
    ):
        load_system_from_data(data)


def test_negative_thermal_required_attribute_warns_and_raises(caplog):
    """Negative thermal required attributes should warn and fail validation."""
    data = load_data("Data/no_exchange_run_of_river")
    frame = data["per_area_balancing_units"]["default"]
    plant_id = str(frame.loc[0, "Plant_id"])
    frame.loc[0, "HeatRate"] = -1.0

    with caplog.at_level(logging.WARNING), pytest.raises(
        ValueError,
        match=rf"per_area_balancing_units thermal candidate '{plant_id}'.*requires HeatRate",
    ):
        load_system_from_data(data)

    assert "invalid HeatRate=-1.0" in caplog.text


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
    with pytest.raises(ValueError, match=r"load_system\(\) or load_system_from_data\(\)"):
        system_to_data_dict(infrasys.System(name="external"))


def test_drop_system_source_data_removes_compatibility_data():
    """Source-data cleanup should make compatibility conversion unavailable."""
    system = load_system("Data/no_exchange_run_of_river")

    drop_system_source_data(system)
    drop_system_source_data(system)

    with pytest.raises(ValueError, match=r"does not include SDOM source data"):
        system_to_data_dict(system)
