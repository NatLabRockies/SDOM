"""Typed infrasys component models for SDOM systems."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from infrasys import Component
from pydantic import Field, model_validator
from r2x_core.units import HasUnits, Unit


class SDOMTechnologyType(StrEnum):
    """Technology categories represented by SDOM components."""

    THERMAL = "thermal"
    SOLAR = "solar"
    WIND = "wind"
    HYDRO = "hydro"
    NUCLEAR = "nuclear"
    OTHER_RENEWABLE = "other_renewable"
    STORAGE = "storage"
    LOAD = "load"
    IMPORT = "import"
    EXPORT = "export"
    TRANSMISSION = "transmission"


class SDOMComponent(Component):
    """Base class for SDOM infrasys components.

    Parameters
    ----------
    name : str
        Unique component name managed by :class:`infrasys.Component`.
    category : str, optional
        SDOM component category used for grouping and display.
    ext : dict, optional
        Additional JSON-serializable metadata that does not belong in the
        typed component schema.
    """

    category: Annotated[str | None, Field(description="SDOM component category")] = None
    ext: Annotated[
        dict[str, Any],
        Field(default_factory=dict, description="Additional serializable component metadata."),
    ]


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
        Bus name inherited from :class:`SDOMComponent`.
    area : SDOMArea
        Area that contains this bus.
    """

    area: Annotated[SDOMArea, Field(description="Area containing this bus.")]


class SDOMLoad(HasUnits, SDOMComponent):
    """Electric demand represented at an SDOM bus.

    Parameters
    ----------
    name : str
        Load component name.
    bus : SDOMBus
        Bus where the load is connected.
    peak_active_power : float, optional
        Peak active power for the load, in MW.
    """

    bus: Annotated[SDOMBus, Field(description="Bus where the load is connected.")]
    peak_active_power: Annotated[
        float,
        Unit("MW"),
        Field(ge=0, description="Peak active power for the load."),
    ] | None = None


class SDOMGenerator(HasUnits, SDOMComponent):
    """Base class for SDOM generation technologies.

    Parameters
    ----------
    name : str
        Generator component name.
    bus : SDOMBus
        Bus where the generator is connected.
    technology : str
        SDOM technology label.
    min_active_power : float, optional
        Minimum active power, in MW.
    max_active_power : float, optional
        Maximum active power, in MW.
    capex : float, optional
        Capital cost, in dollars per MW.
    fom : float, optional
        Fixed operations and maintenance cost, in dollars per MW-year.
    vom : float, optional
        Variable operations and maintenance cost, in dollars per MWh.
    """

    bus: Annotated[SDOMBus, Field(description="Bus where the generator is connected.")]
    technology: Annotated[str, Field(min_length=1, description="SDOM technology label.")]
    min_active_power: Annotated[
        float,
        Unit("MW"),
        Field(ge=0, description="Minimum active power."),
    ] | None = None
    max_active_power: Annotated[
        float,
        Unit("MW"),
        Field(ge=0, description="Maximum active power."),
    ] | None = None
    capex: Annotated[
        float,
        Unit("$/MW"),
        Field(ge=0, description="Capital cost."),
    ] | None = None
    fom: Annotated[
        float,
        Unit("$/MW/year"),
        Field(ge=0, description="Fixed operations and maintenance cost."),
    ] | None = None
    vom: Annotated[
        float,
        Unit("$/MWh"),
        Field(ge=0, description="Variable operations and maintenance cost."),
    ] | None = None


class SDOMThermalGenerator(SDOMGenerator):
    """Thermal generator with fuel and heat-rate data.

    Parameters
    ----------
    heat_rate : float, optional
        Heat rate in MMBtu/MWh.
    fuel_cost : float, optional
        Fuel cost in dollars per MMBtu.
    """

    heat_rate: Annotated[
        float,
        Unit("MMBtu/MWh"),
        Field(ge=0, description="Thermal heat rate."),
    ] | None = None
    fuel_cost: Annotated[
        float,
        Unit("$/MMBtu"),
        Field(ge=0, description="Fuel cost."),
    ] | None = None


class SDOMSolarGenerator(SDOMGenerator):
    """Solar photovoltaic generator component."""


class SDOMWindGenerator(SDOMGenerator):
    """Wind generator component."""


class SDOMHydroGenerator(SDOMGenerator):
    """Hydro generator with optional energy budget data.

    Parameters
    ----------
    budget_period : str, optional
        Hydro budget period such as daily or monthly.
    """

    budget_period: Annotated[
        str | None,
        Field(default=None, description="Hydro budget period such as daily or monthly."),
    ]


class SDOMNuclearGenerator(SDOMGenerator):
    """Nuclear generator component."""


class SDOMOtherRenewableGenerator(SDOMGenerator):
    """Other renewable generator component."""


class SDOMStorage(HasUnits, SDOMComponent):
    """Storage technology connected to an SDOM bus.

    Parameters
    ----------
    name : str
        Storage component name.
    bus : SDOMBus
        Bus where the storage resource is connected.
    technology : str
        Storage technology label.
    max_power_capacity : float, optional
        Maximum charge/discharge power capacity, in MW.
    max_energy_capacity : float, optional
        Maximum energy capacity, in MWh.
    round_trip_efficiency : float, optional
        Round-trip efficiency fraction between 0 and 1.
    """

    bus: Annotated[SDOMBus, Field(description="Bus where the storage resource is connected.")]
    technology: Annotated[str, Field(min_length=1, description="Storage technology label.")]
    max_power_capacity: Annotated[
        float,
        Unit("MW"),
        Field(ge=0, description="Maximum storage power capacity."),
    ] | None = None
    max_energy_capacity: Annotated[
        float,
        Unit("MWh"),
        Field(ge=0, description="Maximum storage energy capacity."),
    ] | None = None
    power_capex: Annotated[
        float,
        Unit("$/MW"),
        Field(ge=0, description="Storage power capital cost."),
    ] | None = None
    energy_capex: Annotated[
        float,
        Unit("$/MWh"),
        Field(ge=0, description="Storage energy capital cost."),
    ] | None = None
    fom: Annotated[
        float,
        Unit("$/MW/year"),
        Field(ge=0, description="Fixed operations and maintenance cost."),
    ] | None = None
    vom: Annotated[
        float,
        Unit("$/MWh"),
        Field(ge=0, description="Variable operations and maintenance cost."),
    ] | None = None
    round_trip_efficiency: Annotated[
        float,
        Field(ge=0, le=1, description="Round-trip efficiency fraction."),
    ] | None = None
    min_duration: Annotated[
        float,
        Unit("hours"),
        Field(ge=0, description="Minimum storage duration."),
    ] | None = None
    max_duration: Annotated[
        float,
        Unit("hours"),
        Field(ge=0, description="Maximum storage duration."),
    ] | None = None

    @model_validator(mode="after")
    def check_duration_bounds(self) -> SDOMStorage:
        """Validate storage duration bounds.

        Returns
        -------
        SDOMStorage
            The validated storage component.

        Raises
        ------
        ValueError
            If both duration bounds are set and the minimum exceeds the
            maximum.
        """
        if (
            self.min_duration is not None
            and self.max_duration is not None
            and self.min_duration > self.max_duration
        ):
            raise ValueError("min_duration must be <= max_duration")
        return self


class SDOMImportInterface(HasUnits, SDOMComponent):
    """Import interface connected to an SDOM bus.

    Parameters
    ----------
    bus : SDOMBus
        Bus where imports enter the system.
    max_active_power : float, optional
        Maximum import capacity, in MW.
    """

    bus: Annotated[SDOMBus, Field(description="Bus where imports enter the system.")]
    max_active_power: Annotated[
        float,
        Unit("MW"),
        Field(ge=0, description="Maximum import capacity."),
    ] | None = None


class SDOMExportInterface(HasUnits, SDOMComponent):
    """Export interface connected to an SDOM bus.

    Parameters
    ----------
    bus : SDOMBus
        Bus where exports leave the system.
    max_active_power : float, optional
        Maximum export capacity, in MW.
    """

    bus: Annotated[SDOMBus, Field(description="Bus where exports leave the system.")]
    max_active_power: Annotated[
        float,
        Unit("MW"),
        Field(ge=0, description="Maximum export capacity."),
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
    "SDOMComponent",
    "SDOMExportInterface",
    "SDOMFormulationConfig",
    "SDOMGenerator",
    "SDOMHydroGenerator",
    "SDOMImportInterface",
    "SDOMLoad",
    "SDOMNuclearGenerator",
    "SDOMOtherRenewableGenerator",
    "SDOMScalarParameter",
    "SDOMSolarGenerator",
    "SDOMStorage",
    "SDOMTechnologyType",
    "SDOMThermalGenerator",
    "SDOMTransmissionInterface",
    "SDOMWindGenerator",
]
