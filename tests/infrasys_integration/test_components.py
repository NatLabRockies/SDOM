"""Tests for SDOM infrasys component models."""

from __future__ import annotations

import importlib
from typing import get_args, get_type_hints

import pytest

infrasys = pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from r2x_core.units import Unit  # noqa: E402

from sdom.infrasys_integration.models import (  # noqa: E402
    SDOMArea,
    SDOMBus,
    SDOMComponent,
    SDOMExportInterface,
    SDOMFormulationConfig,
    SDOMGenerator,
    SDOMHydroGenerator,
    SDOMImportInterface,
    SDOMLoad,
    SDOMNuclearGenerator,
    SDOMOtherRenewableGenerator,
    SDOMScalarParameter,
    SDOMSolarGenerator,
    SDOMStorage,
    SDOMThermalGenerator,
    SDOMTransmissionInterface,
    SDOMWindGenerator,
)
from sdom.infrasys_integration.models.static_injection import (  # noqa: E402
    SDOMStorage as StaticInjectionSDOMStorage,
)
from sdom.infrasys_integration.models.topology import SDOMBus as TopologySDOMBus  # noqa: E402

System = infrasys.System


def _make_bus() -> SDOMBus:
    """Create a representative bus for component construction tests."""
    area = SDOMArea(
        name="default-area",
        country="US",
        max_active_power=1000.0,
        timezone="America/Denver",
    )
    return SDOMBus(name="default-bus", area=area)


def test_package_namespace_imports_without_optional_component_imports():
    """The integration namespace should import as an opt-in package."""
    module = importlib.import_module("sdom.infrasys_integration")

    assert module.__name__ == "sdom.infrasys_integration"


def test_model_package_exports_match_domain_module_imports():
    """Model package exports should match domain module class identities."""
    assert TopologySDOMBus is SDOMBus
    assert StaticInjectionSDOMStorage is SDOMStorage


def test_core_components_share_sdom_component_base():
    """All first-slice system component models should inherit SDOMComponent."""
    component_types = [
        SDOMArea,
        SDOMBus,
        SDOMLoad,
        SDOMGenerator,
        SDOMThermalGenerator,
        SDOMSolarGenerator,
        SDOMWindGenerator,
        SDOMHydroGenerator,
        SDOMNuclearGenerator,
        SDOMOtherRenewableGenerator,
        SDOMStorage,
        SDOMImportInterface,
        SDOMExportInterface,
        SDOMTransmissionInterface,
        SDOMScalarParameter,
        SDOMFormulationConfig,
    ]

    assert all(issubclass(component_type, SDOMComponent) for component_type in component_types)


def test_bus_has_explicit_name_field():
    """Buses should expose an explicit string name field."""
    bus = _make_bus()

    assert isinstance(bus.name, str)
    assert bus.name == "default-bus"
    assert SDOMBus.model_fields["name"].annotation is str


def test_area_and_bus_model_asset_location_hierarchy():
    """Assets should reference buses and buses should reference areas."""
    bus = _make_bus()
    generator = SDOMThermalGenerator(
        name="thermal-1",
        bus=bus,
        technology="Thermal",
        min_active_power=0.0,
        max_active_power=100.0,
        heat_rate=9.5,
        fuel_cost=3.0,
    )

    assert bus.area.name == "default-area"
    assert generator.bus is bus
    assert generator.bus.area.country == "US"


def test_generator_fields_include_documented_cost_inputs():
    """Generator fields should cover documented CAPEX/FOM/transmission costs."""
    bus = _make_bus()
    generator = SDOMGenerator(
        name="generic",
        bus=bus,
        technology="Generic",
        capex=1200.0,
        fom=30.0,
        trans_cap_cost=100.0,
    )

    assert generator.capex == 1200.0
    assert generator.fom == 30.0
    assert generator.trans_cap_cost == 100.0


def test_thermal_generator_tightens_base_generator_contract():
    """Thermal generators should require heat-rate and fuel-cost fields."""
    bus = _make_bus()
    generic = SDOMGenerator(name="generic", bus=bus, technology="Generic")

    assert generic.heat_rate is None
    assert generic.fuel_cost is None
    with pytest.raises(ValueError, match="heat_rate"):
        SDOMThermalGenerator(name="missing-thermal-data", bus=bus, technology="Thermal")


def test_component_validation_rejects_invalid_values():
    """Pydantic validation should reject negative power values."""
    bus = _make_bus()

    with pytest.raises(ValueError, match="greater than or equal to 0"):
        SDOMThermalGenerator(
            name="bad-thermal",
            bus=bus,
            technology="Thermal",
            max_active_power=-1.0,
            heat_rate=9.5,
            fuel_cost=3.0,
        )


def test_unit_annotated_component_field_validates_structured_input():
    """Unit metadata should be present and accept a structured quantity input."""
    annotation = get_type_hints(SDOMLoad, include_extras=True)["peak_active_power"]
    metadata = get_args(get_args(annotation)[0])[1:]

    assert any(isinstance(item, type(Unit("MW"))) for item in metadata)

    load = SDOMLoad(
        name="structured-load",
        bus=_make_bus(),
        peak_active_power={"value": 250.0, "unit": "MW"},
    )

    assert load.peak_active_power == 250.0


def test_storage_duration_bounds_are_validated():
    """Storage duration lower bound should not exceed upper bound."""
    bus = _make_bus()

    with pytest.raises(ValueError, match="min_duration"):
        SDOMStorage(
            name="bad-storage",
            bus=bus,
            technology="Battery",
            min_duration=8.0,
            max_duration=4.0,
        )


def test_components_can_be_added_to_infrasys_system():
    """Representative components should be accepted by infrasys.System."""
    bus = _make_bus()
    load = SDOMLoad(name="load", bus=bus, peak_active_power=250.0)
    storage = SDOMStorage(
        name="storage",
        bus=bus,
        technology="PHS",
        max_power_capacity=50.0,
        max_energy_capacity=400.0,
        power_capex=1500.0,
        energy_capex=10.0,
        round_trip_efficiency=0.8,
        max_cycles=10_000,
        coupled=True,
        lifetime=30,
        cost_ratio=0.5,
    )
    line = SDOMTransmissionInterface(
        name="line",
        from_bus=bus,
        to_bus=SDOMBus(name="remote-bus", area=bus.area),
        forward_capacity=100.0,
        reverse_capacity=75.0,
    )

    system = System(name="SDOM test")
    system.add_component(bus.area)
    system.add_component(bus)
    system.add_component(load)
    system.add_component(storage)
    system.add_component(line.to_bus)
    system.add_component(line)

    assert system.get_component(SDOMArea, "default-area").name == "default-area"
    assert system.get_component(SDOMBus, "default-bus").area.name == "default-area"
    assert system.get_component(SDOMStorage, "storage").technology == "PHS"
    assert system.get_component(SDOMTransmissionInterface, "line").from_bus.name == "default-bus"
