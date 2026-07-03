"""Validation helpers for SDOM infrasys systems."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from infrasys import System

from .models import (
    SDOMArea,
    SDOMBus,
    SDOMExportInterface,
    SDOMGenerator,
    SDOMHydroGenerator,
    SDOMImportInterface,
    SDOMLoad,
    SDOMNuclearGenerator,
    SDOMOtherRenewableGenerator,
    SDOMSolarGenerator,
    SDOMStorage,
    SDOMThermalGenerator,
    SDOMTransmissionInterface,
    SDOMWindGenerator,
)

_REQUIRED_COMPONENT_TYPES = (SDOMArea, SDOMBus, SDOMLoad)
_BUS_CONNECTED_TYPES = (
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
)


def validate_sdom_system(system: System) -> None:
    """Validate core SDOM infrasys System invariants.

    Parameters
    ----------
    system : infrasys.System
        System to validate.

    Returns
    -------
    None
        Returns normally when validation passes.

    Raises
    ------
    ValueError
        If required component types are missing or component associations are
        inconsistent.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> from sdom.infrasys_integration.validation import validate_sdom_system
    >>> system = load_system("Data/no_exchange_run_of_river")
    >>> validate_sdom_system(system)
    """
    validate_required_components(system)
    validate_area_bus_consistency(system)


def validate_required_components(system: System) -> None:
    """Validate that required SDOM component types are present.

    Parameters
    ----------
    system : infrasys.System
        System to validate.

    Returns
    -------
    None
        Returns normally when all required component types are present.

    Raises
    ------
    ValueError
        If areas, buses, or loads are missing.

    Examples
    --------
    >>> from infrasys import System
    >>> from sdom.infrasys_integration.validation import validate_required_components
    >>> validate_required_components(System(name="empty"))
    Traceback (most recent call last):
    ...
    ValueError: SDOM system is missing required component types: SDOMArea, SDOMBus, SDOMLoad
    """
    missing = [component_type.__name__ for component_type in _REQUIRED_COMPONENT_TYPES if not _has_component(system, component_type)]
    if missing:
        raise ValueError(f"SDOM system is missing required component types: {', '.join(missing)}")


def validate_time_series_coverage(system: System, n_hours: int) -> None:
    """Validate attached time-series lengths for an SDOM system.

    Parameters
    ----------
    system : infrasys.System
        System to validate.
    n_hours : int
        Expected number of hourly values in each attached time series.

    Returns
    -------
    None
        Returns normally when every attached time series has ``n_hours``
        values.

    Raises
    ------
    ValueError
        If ``n_hours`` is not positive, no time series are attached, or any
        attached time series has an unexpected length.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> from sdom.infrasys_integration.validation import validate_time_series_coverage
    >>> system = load_system("Data/no_exchange_run_of_river")
    >>> validate_time_series_coverage(system, n_hours=8760)
    """
    if n_hours <= 0:
        raise ValueError(f"n_hours must be positive; got {n_hours}.")

    checked_count = 0
    for component in _iter_sdom_components(system):
        keys = list(system.list_time_series_keys(component))
        if not keys:
            continue
        # Query metadata once per component so validation catches broken
        # time-series metadata associations without loading full arrays.
        metadata = list(system.list_time_series_metadata(component))
        if not metadata:
            raise ValueError(
                f"Time series metadata is not queryable for {component.__class__.__name__} "
                f"'{component.name}'."
            )
        for key in keys:
            checked_count += 1
            length = getattr(key, "length", None)
            if length != n_hours:
                raise ValueError(
                    f"Time series '{key.name}' attached to {component.__class__.__name__} "
                    f"'{component.name}' has length {length}; expected {n_hours}."
                )

    if checked_count == 0:
        raise ValueError("SDOM system does not contain any attached time series.")


def validate_area_bus_consistency(system: System) -> None:
    """Validate area, bus, and bus-connected component associations.

    Parameters
    ----------
    system : infrasys.System
        System to validate.

    Returns
    -------
    None
        Returns normally when area and bus associations are valid.

    Raises
    ------
    ValueError
        If a bus references a missing area, a bus-connected component
        references a missing bus, or a transmission interface references a
        missing endpoint bus.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> from sdom.infrasys_integration.validation import validate_area_bus_consistency
    >>> system = load_system("Data/no_exchange_run_of_river")
    >>> validate_area_bus_consistency(system)
    """
    for bus in system.get_components(SDOMBus):
        _require_component(system, SDOMArea, bus.area.name, owner=bus.name, relationship="area")

    for component_type in _BUS_CONNECTED_TYPES:
        for component in system.get_components(component_type):
            bus = getattr(component, "bus", None)
            if bus is None:
                continue
            _require_component(system, SDOMBus, bus.name, owner=component.name, relationship="bus")
            _require_component(system, SDOMArea, bus.area.name, owner=component.name, relationship="bus.area")

    for interface in system.get_components(SDOMTransmissionInterface):
        _require_component(system, SDOMBus, interface.from_bus.name, owner=interface.name, relationship="from_bus")
        _require_component(system, SDOMBus, interface.to_bus.name, owner=interface.name, relationship="to_bus")


def _has_component(system: System, component_type: type[Any]) -> bool:
    """Return whether a system contains at least one component of a type.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    component_type : type
        Component type to search for.

    Returns
    -------
    bool
        ``True`` when the system contains at least one matching component.

    Examples
    --------
    >>> from infrasys import System
    >>> from sdom.infrasys_integration.models import SDOMArea
    >>> _has_component(System(name="empty"), SDOMArea)
    False
    """
    return next(iter(system.get_components(component_type)), None) is not None


def _iter_sdom_components(system: System) -> Iterable[Any]:
    """Iterate over component types relevant to SDOM validation.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.

    Yields
    ------
    Any
        SDOM component instances from known validation-relevant component
        classes.

    Examples
    --------
    >>> from infrasys import System
    >>> list(_iter_sdom_components(System(name="empty")))
    []
    """
    component_types = (
        SDOMArea,
        SDOMBus,
        *_BUS_CONNECTED_TYPES,
        SDOMTransmissionInterface,
    )
    seen: set[str] = set()
    for component_type in component_types:
        for component in system.get_components(component_type):
            uuid = str(component.uuid)
            if uuid in seen:
                continue
            seen.add(uuid)
            yield component


def _require_component(
    system: System,
    component_type: type[Any],
    name: str,
    *,
    owner: str,
    relationship: str,
) -> None:
    """Require that a named component exists in a system.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    component_type : type
        Required component type.
    name : str
        Required component name.
    owner : str
        Component name that owns the relationship being validated.
    relationship : str
        Human-readable relationship name used in error messages.

    Returns
    -------
    None
        Returns normally when the component exists.

    Raises
    ------
    ValueError
        If the required component cannot be found.

    Examples
    --------
    >>> from infrasys import System
    >>> from sdom.infrasys_integration.models import SDOMBus
    >>> _require_component(System(name="empty"), SDOMBus, "A", owner="load:A", relationship="bus")
    Traceback (most recent call last):
    ...
    ValueError: Component 'load:A' references missing bus SDOMBus 'A'.
    """
    try:
        system.get_component(component_type, name)
    except Exception as exc:
        raise ValueError(
            f"Component '{owner}' references missing {relationship} {component_type.__name__} '{name}'."
        ) from exc


__all__ = [
    "validate_area_bus_consistency",
    "validate_required_components",
    "validate_sdom_system",
    "validate_time_series_coverage",
]
