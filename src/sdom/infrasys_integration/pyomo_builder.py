"""Pyomo builder entry points for SDOM infrasys systems."""

from __future__ import annotations

from types import MethodType
from typing import Any

from infrasys import System
from pyomo.environ import AbstractModel, ConcreteModel

from sdom.constants import COPPER_PLATE_NETWORK, DEFAULT_AREA_ID
from sdom.io_manager import get_network_formulation
from sdom.optimization_main import initialize_model

from .make_system import system_to_data_dict
from .models import SDOMArea, SDOMBus, SDOMTransmissionInterface
from .validation import validate_sdom_system


def initialize_model_from_system(
    system: System,
    n_hours: int = 8760,
    *,
    with_resilience_constraints: bool = False,
    model_name: str = "SDOM_Model",
) -> AbstractModel:
    """Create an AbstractModel-backed SDOM builder from an infrasys system.

    Parameters
    ----------
    system : infrasys.System
        SDOM infrasys system produced by
        :func:`sdom.infrasys_integration.make_system.load_system` or
        :func:`sdom.infrasys_integration.make_system.load_system_from_data`.
    n_hours : int, default=8760
        Number of hours captured by the abstract builder and applied when
        ``create_instance()`` instantiates the model.
    with_resilience_constraints : bool, default=False
        Whether to include SDOM resilience constraints in the instantiated
        model.
    model_name : str, default="SDOM_Model"
        Name assigned to the Pyomo model builder and generated instance.

    Returns
    -------
    pyomo.environ.AbstractModel
        AbstractModel builder. Call ``create_instance()`` to produce the
        concrete SDOM model used by existing solver and results code.

    Raises
    ------
    ValueError
        If ``n_hours`` is not positive or the System topology is inconsistent
        with its SDOM source data.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> from sdom.infrasys_integration.pyomo_builder import initialize_model_from_system
    >>> system = load_system("Data/no_exchange_run_of_river")
    >>> abstract_model = initialize_model_from_system(system, n_hours=24)
    >>> abstract_model.is_constructed()
    False
    """
    return _initialize_abstract_model_from_system(
        system,
        n_hours=n_hours,
        with_resilience_constraints=with_resilience_constraints,
        model_name=model_name,
    )


def initialize_copperplate_model_from_system(
    system: System,
    n_hours: int = 8760,
    *,
    with_resilience_constraints: bool = False,
    model_name: str = "SDOM_Model",
) -> AbstractModel:
    """Create a copperplate AbstractModel builder from an SDOM system.

    Parameters
    ----------
    system : infrasys.System
        SDOM infrasys system containing compatibility source data.
    n_hours : int, default=8760
        Number of hours captured by the abstract builder and applied when
        ``create_instance()`` instantiates the model.
    with_resilience_constraints : bool, default=False
        Whether to include SDOM resilience constraints in the instantiated
        model.
    model_name : str, default="SDOM_Model"
        Name assigned to the Pyomo model builder and generated instance.

    Returns
    -------
    pyomo.environ.AbstractModel
        AbstractModel builder that instantiates the existing copperplate SDOM
        Pyomo body through the compatibility data path.

    Raises
    ------
    ValueError
        If ``n_hours`` is not positive.
    NotImplementedError
        If the system data is not a single-area copperplate system.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> from sdom.infrasys_integration.pyomo_builder import initialize_copperplate_model_from_system
    >>> system = load_system("Data/no_exchange_run_of_river")
    >>> model = initialize_copperplate_model_from_system(system, n_hours=24)
    >>> instance = model.create_instance()
    >>> instance.name
    'SDOM_Model'
    """
    data = system_to_data_dict(system)
    _validate_copperplate_data(data)
    return _initialize_abstract_model_from_system(
        system,
        n_hours=n_hours,
        with_resilience_constraints=with_resilience_constraints,
        model_name=model_name,
        data=data,
    )


def _initialize_abstract_model_from_system(
    system: System,
    *,
    n_hours: int,
    with_resilience_constraints: bool,
    model_name: str,
    data: dict[str, Any] | None = None,
) -> AbstractModel:
    """Create an AbstractModel-backed SDOM builder from validated System data.

    Parameters
    ----------
    system : infrasys.System
        SDOM System containing typed area, bus, and asset components.
    n_hours : int
        Number of model hours to capture in the builder options.
    with_resilience_constraints : bool
        Whether the generated instance should include resilience constraints.
    model_name : str
        Name assigned to the AbstractModel builder and generated instance.
    data : dict[str, Any], optional
        Pre-resolved SDOM compatibility data dictionary. When omitted, the
        dictionary attached by the infrasys loader is read from ``system``.

    Returns
    -------
    pyomo.environ.AbstractModel
        AbstractModel builder whose ``create_instance()`` method instantiates
        the existing SDOM Pyomo body for copperplate or zonal data.

    Raises
    ------
    ValueError
        If ``n_hours`` is not positive or the System topology is inconsistent
        with its SDOM source data.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> builder = _initialize_abstract_model_from_system(
    ...     load_system("Data/zonal_test"),
    ...     n_hours=24,
    ...     with_resilience_constraints=False,
    ...     model_name="SDOM_Model",
    ... )
    >>> builder.is_constructed()
    False
    """
    _validate_n_hours(n_hours)
    resolved_data = system_to_data_dict(system) if data is None else data
    validate_sdom_system(system)
    _validate_system_data_associations(system, resolved_data)

    model = AbstractModel(name=model_name)
    model._sdom_data = resolved_data
    model._sdom_model_options = {
        "n_hours": n_hours,
        "with_resilience_constraints": with_resilience_constraints,
        "model_name": model_name,
    }
    model.create_instance = MethodType(_create_sdom_instance, model)
    return model


def _create_sdom_instance(model: AbstractModel, *args: Any, **kwargs: Any) -> ConcreteModel:
    """Instantiate an AbstractModel-backed SDOM model.

    Parameters
    ----------
    model : pyomo.environ.AbstractModel
        AbstractModel builder returned by :func:`initialize_model_from_system`
        or :func:`initialize_copperplate_model_from_system`.
    *args : Any
        Unsupported positional arguments. Present only to match Pyomo's
        ``create_instance`` calling convention.
    **kwargs : Any
        Unsupported keyword arguments. Present only to match Pyomo's
        ``create_instance`` calling convention.

    Returns
    -------
    pyomo.environ.ConcreteModel
        Concrete Pyomo model generated by the existing SDOM builder.

    Raises
    ------
    TypeError
        If external data arguments are supplied. This builder is already bound
        to source data from the input infrasys system.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> builder = initialize_copperplate_model_from_system(load_system("Data/no_exchange_run_of_river"), n_hours=24)
    >>> builder.create_instance().is_constructed()
    True
    """
    if args or kwargs:
        raise TypeError("SDOM System AbstractModel builders do not accept external create_instance data.")
    return initialize_model(model._sdom_data, **model._sdom_model_options)


def _validate_system_data_associations(system: System, data: dict[str, Any]) -> None:
    """Validate that System topology matches the SDOM source-data topology.

    Parameters
    ----------
    system : infrasys.System
        SDOM System containing typed topology and asset components.
    data : dict[str, Any]
        SDOM compatibility data dictionary attached to ``system``.

    Returns
    -------
    None
        Returns normally when areas, buses, and interfaces align.

    Raises
    ------
    ValueError
        If source-data areas are missing from the System, an area has no bus,
        or a transmission interface does not match the source line endpoints.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system, system_to_data_dict
    >>> system = load_system("Data/zonal_test")
    >>> _validate_system_data_associations(system, system_to_data_dict(system))
    """
    expected_areas = {str(record["area_id"]) for record in data.get("areas", [])}
    system_areas = {area.name for area in system.get_components(SDOMArea)}
    if expected_areas != system_areas:
        raise ValueError(
            "SDOM System areas do not match source data: "
            f"expected {sorted(expected_areas)}, got {sorted(system_areas)}."
        )

    buses_by_area: dict[str, list[str]] = {area_id: [] for area_id in expected_areas}
    for bus in system.get_components(SDOMBus):
        area_name = bus.area.name
        if area_name in buses_by_area:
            buses_by_area[area_name].append(bus.name)
    missing_bus_areas = [area_id for area_id, buses in buses_by_area.items() if not buses]
    if missing_bus_areas:
        raise ValueError(f"SDOM System areas missing buses: {missing_bus_areas}.")

    for line in data.get("lines") or []:
        line_id = str(line["line_id"])
        interface_name = f"line:{line_id}"
        try:
            interface = system.get_component(SDOMTransmissionInterface, interface_name)
        except Exception as exc:
            raise ValueError(f"SDOM System is missing transmission interface '{interface_name}'.") from exc

        expected_from = str(line["from_area"])
        expected_to = str(line["to_area"])
        actual_from = interface.from_bus.area.name
        actual_to = interface.to_bus.area.name
        if (actual_from, actual_to) != (expected_from, expected_to):
            raise ValueError(
                f"Transmission interface '{interface_name}' connects {actual_from!r}->{actual_to!r}; "
                f"expected {expected_from!r}->{expected_to!r}."
            )


def _validate_copperplate_data(data: dict[str, Any]) -> None:
    """Validate that a data dictionary describes a copperplate system.

    Parameters
    ----------
    data : dict[str, Any]
        SDOM compatibility data dictionary.

    Returns
    -------
    None
        Returns normally for single-area copperplate data.

    Raises
    ------
    NotImplementedError
        If the data requires a zonal or unsupported network build.

    Examples
    --------
    >>> from sdom import load_data
    >>> data = load_data("Data/no_exchange_run_of_river")
    >>> _validate_copperplate_data(data)
    """
    network = get_network_formulation(data)
    areas = data.get("areas", [{"area_id": DEFAULT_AREA_ID}])
    if network != COPPER_PLATE_NETWORK or len(areas) != 1:
        raise NotImplementedError(
            "initialize_copperplate_model_from_system supports only single-area "
            f"{COPPER_PLATE_NETWORK} systems; got Network={network!r}, areas={len(areas)}."
        )


def _validate_n_hours(n_hours: int) -> None:
    """Validate the requested model horizon.

    Parameters
    ----------
    n_hours : int
        Requested number of model hours.

    Returns
    -------
    None
        Returns normally when ``n_hours`` is positive.

    Raises
    ------
    ValueError
        If ``n_hours`` is less than one.

    Examples
    --------
    >>> _validate_n_hours(24)
    >>> _validate_n_hours(0)
    Traceback (most recent call last):
    ...
    ValueError: n_hours must be positive; got 0.
    """
    if n_hours <= 0:
        raise ValueError(f"n_hours must be positive; got {n_hours}.")


__all__ = ["initialize_copperplate_model_from_system", "initialize_model_from_system"]
