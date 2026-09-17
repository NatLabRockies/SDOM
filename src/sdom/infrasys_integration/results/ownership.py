"""Result-owner lookup helpers for SDOM system components."""

from __future__ import annotations

from infrasys import System

from ..models import SDOMArea, SDOMBus, SDOMComponent, SDOMStorage
from .helpers import DEFAULT_COPPERPLATE_AREA_NAME


def _get_scenario_owner(system: System) -> SDOMComponent:
    """Return the component that owns run-level results.

    Parameters
    ----------
    system : infrasys.System
        System containing SDOM components.

    Returns
    -------
    SDOMComponent
        First area component by name, or the first SDOM component when no area
        component exists.

    Raises
    ------
    ValueError
        If the system has no SDOM components.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> _get_scenario_owner(load_system("Data/no_exchange_run_of_river")).name
    'default'
    """
    areas = sorted(system.get_components(SDOMArea), key=lambda area: area.name)
    if areas:
        return areas[0]
    try:
        return next(iter(system.get_components(SDOMComponent)))
    except StopIteration as exc:
        raise ValueError("system must contain at least one SDOM component.") from exc


def _get_default_area(system: System) -> SDOMArea:
    """Return the default area used for copperplate result ownership.

    Parameters
    ----------
    system : infrasys.System
        System containing SDOM components.

    Returns
    -------
    SDOMArea
        First existing area by name.

    Raises
    ------
    ValueError
        If the system has no area component.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> isinstance(_get_default_area(load_system("Data/no_exchange_run_of_river")), SDOMArea)
    True
    """
    areas = sorted(system.get_components(SDOMArea), key=lambda area: area.name)
    if not areas:
        raise ValueError(f"system must contain an SDOMArea such as {DEFAULT_COPPERPLATE_AREA_NAME!r}.")
    return areas[0]


def _area_name_from_owner(system: System, owner: SDOMComponent) -> str | None:
    """Return an owner's area name while enforcing area-bus consistency.

    Parameters
    ----------
    system : infrasys.System
        System containing the owner component.
    owner : SDOMComponent
        Result attribute owner.

    Returns
    -------
    str | None
        Area name derived from the owner, or ``None`` when the owner is not
        area-associated.

    Raises
    ------
    ValueError
        If ``owner`` is an :class:`SDOMArea` with no associated bus.

    Examples
    --------
    >>> from infrasys import System
    >>> system = System(name="example")
    >>> area = SDOMArea(name="A")
    >>> system.add_component(area)
    >>> _area_name_from_owner(system, area)
    Traceback (most recent call last):
    ...
    ValueError: SDOMArea 'A' must own at least one SDOMBus.
    """
    if isinstance(owner, SDOMArea):
        for bus in system.get_components(SDOMBus):
            if bus.area.name == owner.name:
                return owner.name
        raise ValueError(f"SDOMArea {owner.name!r} must own at least one SDOMBus.")
    if hasattr(owner, "bus"):
        return owner.bus.area.name
    return None



def _component_by_name(system: System) -> dict[str, SDOMComponent]:
    """Return SDOM components keyed by component name.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.

    Returns
    -------
    dict[str, SDOMComponent]
        Component lookup keyed by name.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> "default" in _component_by_name(load_system("Data/no_exchange_run_of_river"))
    True
    """
    return {component.name: component for component in system.get_components(SDOMComponent)}


def _storage_by_area_and_technology(system: System) -> dict[tuple[str | None, str], SDOMStorage]:
    """Return storage components keyed by area and technology.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.

    Returns
    -------
    dict[tuple[str | None, str], SDOMStorage]
        Storage lookup by ``(area, technology)`` and fallback ``(None, technology)``.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> bool(_storage_by_area_and_technology(load_system("Data/no_exchange_run_of_river")))
    True
    """
    lookup: dict[tuple[str | None, str], SDOMStorage] = {}
    for storage in system.get_components(SDOMStorage):
        area = storage.bus.area.name if getattr(storage, "bus", None) is not None else None
        lookup[(area, storage.technology)] = storage
        lookup.setdefault((None, storage.technology), storage)
    return lookup
