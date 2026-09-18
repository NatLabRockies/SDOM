"""Static injection resource models for SDOM infrasys integration."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator
from r2x_core.units import HasUnits, Unit

from .base import SDOMComponent
from .topology import SDOMBus


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
        Capital cost in USD/kW.
    fom : float, optional
        Fixed operations and maintenance cost in USD/kW-year.
    vom : float, optional
        Variable operations and maintenance cost in USD/MWh.
    trans_cap_cost : float, optional
        Transmission interconnection capital cost in USD/kW.
    heat_rate : float, optional
        Heat rate in MMBtu/MWh. Subclasses may make this required.
    fuel_cost : float, optional
        Fuel cost in dollars per MMBtu. Subclasses may make this required.
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
        Unit("$/kW"),
        Field(ge=0, description="Capital cost."),
    ] | None = None
    fom: Annotated[
        float,
        Unit("$/kW/year"),
        Field(ge=0, description="Fixed operations and maintenance cost."),
    ] | None = None
    vom: Annotated[
        float,
        Unit("$/MWh"),
        Field(ge=0, description="Variable operations and maintenance cost."),
    ] | None = None
    trans_cap_cost: Annotated[
        float,
        Unit("$/kW"),
        Field(ge=0, description="Transmission interconnection capital cost."),
    ] | None = None
    heat_rate: Annotated[
        float,
        Unit("MMBtu/MWh"),
        Field(ge=0, description="Heat rate."),
    ] | None = None
    fuel_cost: Annotated[
        float,
        Unit("$/MMBtu"),
        Field(ge=0, description="Fuel cost."),
    ] | None = None


class SDOMThermalGenerator(SDOMGenerator):
    """Thermal generator with fuel and heat-rate data.

    Parameters
    ----------
    heat_rate : float
        Required heat rate in MMBtu/MWh.
    fuel_cost : float
        Required fuel cost in dollars per MMBtu.
    """

    heat_rate: Annotated[
        float,
        Unit("MMBtu/MWh"),
        Field(ge=0, description="Thermal heat rate."),
    ]
    fuel_cost: Annotated[
        float,
        Unit("$/MMBtu"),
        Field(ge=0, description="Fuel cost."),
    ]


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
        Maximum charge/discharge power capacity, in kW.
    max_energy_capacity : float, optional
        Maximum energy capacity, in MWh.
    round_trip_efficiency : float, optional
        Round-trip efficiency fraction between 0 and 1.
    max_cycles : int, optional
        Maximum number of charge/discharge cycles.
    coupled : bool, optional
        Whether input and output power are coupled.
    lifetime : int, optional
        Expected storage lifetime in years.
    cost_ratio : float, optional
        Input/output power-cost allocation ratio.
    """

    bus: Annotated[SDOMBus, Field(description="Bus where the storage resource is connected.")]
    technology: Annotated[str, Field(min_length=1, description="Storage technology label.")]
    max_power_capacity: Annotated[
        float,
        Unit("kW"),
        Field(ge=0, description="Maximum storage power capacity."),
    ] | None = None
    max_energy_capacity: Annotated[
        float,
        Unit("MWh"),
        Field(ge=0, description="Maximum storage energy capacity."),
    ] | None = None
    power_capex: Annotated[
        float,
        Unit("$/kW"),
        Field(ge=0, description="Storage power capital cost."),
    ] | None = None
    energy_capex: Annotated[
        float,
        Unit("$/kWh"),
        Field(ge=0, description="Storage energy capital cost."),
    ] | None = None
    fom: Annotated[
        float,
        Unit("$/kW/year"),
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
    max_cycles: Annotated[
        int,
        Field(ge=0, description="Maximum number of charge/discharge cycles."),
    ] | None = None
    coupled: Annotated[
        bool,
        Field(description="Whether input and output power capacities are coupled."),
    ] | None = None
    lifetime: Annotated[
        int,
        Unit("years"),
        Field(ge=0, description="Expected storage lifetime."),
    ] | None = None
    cost_ratio: Annotated[
        float,
        Field(ge=0, le=1, description="Input/output power-cost allocation ratio."),
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


__all__ = [
    "SDOMGenerator",
    "SDOMHydroGenerator",
    "SDOMLoad",
    "SDOMNuclearGenerator",
    "SDOMOtherRenewableGenerator",
    "SDOMSolarGenerator",
    "SDOMStorage",
    "SDOMThermalGenerator",
    "SDOMWindGenerator",
]
