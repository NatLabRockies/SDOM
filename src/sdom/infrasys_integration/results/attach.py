"""Helpers that attach typed SDOM result attributes to a system."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd
from infrasys import System

from sdom.results import OptimizationResults

from .context import _ResultContext, _line_records, _unique_string
from .helpers import (
    LOGGER,
    _DISPATCH_COLUMNS,
    _EXCHANGE_COLUMNS,
    _GENERATOR_PREFIX_BY_TECHNOLOGY,
    _float_list,
    _int_list,
    _iter_numeric_leaves,
    _iter_numeric_paths,
    _json_scalar,
    _optional_float,
    _optional_float_list,
    _optional_str,
)
from ..models import (
    SDOMArea,
    SDOMAreaDispatchMetric,
    SDOMAreaDispatchResult,
    SDOMAreaDispatchSeries,
    SDOMCapacityResult,
    SDOMComponent,
    SDOMCostResult,
    SDOMCurtailmentResult,
    SDOMGenerationResult,
    SDOMInstalledCapacityResult,
    SDOMInterregionalExchangeResult,
    SDOMProblemInfoResult,
    SDOMStorage,
    SDOMStorageDispatchResult,
    SDOMSummaryMetricResult,
    SDOMThermalGenerationResult,
    SDOMTransmissionInterface,
)
from .ownership import (
    _component_by_name,
    _get_default_area,
    _storage_by_area_and_technology,
)


def _attach_problem_info_results(
    system: System,
    owner: SDOMComponent,
    problem_info: Mapping[str, Any],
    *,
    context: _ResultContext,
) -> None:
    """Attach solver problem information entries.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : SDOMComponent
        Scenario-level owner.
    problem_info : mapping of str to Any
        Problem information dictionary.
    context : _ResultContext
        Shared run metadata.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_problem_info_results(System(name="empty"), SDOMArea(name="A"), {}, context=_ResultContext("run-1", None, None))
    """
    for key, value in problem_info.items():
        system.add_supplemental_attribute(
            owner,
            SDOMProblemInfoResult(**context.kwargs, key=str(key), value=_json_scalar(value)),
        )


def _attach_capacity_results(
    system: System,
    owner: SDOMComponent,
    capacity: Mapping[str, Any],
    *,
    context: _ResultContext,
    area: str | None = None,
) -> None:
    """Attach aggregate capacity metrics.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : SDOMComponent
        Component that owns aggregate metrics.
    capacity : mapping of str to Any
        Capacity result dictionary.
    context : _ResultContext
        Shared run metadata.
    area : str, optional
        Area associated with the metrics.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_capacity_results(System(name="empty"), SDOMArea(name="A"), {}, context=_ResultContext("run-1", None, None))
    """
    for technology, value in _iter_numeric_leaves(capacity):
        system.add_supplemental_attribute(
            owner,
            SDOMCapacityResult(**context.kwargs, technology=technology, value=value, area=area),
        )


def _attach_storage_capacity_results(
    system: System,
    owner: SDOMComponent,
    storage_capacity: Mapping[str, Any],
    *,
    context: _ResultContext,
    area: str | None = None,
) -> None:
    """Attach aggregate storage capacity metrics.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : SDOMComponent
        Component that owns aggregate metrics.
    storage_capacity : mapping of str to Any
        Nested storage capacity dictionary.
    context : _ResultContext
        Shared run metadata.
    area : str, optional
        Area associated with the metrics.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_storage_capacity_results(System(name="empty"), SDOMArea(name="A"), {}, context=_ResultContext("run-1", None, None))
    """
    for path, value in _iter_numeric_paths(storage_capacity):
        if len(path) < 2:
            continue
        capacity_type, technology = path[0], path[-1]
        system.add_supplemental_attribute(
            owner,
            SDOMCapacityResult(
                **context.kwargs,
                technology=technology,
                capacity_type=capacity_type,
                value=value,
                unit="MWh" if capacity_type == "energy" else "MW",
                area=area,
            ),
        )


def _attach_generation_totals(
    system: System,
    owner: SDOMComponent,
    generation_totals: Mapping[str, Any],
    *,
    context: _ResultContext,
    area: str | None = None,
) -> None:
    """Attach aggregate generation totals.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : SDOMComponent
        Component that owns aggregate metrics.
    generation_totals : mapping of str to Any
        Generation totals by technology.
    context : _ResultContext
        Shared run metadata.
    area : str, optional
        Area associated with the metrics.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_generation_totals(System(name="empty"), SDOMArea(name="A"), {}, context=_ResultContext("run-1", None, None))
    """
    for technology, value in _iter_numeric_leaves(generation_totals):
        system.add_supplemental_attribute(
            owner,
            SDOMGenerationResult(**context.kwargs, technology=technology, total_mwh=value, area=area),
        )


def _attach_area_dispatch_results(system: System, results: OptimizationResults, *, context: _ResultContext) -> None:
    """Attach hourly dispatch results to SDOMArea owners.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    results : sdom.results.OptimizationResults
        Optimization results containing dispatch DataFrames.
    context : _ResultContext
        Shared run metadata.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_area_dispatch_results(System(name="empty"), OptimizationResults(), context=_ResultContext("run-1", None, None))
    """
    frames = _area_generation_frames(results)
    if not frames:
        return

    areas = {area.name: area for area in system.get_components(SDOMArea)}
    default_area = _get_default_area(system)
    for area_name, frame in frames:
        if frame.empty or "Hour" not in frame.columns:
            continue
        target = areas.get(area_name) if area_name is not None else default_area
        if target is None:
            if area_name is not None:
                LOGGER.warning(
                    "No SDOMArea matched dispatch result area %r; skipping area dispatch result attachment.",
                    area_name,
                )
            continue
        system.add_supplemental_attribute(target, _area_dispatch_from_frame(frame, context=context))


def _area_generation_frames(results: OptimizationResults) -> list[tuple[str | None, pd.DataFrame]]:
    """Return area dispatch frames to persist.

    Parameters
    ----------
    results : sdom.results.OptimizationResults
        Optimization results containing generation frames.

    Returns
    -------
    list[tuple[str | None, pandas.DataFrame]]
        Area name and frame pairs. The area name is ``None`` for copperplate.

    Examples
    --------
    >>> _area_generation_frames(OptimizationResults())
    []
    """
    if results.is_zonal and results.area_generation_df:
        return [(str(area), frame) for area, frame in results.area_generation_df.items()]
    if results.generation_df.empty:
        return []
    if "Area" in results.generation_df.columns:
        return [(str(area), group.drop(columns=["Area"])) for area, group in results.generation_df.groupby("Area", sort=False)]
    return [(None, results.generation_df)]


def _area_dispatch_from_frame(frame: pd.DataFrame, *, context: _ResultContext) -> SDOMAreaDispatchResult:
    """Build an area dispatch attribute from a generation DataFrame.

    Parameters
    ----------
    frame : pandas.DataFrame
        Generation dispatch frame with an ``Hour`` column.
    context : _ResultContext
        Shared run metadata.

    Returns
    -------
    SDOMAreaDispatchResult
        Area-owned dispatch attribute.

    Examples
    --------
    >>> attr = _area_dispatch_from_frame(pd.DataFrame({"Hour": [1], "Load (MW)": [2.0]}), context=_ResultContext("run-1", None, None))
    >>> attr.hours
    [1]
    """
    series = [
        SDOMAreaDispatchSeries(metric=SDOMAreaDispatchMetric(column), values=_float_list(frame[column]))
        for column in _DISPATCH_COLUMNS
        if column in frame.columns
    ]
    return SDOMAreaDispatchResult(
        **context.kwargs,
        hours=_int_list(frame["Hour"]),
        scenario=_unique_string(frame["Scenario"]) if "Scenario" in frame.columns else None,
        series=series,
    )


def _attach_curtailment_results(system: System, results: OptimizationResults, *, context: _ResultContext) -> None:
    """Attach aggregate curtailment metrics derived from area dispatch.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    results : sdom.results.OptimizationResults
        Optimization results containing generation frames.
    context : _ResultContext
        Shared run metadata.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_curtailment_results(System(name="empty"), OptimizationResults(), context=_ResultContext("run-1", None, None))
    """
    curtailment_columns = {
        "Solar PV": SDOMAreaDispatchMetric.SOLAR_PV_CURTAILMENT.value,
        "Wind": SDOMAreaDispatchMetric.WIND_CURTAILMENT.value,
    }
    areas = {area.name: area for area in system.get_components(SDOMArea)}
    default_area = _get_default_area(system) if areas else None
    for area_name, frame in _area_generation_frames(results):
        target = areas.get(area_name) if area_name is not None else default_area
        if target is None:
            if area_name is not None:
                LOGGER.warning(
                    "No SDOMArea matched curtailment result area %r; skipping curtailment result attachment.",
                    area_name,
                )
            continue
        for technology, column in curtailment_columns.items():
            if column not in frame.columns:
                continue
            system.add_supplemental_attribute(
                target,
                SDOMCurtailmentResult(
                    **context.kwargs,
                    technology=technology,
                    total_mwh=sum(_float_list(frame[column])),
                    area=area_name,
                ),
            )


def _attach_cost_results(
    system: System,
    owner: SDOMComponent,
    cost_breakdown: Mapping[str, Any],
    *,
    context: _ResultContext,
    area: str | None = None,
) -> None:
    """Attach aggregate cost metrics.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : SDOMComponent
        Component that owns aggregate metrics.
    cost_breakdown : mapping of str to Any
        Nested cost breakdown dictionary.
    context : _ResultContext
        Shared run metadata.
    area : str, optional
        Area associated with the metrics.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_cost_results(System(name="empty"), SDOMArea(name="A"), {}, context=_ResultContext("run-1", None, None))
    """
    for path, value in _iter_numeric_paths(cost_breakdown):
        cost_type = path[0]
        technology = path[-1] if len(path) > 1 else None
        system.add_supplemental_attribute(
            owner,
            SDOMCostResult(**context.kwargs, cost_type=cost_type, technology=technology, value=value, area=area),
        )


def _attach_installed_plant_results(
    system: System,
    owner: SDOMComponent,
    frame: pd.DataFrame,
    *,
    context: _ResultContext,
) -> None:
    """Attach installed capacity rows to plant components when possible.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : SDOMComponent
        Fallback owner for unmatched rows.
    frame : pandas.DataFrame
        Installed plants result DataFrame.
    context : _ResultContext
        Shared run metadata.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_installed_plant_results(System(name="empty"), SDOMArea(name="A"), pd.DataFrame(), context=_ResultContext("run-1", None, None))
    """
    if frame.empty:
        return

    components = _component_by_name(system)
    areas = {area.name: area for area in system.get_components(SDOMArea)}
    for row_order, (_, row) in enumerate(frame.iterrows()):
        technology = str(row["Technology"])
        plant_id = str(row["Plant ID"])
        area_name = _optional_str(row.get("Area")) if "Area" in frame.columns else None
        prefix = _GENERATOR_PREFIX_BY_TECHNOLOGY.get(technology)
        component = components.get(f"{prefix}:{plant_id}") if prefix else None
        target = component or areas.get(area_name) or owner
        if component is None:
            if area_name is not None and area_name in areas:
                LOGGER.warning(
                    "No SDOM generator matched installed plant %r; attaching capacity result to area %r.",
                    plant_id,
                    area_name,
                )
            else:
                LOGGER.warning(
                    "No SDOM generator matched installed plant %r and no matching area was found; "
                    "attaching capacity result to scenario owner %r.",
                    plant_id,
                    owner.name,
                )
        system.add_supplemental_attribute(
            target,
            SDOMInstalledCapacityResult(
                **context.kwargs,
                plant_id=plant_id,
                technology=technology,
                row_order=row_order,
                installed_capacity_mw=float(row["Installed Capacity (MW)"]),
                max_capacity_mw=_optional_float(row.get("Max Capacity (MW)")),
                capacity_fraction=_optional_float(row.get("Capacity Fraction")),
            ),
        )


def _attach_storage_dispatch_results(
    system: System,
    owner: SDOMComponent,
    frame: pd.DataFrame,
    *,
    context: _ResultContext,
) -> None:
    """Attach storage dispatch time series to storage components.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : SDOMComponent
        Fallback owner for unmatched storage rows.
    frame : pandas.DataFrame
        Storage dispatch result DataFrame.
    context : _ResultContext
        Shared run metadata.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_storage_dispatch_results(System(name="empty"), SDOMArea(name="A"), pd.DataFrame(), context=_ResultContext("run-1", None, None))
    """
    if frame.empty:
        return

    storage_by_key = _storage_by_area_and_technology(system)
    group_cols = ["Technology"]
    if "Area" in frame.columns:
        group_cols.insert(0, "Area")

    for row_order, (key, group) in enumerate(frame.groupby(group_cols, sort=False)):
        target = _resolve_storage_dispatch_owner(storage_by_key, key)
        system.add_supplemental_attribute(
            target,
            SDOMStorageDispatchResult(
                **context.kwargs,
                hours=_int_list(group["Hour"]),
                row_order=row_order,
                charge_mw=_float_list(group["Charging power (MW)"]),
                discharge_mw=_float_list(group["Discharging power (MW)"]),
                state_of_charge_mwh=_float_list(group["State of charge (MWh)"]),
            ),
        )


def _validate_storage_dispatch_owners(system: System, frame: pd.DataFrame) -> None:
    """Ensure every storage dispatch group has an SDOMStorage owner.

    Parameters
    ----------
    system : infrasys.System
        System containing typed SDOM components.
    frame : pandas.DataFrame
        Storage dispatch result DataFrame.

    Returns
    -------
    None
        Raises before any result attributes are attached when a storage owner
        cannot be resolved.
    """
    if frame.empty:
        return

    storage_by_key = _storage_by_area_and_technology(system)
    group_cols = ["Technology"]
    if "Area" in frame.columns:
        group_cols.insert(0, "Area")

    for key, _ in frame.groupby(group_cols, sort=False):
        _resolve_storage_dispatch_owner(storage_by_key, key)


def _resolve_storage_dispatch_owner(
    storage_by_key: dict[tuple[str | None, str], SDOMStorage],
    key: str | tuple[Any, ...],
) -> SDOMStorage:
    """Resolve the storage component that owns one dispatch group.

    Parameters
    ----------
    storage_by_key : dict[tuple[str | None, str], SDOMStorage]
        Storage components keyed by area and technology.
    key : str or tuple
        Pandas group key containing technology, and optionally area.

    Returns
    -------
    SDOMStorage
        Matching storage component.

    Raises
    ------
    ValueError
        If no storage component matches the group technology and area.
    """
    if isinstance(key, tuple):
        area, technology = str(key[0]), str(key[-1])
    else:
        area, technology = None, str(key)
    target = storage_by_key.get((area, technology)) or storage_by_key.get((None, technology))
    if target is None:
        raise ValueError(
            f"Cannot attach storage dispatch for technology {technology!r}; "
            "no matching SDOMStorage component exists."
        )
    return target


def _attach_thermal_generation_results(
    system: System,
    owner: SDOMComponent,
    frame: pd.DataFrame,
    *,
    context: _ResultContext,
) -> None:
    """Attach thermal generation time series to thermal components.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : SDOMComponent
        Fallback owner for unmatched plant columns.
    frame : pandas.DataFrame
        Thermal generation result DataFrame.
    context : _ResultContext
        Shared run metadata.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_thermal_generation_results(System(name="empty"), SDOMArea(name="A"), pd.DataFrame(), context=_ResultContext("run-1", None, None))
    """
    if frame.empty:
        return

    components = _component_by_name(system)
    area_column = "Area" if "Area" in frame.columns else None
    ignore = {"Hour"}
    if area_column:
        ignore.add(area_column)

    groups = frame.groupby(area_column, sort=False) if area_column else [(None, frame)]
    for _, group in groups:
        for column in group.columns:
            if column in ignore:
                continue
            target = components.get(f"thermal:{column}")
            if target is None:
                LOGGER.warning(
                    "No SDOM thermal generator matched column %r; attaching generation result to scenario owner %r.",
                    column,
                    owner.name,
                )
                target = owner
            system.add_supplemental_attribute(
                target,
                SDOMThermalGenerationResult(
                    **context.kwargs,
                    hours=_int_list(group["Hour"]),
                    generation_mw=_float_list(group[column]),
                ),
            )


def _attach_summary_results(
    system: System,
    owner: SDOMComponent,
    frame: pd.DataFrame,
    *,
    context: _ResultContext,
    area: str | None = None,
) -> None:
    """Attach summary table rows.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : SDOMComponent
        Component that owns summary rows.
    frame : pandas.DataFrame
        Summary DataFrame.
    context : _ResultContext
        Shared run metadata.
    area : str, optional
        Area associated with these summary rows.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_summary_results(System(name="empty"), SDOMArea(name="A"), pd.DataFrame(), context=_ResultContext("run-1", None, None))
    """
    if frame.empty:
        return
    for row_order, (_, row) in enumerate(frame.iterrows()):
        system.add_supplemental_attribute(
            owner,
            SDOMSummaryMetricResult(
                **context.kwargs,
                row_order=row_order,
                metric=str(row.get("Metric", "")),
                technology=_optional_str(row.get("Technology")),
                run=_json_scalar(row.get("Run")),
                optimal_value=_json_scalar(row.get("Optimal Value")),
                unit=_optional_str(row.get("Unit")),
            ),
        )


def _attach_interregional_exchange_results(system: System, frame: pd.DataFrame, *, context: _ResultContext) -> None:
    """Attach interregional exchange time series to transmission interfaces.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    frame : pandas.DataFrame
        Interregional exchange DataFrame.
    context : _ResultContext
        Shared run metadata.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_interregional_exchange_results(System(name="empty"), pd.DataFrame(), context=_ResultContext("run-1", None, None))
    """
    if frame.empty:
        return
    missing_columns = [column for column in _EXCHANGE_COLUMNS if column not in frame.columns]
    if missing_columns:
        LOGGER.warning(
            "Interregional exchange results are missing required columns %s; skipping exchange result attachment.",
            missing_columns,
        )
        return
    lines = {line.name.removeprefix("line:"): line for line in system.get_components(SDOMTransmissionInterface)}
    for line_id, group in frame.groupby("line_id", sort=False):
        line = lines.get(str(line_id))
        if line is None:
            continue
        system.add_supplemental_attribute(
            line,
            SDOMInterregionalExchangeResult(
                **context.kwargs,
                hours=_int_list(group["hour"]),
                flow_signed_mw=_float_list(group["flow_signed_MW"]),
                flow_ft_mw=_float_list(group["flow_FT_MW"]),
                flow_tf_mw=_float_list(group["flow_TF_MW"]),
                cap_ft_mw=_float_list(group["cap_FT_MW"]),
                cap_tf_mw=_float_list(group["cap_TF_MW"]),
                utilization_ft=_optional_float_list(group["utilization_FT"]),
                utilization_tf=_optional_float_list(group["utilization_TF"]),
            ),
        )


def _attach_area_results(
    system: System,
    owner: SDOMComponent,
    results: OptimizationResults,
    *,
    context: _ResultContext,
) -> None:
    """Attach zonal area-level aggregate result dictionaries and summaries.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : SDOMComponent
        Fallback owner for unknown areas.
    results : sdom.results.OptimizationResults
        Optimization results to attach.
    context : _ResultContext
        Shared run metadata.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_area_results(System(name="empty"), SDOMArea(name="A"), OptimizationResults(), context=_ResultContext("run-1", None, None))
    """
    if not results.is_zonal:
        return

    areas = {area.name: area for area in system.get_components(SDOMArea)}
    for area_id in results.areas:
        area = str(area_id)
        target = areas.get(area)
        if target is None:
            LOGGER.warning(
                "No SDOMArea matched result area %r; attaching aggregate area results to scenario owner %r.",
                area,
                owner.name,
            )
            target = owner
        _attach_capacity_results(system, target, results.area_capacity.get(area_id, {}), context=context, area=area)
        _attach_storage_capacity_results(
            system,
            target,
            results.area_storage_capacity.get(area_id, {}),
            context=context,
            area=area,
        )
        _attach_generation_totals(
            system,
            target,
            results.area_generation_totals.get(area_id, {}),
            context=context,
            area=area,
        )
        _attach_cost_results(system, target, results.area_cost_breakdown.get(area_id, {}), context=context, area=area)
        _attach_summary_results(system, target, results.area_summary_df.get(area_id, pd.DataFrame()), context=context, area=area)
