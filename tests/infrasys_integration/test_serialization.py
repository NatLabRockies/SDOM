"""Tests for SDOM infrasys System serialization and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

infrasys = pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from sdom import load_data  # noqa: E402
from sdom.infrasys_integration.make_system import load_system  # noqa: E402
from sdom.infrasys_integration.models import (  # noqa: E402
    SDOMArea,
    SDOMBus,
    SDOMLoad,
    SDOMSolarGenerator,
    SDOMTransmissionInterface,
)
from sdom.infrasys_integration.validation import (  # noqa: E402
    validate_area_bus_consistency,
    validate_required_components,
    validate_sdom_system,
    validate_time_series_coverage,
)

System = infrasys.System


def _count(system: System, component_type: type) -> int:
    """Count components of one type in an infrasys system."""
    return sum(1 for _ in system.get_components(component_type))


def _round_trip(system: System, path: Path) -> System:
    """Serialize and reload an infrasys system through JSON persistence."""
    system.to_json(path, overwrite=True)
    return System.from_json(path)


def test_copperplate_system_round_trips_without_losing_components(tmp_path):
    """Copperplate systems should preserve components and associations."""
    system = load_system("Data/no_exchange_run_of_river", name="copperplate")
    n_hours = len(load_data("Data/no_exchange_run_of_river")["load_data"])

    loaded = _round_trip(system, tmp_path / "copperplate.json")

    assert _count(loaded, SDOMArea) == _count(system, SDOMArea)
    assert _count(loaded, SDOMBus) == _count(system, SDOMBus)
    assert _count(loaded, SDOMLoad) == _count(system, SDOMLoad)
    validate_sdom_system(loaded)
    validate_time_series_coverage(loaded, n_hours=n_hours)


def test_zonal_system_round_trips_without_losing_topology(tmp_path):
    """Zonal systems should preserve areas, buses, and interfaces."""
    system = load_system("Data/zonal_test", name="zonal")
    n_hours = len(load_data("Data/zonal_test")["load_data"])

    loaded = _round_trip(system, tmp_path / "zonal.json")

    assert _count(loaded, SDOMArea) == _count(system, SDOMArea)
    assert _count(loaded, SDOMBus) == _count(system, SDOMBus)
    assert _count(loaded, SDOMTransmissionInterface) == _count(system, SDOMTransmissionInterface)
    interface = loaded.get_component(SDOMTransmissionInterface, "line:L_A1_A2")
    assert interface.from_bus.area.name == "A1"
    assert interface.to_bus.area.name == "A2"
    validate_area_bus_consistency(loaded)
    validate_time_series_coverage(loaded, n_hours=n_hours)


def test_time_series_metadata_remains_queryable_after_reload(tmp_path):
    """Reloaded systems should preserve queryable time-series metadata."""
    system = load_system("Data/no_exchange_run_of_river")

    loaded = _round_trip(system, tmp_path / "metadata.json")
    load = loaded.get_component(SDOMLoad, "load:default")
    solar = loaded.get_component(SDOMSolarGenerator, "solar:132876")

    assert loaded.has_time_series(load, name="active_power")
    assert loaded.has_time_series(solar, name="capacity_factor")
    assert list(loaded.list_time_series_metadata(load))
    assert list(loaded.list_time_series_metadata(solar))


def test_validate_required_components_reports_missing_types():
    """Validation failures should describe missing required components."""
    with pytest.raises(ValueError, match="SDOMArea, SDOMBus, SDOMLoad"):
        validate_required_components(System(name="empty"))


def test_validate_time_series_coverage_reports_wrong_length():
    """Time-series validation should report component and series names."""
    system = load_system("Data/no_exchange_run_of_river")

    with pytest.raises(ValueError, match=r"active_power.*load:default.*expected 1"):
        validate_time_series_coverage(system, n_hours=1)
