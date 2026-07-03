"""Topology and system-configuration data models for SDOM infrasys integration."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field
from r2x_core.units import HasUnits, Unit

from .base import SDOMComponent


class SDOMArea(HasUnits, SDOMComponent):
    """Geographic or market area represented in an SDOM system.

    Parameters
    ----------
    name : str
        Area name inherited from :class:`SDOMComponent`.
    country : str, optional
        Country code or country name for the area.
    max_active_power : float, optional
        Maximum active power associated with the area, in MW.
    timezone : str, optional
        Time zone identifier for time-series interpretation.
    """

    country: Annotated[str | None, Field(description="Country code or name for the area.")] = None
    max_active_power: Annotated[
        float,
        Unit("MW"),
        Field(ge=0, description="Maximum active power for the area."),
    ] | None = None
    timezone: Annotated[str | None, Field(description="Time zone identifier for the area.")] = None


class SDOMBus(SDOMComponent):
    """Electrical connection point for SDOM assets.

    Parameters
    ----------
    name : str
        Unique bus name.
    area : SDOMArea
        Area that contains this bus.
    """

    name: Annotated[str, Field(min_length=1, description="Unique bus name.")]
    area: Annotated[SDOMArea, Field(description="Area containing this bus.")]


class SDOMImportInterface(HasUnits, SDOMComponent):
    """Import interface connected to an SDOM bus.

    Parameters
    ----------
    bus : SDOMBus
        Bus where imports enter the system.
    max_active_power : float, optional
        Maximum import capacity, in MW.
    price : float, optional
        Import price in USD/MWh.
    """

    bus: Annotated[SDOMBus, Field(description="Bus where imports enter the system.")]
    max_active_power: Annotated[
        float,
        Unit("MW"),
        Field(ge=0, description="Maximum import capacity."),
    ] | None = None
    price: Annotated[
        float,
        Unit("$/MWh"),
        Field(ge=0, description="Import price."),
    ] | None = None


class SDOMExportInterface(HasUnits, SDOMComponent):
    """Export interface connected to an SDOM bus.

    Parameters
    ----------
    bus : SDOMBus
        Bus where exports leave the system.
    max_active_power : float, optional
        Maximum export capacity, in MW.
    price : float, optional
        Export price in USD/MWh.
    """

    bus: Annotated[SDOMBus, Field(description="Bus where exports leave the system.")]
    max_active_power: Annotated[
        float,
        Unit("MW"),
        Field(ge=0, description="Maximum export capacity."),
    ] | None = None
    price: Annotated[
        float,
        Unit("$/MWh"),
        Field(ge=0, description="Export price."),
    ] | None = None


class SDOMTransmissionInterface(HasUnits, SDOMComponent):
    """Transmission interface between two SDOM buses.

    Parameters
    ----------
    from_bus : SDOMBus
        Origin bus for positive flow.
    to_bus : SDOMBus
        Destination bus for positive flow.
    forward_capacity : float, optional
        Capacity from origin to destination, in MW.
    reverse_capacity : float, optional
        Capacity from destination to origin, in MW.
    """

    from_bus: Annotated[SDOMBus, Field(description="Origin bus for positive flow.")]
    to_bus: Annotated[SDOMBus, Field(description="Destination bus for positive flow.")]
    forward_capacity: Annotated[
        float,
        Unit("MW"),
        Field(ge=0, description="Forward transfer capacity."),
    ] | None = None
    reverse_capacity: Annotated[
        float,
        Unit("MW"),
        Field(ge=0, description="Reverse transfer capacity."),
    ] | None = None


class SDOMScalarParameter(SDOMComponent):
    """Scalar parameter from an SDOM input dataset.

    Parameters
    ----------
    parameter_name : str
        Original scalar parameter name.
    value : float
        Scalar parameter value.
    unit : str, optional
        Display unit for the scalar value, when known.
    """

    parameter_name: Annotated[str, Field(min_length=1, description="Original scalar parameter name.")]
    value: Annotated[float, Field(description="Scalar parameter value.")]
    unit: Annotated[str | None, Field(default=None, description="Display unit for the value.")]


class SDOMFormulationConfig(SDOMComponent):
    """Formulation selection for an SDOM model component.

    Parameters
    ----------
    component : str
        SDOM formulation component name.
    formulation : str
        Selected formulation for the component.
    description : str, optional
        Optional human-readable formulation description.
    """

    component: Annotated[str, Field(min_length=1, description="SDOM formulation component name.")]
    formulation: Annotated[str, Field(min_length=1, description="Selected formulation name.")]
    description: Annotated[str | None, Field(default=None, description="Formulation description.")]


__all__ = [
    "SDOMArea",
    "SDOMBus",
    "SDOMExportInterface",
    "SDOMFormulationConfig",
    "SDOMImportInterface",
    "SDOMScalarParameter",
    "SDOMTransmissionInterface",
]
