"""CSV-to-System loader entry points for SDOM infrasys integration."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from infrasys import SingleTimeSeries, System

from sdom import load_data as _load_data

from .attributes import GeographicInfo, GeoLocation
from .components import (
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

_SOURCE_DATA_ATTR = "_sdom_source_data_dict"
_DEFAULT_INITIAL_TIMESTAMP = datetime(2000, 1, 1)
_DEFAULT_RESOLUTION = timedelta(hours=1)


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
    >>> from sdom.infrasys_integration.csv_loader import load_system
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
    >>> from sdom.infrasys_integration.csv_loader import load_system_from_data
    >>> data = load_data("Data/no_exchange_run_of_river")
    >>> system = load_system_from_data(data, name="example")
    >>> bool(list(system.get_components(SDOMArea)))
    True
    """
    system = System(name=name)
    areas, buses = _add_areas_and_buses(system, data)
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
    # Keep local variables referenced until all composed components have been
    # attached; this makes the ownership graph explicit without copying data.
    _ = areas
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
    >>> from sdom.infrasys_integration.csv_loader import load_system_from_data, system_to_data_dict
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
                heat_rate=_optional_float(row_data.get("HeatRate")) or 0.0,
                fuel_cost=_optional_float(row_data.get("FuelCost")) or 0.0,
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
            generator = component_type(
                name=f"{name_prefix}:{area_id}",
                bus=buses[area_id],
                category=category,
                technology=label,
                max_active_power=_peak_from_frame(frame),
            )
            system.add_component(generator)
            _attach_bus_geographic_info(system, generator, buses[area_id])
            _attach_first_numeric_series(system, generator, frame, name="active_power", source_key=data_key)


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


def _attach_first_numeric_series(system: System, owner: Any, frame: pd.DataFrame | None, *, name: str, source_key: str) -> None:
    """Attach the first numeric non-time column in a DataFrame.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : Any
        Component that owns the time series.
    frame : pandas.DataFrame or None
        Candidate time-series table.
    name : str
        Time-series name stored in infrasys.
    source_key : str
        SDOM data dictionary key used as metadata.

    Returns
    -------
    None
        Time series are attached in place when a usable column exists.

    Examples
    --------
    >>> system = System(name="example")
    >>> area = SDOMArea(name="A")
    >>> system.add_component(area)
    >>> _attach_first_numeric_series(system, area, pd.DataFrame({"Hour": [1, 2], "x": [1.0, 2.0]}), name="x", source_key="demo")
    >>> len(list(system.list_time_series_keys(area)))
    1
    """
    if not isinstance(frame, pd.DataFrame):
        return
    column = _first_value_column(frame)
    if column is not None:
        _attach_column_series(system, owner, frame, column=column, name=name, source_key=source_key)


def _attach_column_series(system: System, owner: Any, frame: pd.DataFrame | None, *, column: str, name: str, source_key: str) -> None:
    """Attach one DataFrame column as a single time series.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : Any
        Component that owns the time series.
    frame : pandas.DataFrame or None
        DataFrame containing ``column``.
    column : str
        Column to attach.
    name : str
        Time-series name stored in infrasys.
    source_key : str
        SDOM data dictionary key used as metadata.

    Returns
    -------
    None
        Time series are attached in place when at least two values are present.

    Examples
    --------
    >>> system = System(name="example")
    >>> area = SDOMArea(name="A")
    >>> system.add_component(area)
    >>> frame = pd.DataFrame({"Hour": [1, 2], "x": [1.0, 2.0]})
    >>> _attach_column_series(system, area, frame, column="x", name="x", source_key="demo")
    >>> system.has_time_series(area, name="x")
    True
    """
    if not _has_column(frame, column):
        return
    numeric_values = pd.to_numeric(frame[column], errors="coerce")
    if numeric_values.isna().any():
        missing_rows = numeric_values.index[numeric_values.isna()].tolist()
        raise ValueError(
            f"Time series '{name}' from source '{source_key}' column '{column}' contains "
            f"missing or non-numeric values at rows {missing_rows}."
        )
    values = numeric_values.to_numpy(dtype=float, copy=False)
    if len(values) < 2:
        return
    ts = SingleTimeSeries.from_array(
        values,
        name=name,
        initial_timestamp=_DEFAULT_INITIAL_TIMESTAMP,
        resolution=_DEFAULT_RESOLUTION,
    )
    system.add_time_series(ts, owner, source_key=source_key, source_column=str(column))


def _iter_area_frames(value: Any) -> list[tuple[str, pd.DataFrame]]:
    """Return non-empty area DataFrames from a per-area mapping.

    Parameters
    ----------
    value : Any
        Candidate mapping of area id to DataFrame.

    Returns
    -------
    list[tuple[str, pandas.DataFrame]]
        Non-empty DataFrame entries sorted by area id for deterministic output.

    Examples
    --------
    >>> _iter_area_frames({"B": pd.DataFrame(), "A": pd.DataFrame({"x": [1]})})[0][0]
    'A'
    """
    if not isinstance(value, Mapping):
        return []
    return [
        (str(area), frame)
        for area, frame in sorted(value.items(), key=lambda item: str(item[0]))
        if isinstance(frame, pd.DataFrame) and not frame.empty
    ]


def _mapping_get(value: Any, key: str) -> Any:
    """Return a mapping value when ``value`` is a mapping.

    Parameters
    ----------
    value : Any
        Candidate mapping.
    key : str
        Key to retrieve.

    Returns
    -------
    Any
        Mapped value or ``None``.

    Examples
    --------
    >>> _mapping_get({"a": 1}, "a")
    1
    """
    if isinstance(value, Mapping):
        return value.get(key)
    return None


def _first_value_column(frame: pd.DataFrame) -> str | None:
    """Return the first non-time value column in a DataFrame.

    Parameters
    ----------
    frame : pandas.DataFrame
        Candidate time-series table.

    Returns
    -------
    str or None
        First value column, or ``None`` when no candidate exists.

    Examples
    --------
    >>> _first_value_column(pd.DataFrame({"Hour": [1], "Load": [2]}))
    'Load'
    """
    for column in frame.columns:
        lower = str(column).lower().lstrip("*")
        if lower not in {"hour", "timestamp", "time"}:
            return str(column)
    return None


def _first_matching_column(frame: pd.DataFrame, *, suffixes: tuple[str, ...], exclude_suffixes: tuple[str, ...]) -> str | None:
    """Return the first value column matching suffix hints.

    Parameters
    ----------
    frame : pandas.DataFrame
        Candidate time-series table.
    suffixes : tuple[str, ...]
        Lowercase substrings that should appear in the column name.
    exclude_suffixes : tuple[str, ...]
        Lowercase substrings that disqualify the column name.

    Returns
    -------
    str or None
        Matching column name, or ``None``.

    Examples
    --------
    >>> frame = pd.DataFrame({"Hour": [1], "Imports": [2], "Imports_price": [3]})
    >>> _first_matching_column(frame, suffixes=("price",), exclude_suffixes=())
    'Imports_price'
    """
    for column in frame.columns:
        lower = str(column).lower().lstrip("*")
        if lower in {"hour", "timestamp", "time"}:
            continue
        if any(excluded in lower for excluded in exclude_suffixes):
            continue
        if any(suffix in lower for suffix in suffixes):
            return str(column)
    return None


def _has_column(frame: Any, column: str) -> bool:
    """Return whether a DataFrame has a column.

    Parameters
    ----------
    frame : Any
        Candidate DataFrame.
    column : str
        Column name to check.

    Returns
    -------
    bool
        ``True`` when ``frame`` is a DataFrame and contains ``column``.

    Examples
    --------
    >>> _has_column(pd.DataFrame({"x": [1]}), "x")
    True
    """
    return isinstance(frame, pd.DataFrame) and column in frame.columns


def _peak_from_frame(frame: pd.DataFrame | None) -> float | None:
    """Return the peak value from the first non-time numeric column.

    Parameters
    ----------
    frame : pandas.DataFrame or None
        Candidate time-series table.

    Returns
    -------
    float or None
        Maximum numeric value, or ``None`` when unavailable.

    Examples
    --------
    >>> _peak_from_frame(pd.DataFrame({"Hour": [1, 2], "Load": [3.0, 4.0]}))
    4.0
    """
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    column = _first_value_column(frame)
    if column is None:
        return None
    return _series_peak(frame[column])


def _series_peak(series: pd.Series) -> float | None:
    """Return the maximum finite value in a series.

    Parameters
    ----------
    series : pandas.Series
        Candidate numeric values.

    Returns
    -------
    float or None
        Maximum finite value, or ``None`` when no finite values exist.

    Examples
    --------
    >>> _series_peak(pd.Series([1, 3, float("nan")]))
    3.0
    """
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.max())


def _series_mean(series: pd.Series) -> float | None:
    """Return the mean finite value in a series.

    Parameters
    ----------
    series : pandas.Series
        Candidate numeric values.

    Returns
    -------
    float or None
        Mean finite value, or ``None`` when no finite values exist.

    Examples
    --------
    >>> _series_mean(pd.Series([1, 3, float("nan")]))
    2.0
    """
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.mean())


def _table_float(frame: pd.DataFrame, row_label: str, column: str) -> float | None:
    """Return a float from a row/column property table.

    Parameters
    ----------
    frame : pandas.DataFrame
        Row-indexed property table.
    row_label : str
        Property row label.
    column : str
        Technology column name.

    Returns
    -------
    float or None
        Parsed finite value, or ``None`` when unavailable.

    Examples
    --------
    >>> _table_float(pd.DataFrame({"Battery": [1.5]}, index=["P_Capex"]), "P_Capex", "Battery")
    1.5
    """
    if row_label not in frame.index or column not in frame.columns:
        return None
    return _optional_float(frame.at[row_label, column])


def _table_int(frame: pd.DataFrame, row_label: str, column: str) -> int | None:
    """Return an integer from a row/column property table.

    Parameters
    ----------
    frame : pandas.DataFrame
        Row-indexed property table.
    row_label : str
        Property row label.
    column : str
        Technology column name.

    Returns
    -------
    int or None
        Parsed integer value, or ``None`` when unavailable.

    Examples
    --------
    >>> _table_int(pd.DataFrame({"Battery": [3]}, index=["Lifetime"]), "Lifetime", "Battery")
    3
    """
    value = _table_float(frame, row_label, column)
    return int(value) if value is not None else None


def _table_bool(frame: pd.DataFrame, row_label: str, column: str) -> bool | None:
    """Return a boolean from a row/column property table.

    Parameters
    ----------
    frame : pandas.DataFrame
        Row-indexed property table.
    row_label : str
        Property row label.
    column : str
        Technology column name.

    Returns
    -------
    bool or None
        Parsed boolean value, or ``None`` when unavailable.

    Examples
    --------
    >>> _table_bool(pd.DataFrame({"Battery": [1]}, index=["Coupled"]), "Coupled", "Battery")
    True
    """
    value = _table_float(frame, row_label, column)
    return bool(value) if value is not None else None


def _optional_float(value: Any) -> float | None:
    """Return a finite float or ``None``.

    Parameters
    ----------
    value : Any
        Candidate numeric value.

    Returns
    -------
    float or None
        Finite float value, or ``None`` for missing/non-finite input.

    Examples
    --------
    >>> _optional_float("1.5")
    1.5
    >>> _optional_float(float("nan")) is None
    True
    """
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _optional_str(value: Any) -> str | None:
    """Return a non-empty string or ``None``.

    Parameters
    ----------
    value : Any
        Candidate string value.

    Returns
    -------
    str or None
        Stripped non-empty string, or ``None``.

    Examples
    --------
    >>> _optional_str(" area ")
    'area'
    >>> _optional_str("") is None
    True
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


def _row_ext(row: Mapping[str, Any], *, exclude: set[str]) -> dict[str, Any]:
    """Return JSON-friendly metadata from unmodeled row fields.

    Parameters
    ----------
    row : mapping of str to Any
        Source row data.
    exclude : set[str]
        Keys already represented by typed component fields.

    Returns
    -------
    dict[str, Any]
        Metadata dictionary containing scalar JSON-friendly values.

    Examples
    --------
    >>> _row_ext({"id": "x", "latitude": 1.2}, exclude={"id"})
    {'latitude': 1.2}
    """
    metadata: dict[str, Any] = {}
    for key, value in row.items():
        if key in exclude:
            continue
        clean = _clean_metadata_value(value)
        if clean is not None:
            metadata[str(key)] = clean
    return metadata


def _geographic_info_by_area(data: Mapping[str, Any]) -> dict[str, GeographicInfo]:
    """Derive bus geographic attributes from generator coordinates.

    Parameters
    ----------
    data : mapping of str to Any
        SDOM data dictionary containing per-area VRE plant tables.

    Returns
    -------
    dict[str, GeographicInfo]
        Geographic attributes keyed by area id, using the mean longitude and
        latitude of generators with explicit coordinates in each area.

    Examples
    --------
    >>> frame = pd.DataFrame({"longitude": [-100.0, -102.0], "latitude": [40.0, 42.0]})
    >>> attrs = _geographic_info_by_area({"per_area_pv_plants": {"A": frame}})
    >>> attrs["A"].geo_json.coordinates
    [-101.0, 41.0]
    """
    coordinates_by_area: dict[str, list[tuple[float, float]]] = {}
    for source_key in ("per_area_pv_plants", "per_area_wind_plants", "per_area_balancing_units"):
        for area_id, frame in _iter_area_frames(data.get(source_key)):
            if "longitude" not in frame.columns or "latitude" not in frame.columns:
                continue
            for row in frame[["longitude", "latitude"]].itertuples(index=False):
                longitude = _optional_float(row.longitude)
                latitude = _optional_float(row.latitude)
                if longitude is None or latitude is None:
                    continue
                coordinates_by_area.setdefault(area_id, []).append((longitude, latitude))

    return {
        area_id: GeographicInfo(
            geo_json=GeoLocation(
                coordinates=[
                    float(np.mean([point[0] for point in coordinates])),
                    float(np.mean([point[1] for point in coordinates])),
                ]
            ),
            source="derived_area_centroid",
        )
        for area_id, coordinates in coordinates_by_area.items()
        if coordinates
    }


def _attach_geographic_info(system: System, component: Any, row: Mapping[str, Any], *, source: str) -> bool:
    """Attach explicit row-level geographic information to a component.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    component : Any
        Component that receives the supplemental attribute.
    row : mapping of str to Any
        Source row containing optional ``longitude`` and ``latitude`` fields.
    source : str
        Source label stored on the supplemental attribute.

    Returns
    -------
    bool
        ``True`` when a geographic attribute was attached.

    Examples
    --------
    >>> system = System(name="example")
    >>> area = SDOMArea(name="A")
    >>> system.add_component(area)
    >>> _attach_geographic_info(system, area, {"longitude": -105, "latitude": 40}, source="demo")
    True
    """
    longitude = _optional_float(row.get("longitude"))
    latitude = _optional_float(row.get("latitude"))
    if longitude is None or latitude is None:
        return False
    attribute = GeographicInfo(
        geo_json=GeoLocation(coordinates=[longitude, latitude]),
        source=source,
    )
    system.add_supplemental_attribute(component, attribute)
    return True


def _attach_bus_geographic_info(system: System, component: Any, bus: SDOMBus) -> bool:
    """Attach a bus geographic attribute to another component.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    component : Any
        Component that should share the bus location attribute.
    bus : SDOMBus
        Bus whose geographic attribute is reused.

    Returns
    -------
    bool
        ``True`` when the bus has a geographic attribute that was attached.

    Examples
    --------
    >>> system = System(name="example")
    >>> area = SDOMArea(name="A")
    >>> bus = SDOMBus(name="A", area=area)
    >>> system.add_component(area); system.add_component(bus)
    >>> system.add_supplemental_attribute(bus, GeographicInfo.example())
    >>> _attach_bus_geographic_info(system, area, bus)
    True
    """
    attributes = list(system.get_supplemental_attributes_with_component(bus, GeographicInfo))
    if not attributes:
        return False
    system.add_supplemental_attribute(component, attributes[0])
    return True



def _clean_metadata_value(value: Any) -> Any:
    """Return a JSON-friendly scalar metadata value.

    Parameters
    ----------
    value : Any
        Candidate metadata value.

    Returns
    -------
    Any
        Cleaned scalar value, or ``None`` for missing/non-finite values.

    Examples
    --------
    >>> _clean_metadata_value(np.int64(2))
    2
    """
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


__all__ = ["load_system", "load_system_from_data", "system_to_data_dict"]
