"""Create infrasys systems from SDOM input data."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd
from infrasys import System

from sdom import load_data as _load_data

from ..models import (
    SDOMArea,
    SDOMBus,
    SDOMExportInterface,
    SDOMFormulationConfig,
    SDOMHydroGenerator,
    SDOMImportInterface,
    SDOMLoad,
    SDOMNuclearGenerator,
    SDOMOtherRenewableGenerator,
    SDOMScalarParameter,
    SDOMSolarGenerator,
    SDOMStorage,
    SDOMTechnologyType,
    SDOMThermalGenerator,
    SDOMTransmissionInterface,
    SDOMWindGenerator,
)
from .utils import (
    _attach_bus_geographic_info,
    _attach_column_series,
    _attach_first_numeric_series,
    _attach_geographic_info,
    _first_matching_column,
    _geographic_info_by_area,
    _has_column,
    _iter_area_frames,
    _mapping_get,
    _optional_float,
    _optional_str,
    _peak_from_frame,
    _required_nonnegative_float,
    _row_ext,
    _series_mean,
    _series_peak,
    _table_bool,
    _table_float,
    _table_int,
)

_SOURCE_DATA_ATTR = "_sdom_source_data_dict"


def drop_system_source_data(system: System) -> None:
    """Remove compatibility source data retained on an SDOM System.

    Parameters
    ----------
    system : infrasys.System
        System previously created by :func:`load_system` or
        :func:`load_system_from_data`.

    Returns
    -------
    None
        The system is mutated in place. Calling the function on a system with
        no retained source data is a no-op.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system, system_to_data_dict
    >>> system = load_system("Data/no_exchange_run_of_river")
    >>> drop_system_source_data(system)
    >>> system_to_data_dict(system)
    Traceback (most recent call last):
    ...
    ValueError: system does not include SDOM source data; use load_system() or load_system_from_data().
    """
    if hasattr(system, _SOURCE_DATA_ATTR):
        delattr(system, _SOURCE_DATA_ATTR)


def load_system(input_data_dir: str | Path, *, name: str = "SDOM") -> System:
    """Load SDOM CSV inputs into an infrasys system.

    Parameters
    ----------
    input_data_dir : str or pathlib.Path
        Directory containing SDOM CSV input files accepted by
        :func:`sdom.load_data`.
    name : str, default="SDOM"
        Name assigned to the returned infrasys system.

    Returns
    -------
    infrasys.System
        System containing typed SDOM components and attached time series.

    Raises
    ------
    FileNotFoundError
        If required SDOM CSV files are missing.
    ValueError
        If SDOM CSV validation or component construction fails.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> system = load_system("Data/no_exchange_run_of_river", name="example")
    >>> system.name
    'example'
    """
    return load_system_from_data(_load_data(str(input_data_dir)), name=name)


def load_system_from_data(data: dict[str, Any], *, name: str = "SDOM") -> System:
    """Convert an SDOM data dictionary into an infrasys system.

    Parameters
    ----------
    data : dict[str, Any]
        SDOM data dictionary returned by :func:`sdom.load_data`.
    name : str, default="SDOM"
        Name assigned to the returned infrasys system.

    Returns
    -------
    infrasys.System
        System containing typed SDOM components, with the original data
        dictionary retained by reference for compatibility conversion.

    Raises
    ------
    ValueError
        If required area information is missing or component values fail
        validation.

    Examples
    --------
    >>> from sdom import load_data
    >>> from sdom.infrasys_integration.make_system import load_system_from_data
    >>> data = load_data("Data/no_exchange_run_of_river")
    >>> system = load_system_from_data(data, name="example")
    >>> bool(list(system.get_components(SDOMArea)))
    True
    """
    system = System(name=name)
    _, buses = _add_areas_and_buses(system, data)
    _add_loads(system, data, buses)
    _add_vre_generators(system, data, buses, technology="solar")
    _add_vre_generators(system, data, buses, technology="wind")
    _add_thermal_generators(system, data, buses)
    _add_profile_generators(system, data, buses)
    _add_storage(system, data, buses)
    _add_trade_interfaces(system, data, buses)
    _add_transmission_interfaces(system, data, buses)
    _add_scalars(system, data)
    _add_formulations(system, data)
    setattr(system, _SOURCE_DATA_ATTR, data)
    return system


def system_to_data_dict(system: System) -> dict[str, Any]:
    """Return the SDOM data dictionary backing a loaded system.

    Parameters
    ----------
    system : infrasys.System
        System produced by :func:`load_system` or
        :func:`load_system_from_data`.

    Returns
    -------
    dict[str, Any]
        Shallow copy of the original SDOM data dictionary. DataFrame values are
        intentionally shared with the source dictionary to avoid unnecessary
        memory growth during the compatibility phase.

    Raises
    ------
    ValueError
        If ``system`` was not produced by this compatibility loader.

    Examples
    --------
    >>> from sdom import load_data
    >>> from sdom.infrasys_integration.make_system import load_system_from_data, system_to_data_dict
    >>> data = load_data("Data/no_exchange_run_of_river")
    >>> restored = system_to_data_dict(load_system_from_data(data))
    >>> restored["load_data"] is data["load_data"]
    True
    """
    data = getattr(system, _SOURCE_DATA_ATTR, None)
    if data is None:
        raise ValueError("system does not include SDOM source data; use load_system() or load_system_from_data().")
    return dict(data)


def _add_areas_and_buses(system: System, data: Mapping[str, Any]) -> tuple[dict[str, SDOMArea], dict[str, SDOMBus]]:
    """Add SDOM areas and one default bus per area.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    data : mapping of str to Any
        SDOM data dictionary containing an ``areas`` list.

    Returns
    -------
    tuple[dict[str, SDOMArea], dict[str, SDOMBus]]
        Area and bus lookups keyed by SDOM ``area_id``.

    Raises
    ------
    ValueError
        If the data dictionary has no area records.

    Examples
    --------
    >>> system = System(name="example")
    >>> areas, buses = _add_areas_and_buses(system, {"areas": [{"area_id": "A", "description": "Area A"}]})
    >>> buses["A"].area is areas["A"]
    True
    """
    area_records = data.get("areas") or []
    if not area_records:
        raise ValueError("SDOM data dictionary must include at least one area record.")

    geographic_info_by_area = _geographic_info_by_area(data)
    areas: dict[str, SDOMArea] = {}
    buses: dict[str, SDOMBus] = {}
    for record in area_records:
        area_id = str(record["area_id"])
        area = SDOMArea(
            name=area_id,
            country=_optional_str(record.get("country")),
            max_active_power=_peak_from_frame(_mapping_get(data.get("per_area_demand"), area_id)),
            timezone=_optional_str(record.get("timezone")),
            ext={"description": _optional_str(record.get("description"))},
        )
        bus = SDOMBus(name=area_id, area=area, category="bus")
        system.add_component(area)
        system.add_component(bus)
        if area_id in geographic_info_by_area:
            system.add_supplemental_attribute(bus, geographic_info_by_area[area_id])
        areas[area_id] = area
        buses[area_id] = bus
    return areas, buses


def _add_loads(system: System, data: Mapping[str, Any], buses: Mapping[str, SDOMBus]) -> None:
    """Add area load components and demand time series.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    data : mapping of str to Any
        SDOM data dictionary containing ``per_area_demand``.
    buses : mapping of str to SDOMBus
        Bus lookup keyed by area id.

    Returns
    -------
    None
        Components are added to ``system`` in place.

    Examples
    --------
    >>> system = System(name="example")
    >>> _, buses = _add_areas_and_buses(system, {"areas": [{"area_id": "A"}]})
    >>> _add_loads(system, {"per_area_demand": {"A": pd.DataFrame({"Hour": [1, 2], "Load": [3.0, 4.0]})}}, buses)
    >>> system.get_component(SDOMLoad, "load:A").peak_active_power
    4.0
    """
    for area_id, frame in _iter_area_frames(data.get("per_area_demand")):
        load = SDOMLoad(
            name=f"load:{area_id}",
            bus=buses[area_id],
            category=SDOMTechnologyType.LOAD.value,
            peak_active_power=_peak_from_frame(frame),
        )
        system.add_component(load)
        _attach_first_numeric_series(system, load, frame, name="active_power", source_key="per_area_demand")


def _add_vre_generators(system: System, data: Mapping[str, Any], buses: Mapping[str, SDOMBus], *, technology: str) -> None:
    """Add solar or wind generator components and capacity-factor series.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    data : mapping of str to Any
        SDOM data dictionary containing VRE plant and profile views.
    buses : mapping of str to SDOMBus
        Bus lookup keyed by area id.
    technology : {"solar", "wind"}
        VRE technology to convert.

    Returns
    -------
    None
        Components are added to ``system`` in place.

    Raises
    ------
    ValueError
        If ``technology`` is not ``"solar"`` or ``"wind"``.

    Examples
    --------
    >>> system = System(name="example")
    >>> _, buses = _add_areas_and_buses(system, {"areas": [{"area_id": "A"}]})
    >>> data = {"per_area_pv_plants": {"A": pd.DataFrame({"sc_gid": ["g1"], "capacity": [1.0]})}}
    >>> _add_vre_generators(system, data, buses, technology="solar")
    >>> system.get_component(SDOMSolarGenerator, "solar:g1").technology
    'Solar PV'
    """
    if technology == "solar":
        plant_key = "per_area_pv_plants"
        cf_key = "per_area_capacity_factors_pv"
        component_type = SDOMSolarGenerator
        name_prefix = "solar"
        label = "Solar PV"
        category = SDOMTechnologyType.SOLAR.value
    elif technology == "wind":
        plant_key = "per_area_wind_plants"
        cf_key = "per_area_capacity_factors_wind"
        component_type = SDOMWindGenerator
        name_prefix = "wind"
        label = "Wind"
        category = SDOMTechnologyType.WIND.value
    else:
        raise ValueError("technology must be 'solar' or 'wind'.")

    profiles = data.get(cf_key) or {}
    for area_id, frame in _iter_area_frames(data.get(plant_key)):
        profile_frame = _mapping_get(profiles, area_id)
        for row in frame.itertuples(index=False):
            row_data = row._asdict()
            plant_id = str(row_data["sc_gid"])
            generator = component_type(
                name=f"{name_prefix}:{plant_id}",
                bus=buses[area_id],
                category=category,
                technology=label,
                max_active_power=_optional_float(row_data.get("capacity")),
                capex=_optional_float(row_data.get("CAPEX_M")),
                fom=_optional_float(row_data.get("FOM_M")),
                trans_cap_cost=_optional_float(row_data.get("trans_cap_cost")),
                ext=_row_ext(row_data, exclude={"area_id", "sc_gid", "capacity", "CAPEX_M", "FOM_M", "trans_cap_cost"}),
            )
            system.add_component(generator)
            if not _attach_geographic_info(system, generator, row_data, source=plant_key):
                _attach_bus_geographic_info(system, generator, buses[area_id])
            _attach_column_series(
                system,
                generator,
                profile_frame,
                column=plant_id,
                name="capacity_factor",
                source_key=cf_key,
            )


def _add_thermal_generators(system: System, data: Mapping[str, Any], buses: Mapping[str, SDOMBus]) -> None:
    """Add thermal generator components from balancing-unit data.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    data : mapping of str to Any
        SDOM data dictionary containing ``per_area_balancing_units``.
    buses : mapping of str to SDOMBus
        Bus lookup keyed by area id.

    Returns
    -------
    None
        Components are added to ``system`` in place.

    Examples
    --------
    >>> system = System(name="example")
    >>> _, buses = _add_areas_and_buses(system, {"areas": [{"area_id": "A"}]})
    >>> frame = pd.DataFrame({"Plant_id": ["p1"], "MinCapacity": [0], "MaxCapacity": [1], "HeatRate": [7], "FuelCost": [2]})
    >>> _add_thermal_generators(system, {"per_area_balancing_units": {"A": frame}}, buses)
    >>> system.get_component(SDOMThermalGenerator, "thermal:p1").fuel_cost
    2.0
    """
    for area_id, frame in _iter_area_frames(data.get("per_area_balancing_units")):
        for row in frame.itertuples(index=False):
            row_data = row._asdict()
            plant_id = str(row_data["Plant_id"])
            generator = SDOMThermalGenerator(
                name=f"thermal:{plant_id}",
                bus=buses[area_id],
                category=SDOMTechnologyType.THERMAL.value,
                technology="Thermal",
                min_active_power=_optional_float(row_data.get("MinCapacity")),
                max_active_power=_optional_float(row_data.get("MaxCapacity")),
                capex=_optional_float(row_data.get("Capex")),
                fom=_optional_float(row_data.get("FOM")),
                vom=_optional_float(row_data.get("VOM")),
                heat_rate=_required_nonnegative_float(
                    row_data,
                    "HeatRate",
                    source="per_area_balancing_units",
                    technology="thermal",
                    component_name=plant_id,
                    area_id=area_id,
                ),
                fuel_cost=_required_nonnegative_float(
                    row_data,
                    "FuelCost",
                    source="per_area_balancing_units",
                    technology="thermal",
                    component_name=plant_id,
                    area_id=area_id,
                ),
                ext={
                    **_row_ext(
                        row_data,
                        exclude={
                            "area_id",
                            "Plant_id",
                            "MinCapacity",
                            "MaxCapacity",
                            "Capex",
                            "FOM",
                            "VOM",
                            "HeatRate",
                            "FuelCost",
                        },
                    ),
                    "asset_status": "candidate",
                    "location_status": "allowed_area",
                    "allowed_area": area_id,
                },
            )
            system.add_component(generator)
            _attach_bus_geographic_info(system, generator, buses[area_id])


def _add_profile_generators(system: System, data: Mapping[str, Any], buses: Mapping[str, SDOMBus]) -> None:
    """Add hydro, nuclear, and other-renewable profile generators.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    data : mapping of str to Any
        SDOM data dictionary containing per-area fixed-generation profiles.
    buses : mapping of str to SDOMBus
        Bus lookup keyed by area id.

    Returns
    -------
    None
        Components and time series are added to ``system`` in place.

    Examples
    --------
    >>> system = System(name="example")
    >>> _, buses = _add_areas_and_buses(system, {"areas": [{"area_id": "A"}]})
    >>> data = {"per_area_nuclear": {"A": pd.DataFrame({"Hour": [1, 2], "Nuclear": [5.0, 6.0]})}}
    >>> _add_profile_generators(system, data, buses)
    >>> system.get_component(SDOMNuclearGenerator, "nuclear:A").max_active_power
    6.0
    """
    hydro_budget_period = _hydro_budget_period(data)
    specs = [
        ("per_area_hydro", SDOMHydroGenerator, "hydro", "Hydro", SDOMTechnologyType.HYDRO.value),
        ("per_area_nuclear", SDOMNuclearGenerator, "nuclear", "Nuclear", SDOMTechnologyType.NUCLEAR.value),
        (
            "per_area_other_renewables",
            SDOMOtherRenewableGenerator,
            "other_renewable",
            "OtherRenewables",
            SDOMTechnologyType.OTHER_RENEWABLE.value,
        ),
    ]
    for data_key, component_type, name_prefix, label, category in specs:
        for area_id, frame in _iter_area_frames(data.get(data_key)):
            generator_kwargs: dict[str, Any] = {
                "name": f"{name_prefix}:{area_id}",
                "bus": buses[area_id],
                "category": category,
                "technology": label,
                "max_active_power": _peak_from_frame(frame),
            }
            if component_type is SDOMHydroGenerator:
                generator_kwargs["budget_period"] = hydro_budget_period
            generator = component_type(**generator_kwargs)
            system.add_component(generator)
            _attach_bus_geographic_info(system, generator, buses[area_id])
            _attach_first_numeric_series(system, generator, frame, name="active_power", source_key=data_key)


def _hydro_budget_period(data: Mapping[str, Any]) -> str | None:
    """Return the typed budget period selected by the hydro formulation.

    Parameters
    ----------
    data : mapping of str to Any
        SDOM data dictionary containing the optional formulations table.

    Returns
    -------
    str or None
        ``"daily"`` or ``"monthly"`` for budget formulations, otherwise
        ``None``.
    """
    formulations = data.get("formulations")
    if not isinstance(formulations, pd.DataFrame):
        return None
    required_columns = {"Component", "Formulation"}
    if not required_columns.issubset(formulations.columns):
        return None

    hydro_formulations = formulations.loc[
        formulations["Component"].astype(str).str.casefold() == "hydro",
        "Formulation",
    ]
    if hydro_formulations.empty:
        return None
    return {
        "DailyBudgetFormulation": "daily",
        "MonthlyBudgetFormulation": "monthly",
    }.get(str(hydro_formulations.iloc[0]))


def _add_storage(system: System, data: Mapping[str, Any], buses: Mapping[str, SDOMBus]) -> None:
    """Add storage components from per-area storage tables.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    data : mapping of str to Any
        SDOM data dictionary containing ``per_area_storage``.
    buses : mapping of str to SDOMBus
        Bus lookup keyed by area id.

    Returns
    -------
    None
        Components are added to ``system`` in place.

    Examples
    --------
    >>> system = System(name="example")
    >>> _, buses = _add_areas_and_buses(system, {"areas": [{"area_id": "A"}]})
    >>> frame = pd.DataFrame({"Battery": [1, 2, 0.9]}, index=["P_Capex", "E_Capex", "Eff"])
    >>> _add_storage(system, {"per_area_storage": {"A": frame}}, buses)
    >>> system.get_component(SDOMStorage, "storage:A:Battery").round_trip_efficiency
    0.9
    """
    for area_id, frame in _iter_area_frames(data.get("per_area_storage")):
        for technology in frame.columns.astype(str):
            storage = SDOMStorage(
                name=f"storage:{area_id}:{technology}",
                bus=buses[area_id],
                category=SDOMTechnologyType.STORAGE.value,
                technology=technology,
                max_power_capacity=_table_float(frame, "Max_P", technology),
                max_energy_capacity=None,
                power_capex=_table_float(frame, "P_Capex", technology),
                energy_capex=_table_float(frame, "E_Capex", technology),
                fom=_table_float(frame, "FOM", technology),
                vom=_table_float(frame, "VOM", technology),
                round_trip_efficiency=_table_float(frame, "Eff", technology),
                min_duration=_table_float(frame, "Min_Duration", technology),
                max_duration=_table_float(frame, "Max_Duration", technology),
                max_cycles=_table_int(frame, "MaxCycles", technology),
                coupled=_table_bool(frame, "Coupled", technology),
                lifetime=_table_int(frame, "Lifetime", technology),
                cost_ratio=_table_float(frame, "CostRatio", technology),
                ext={
                    "asset_status": "candidate",
                    "location_status": "allowed_area",
                    "allowed_area": area_id,
                },
            )
            system.add_component(storage)


def _add_trade_interfaces(system: System, data: Mapping[str, Any], buses: Mapping[str, SDOMBus]) -> None:
    """Add import and export interfaces with capacity and price series.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    data : mapping of str to Any
        SDOM data dictionary containing per-area import/export views.
    buses : mapping of str to SDOMBus
        Bus lookup keyed by area id.

    Returns
    -------
    None
        Components and time series are added to ``system`` in place.

    Examples
    --------
    >>> system = System(name="example")
    >>> _, buses = _add_areas_and_buses(system, {"areas": [{"area_id": "A"}]})
    >>> frame = pd.DataFrame({"Hour": [1, 2], "Imports": [3.0, 4.0], "Imports_price": [5.0, 6.0]})
    >>> _add_trade_interfaces(system, {"per_area_imports": {"A": frame}}, buses)
    >>> system.get_component(SDOMImportInterface, "import:A").max_active_power
    4.0
    """
    specs = [
        ("per_area_imports", SDOMImportInterface, "import", SDOMTechnologyType.IMPORT.value),
        ("per_area_exports", SDOMExportInterface, "export", SDOMTechnologyType.EXPORT.value),
    ]
    for data_key, component_type, name_prefix, category in specs:
        for area_id, frame in _iter_area_frames(data.get(data_key)):
            cap_col = _first_matching_column(frame, suffixes=("cap", "imports", "exports"), exclude_suffixes=("price",))
            price_col = _first_matching_column(frame, suffixes=("price",), exclude_suffixes=())
            component = component_type(
                name=f"{name_prefix}:{area_id}",
                bus=buses[area_id],
                category=category,
                max_active_power=_series_peak(frame[cap_col]) if cap_col else None,
                price=_series_mean(frame[price_col]) if price_col else None,
            )
            system.add_component(component)
            if cap_col:
                _attach_column_series(system, component, frame, column=cap_col, name="max_active_power", source_key=data_key)
            if price_col:
                _attach_column_series(system, component, frame, column=price_col, name="price", source_key=data_key)


def _add_transmission_interfaces(system: System, data: Mapping[str, Any], buses: Mapping[str, SDOMBus]) -> None:
    """Add zonal transmission interfaces and line-capacity series.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    data : mapping of str to Any
        SDOM data dictionary containing ``lines`` and line-capacity tables.
    buses : mapping of str to SDOMBus
        Bus lookup keyed by area id.

    Returns
    -------
    None
        Components and time series are added to ``system`` in place.

    Examples
    --------
    >>> system = System(name="example")
    >>> _, buses = _add_areas_and_buses(system, {"areas": [{"area_id": "A"}, {"area_id": "B"}]})
    >>> data = {"lines": [{"line_id": "L", "from_area": "A", "to_area": "B"}]}
    >>> _add_transmission_interfaces(system, data, buses)
    >>> system.get_component(SDOMTransmissionInterface, "line:L").to_bus.name
    'B'
    """
    cap_ft = data.get("line_cap_ft")
    cap_tf = data.get("line_cap_tf")
    for line in data.get("lines") or []:
        line_id = str(line["line_id"])
        component = SDOMTransmissionInterface(
            name=f"line:{line_id}",
            from_bus=buses[str(line["from_area"])],
            to_bus=buses[str(line["to_area"])],
            category=SDOMTechnologyType.TRANSMISSION.value,
            forward_capacity=_series_peak(cap_ft[line_id]) if _has_column(cap_ft, line_id) else None,
            reverse_capacity=_series_peak(cap_tf[line_id]) if _has_column(cap_tf, line_id) else None,
        )
        system.add_component(component)
        _attach_column_series(system, component, cap_ft, column=line_id, name="forward_capacity", source_key="line_cap_ft")
        _attach_column_series(system, component, cap_tf, column=line_id, name="reverse_capacity", source_key="line_cap_tf")


def _add_scalars(system: System, data: Mapping[str, Any]) -> None:
    """Add scalar parameter components.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    data : mapping of str to Any
        SDOM data dictionary containing the ``scalars`` DataFrame.

    Returns
    -------
    None
        Components are added to ``system`` in place.

    Examples
    --------
    >>> system = System(name="example")
    >>> _add_scalars(system, {"scalars": pd.DataFrame({"Value": [1.0]}, index=["alpha"])})
    >>> system.get_component(SDOMScalarParameter, "scalar:alpha").value
    1.0
    """
    scalars = data.get("scalars")
    if not isinstance(scalars, pd.DataFrame) or scalars.empty:
        return
    value_col = "Value" if "Value" in scalars.columns else scalars.columns[0]
    for parameter, value in scalars[value_col].items():
        scalar_value = _optional_float(value)
        if scalar_value is None:
            continue
        system.add_component(
            SDOMScalarParameter(
                name=f"scalar:{parameter}",
                category="scalar",
                parameter_name=str(parameter),
                value=scalar_value,
            )
        )


def _add_formulations(system: System, data: Mapping[str, Any]) -> None:
    """Add formulation selection components.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    data : mapping of str to Any
        SDOM data dictionary containing the ``formulations`` DataFrame.

    Returns
    -------
    None
        Components are added to ``system`` in place.

    Examples
    --------
    >>> system = System(name="example")
    >>> frame = pd.DataFrame({"Component": ["Network"], "Formulation": ["CopperPlateNetwork"]})
    >>> _add_formulations(system, {"formulations": frame})
    >>> system.get_component(SDOMFormulationConfig, "formulation:Network").formulation
    'CopperPlateNetwork'
    """
    formulations = data.get("formulations")
    if not isinstance(formulations, pd.DataFrame) or formulations.empty:
        return
    for row in formulations.itertuples(index=False):
        row_data = row._asdict()
        component = str(row_data["Component"])
        system.add_component(
            SDOMFormulationConfig(
                name=f"formulation:{component}",
                category="formulation",
                component=component,
                formulation=str(row_data["Formulation"]),
                description=_optional_str(row_data.get("Description")),
            )
        )
