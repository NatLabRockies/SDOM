"""Helpers that rebuild SDOM optimization results from system attributes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd
from infrasys import System

from sdom.results import OptimizationResults

from .context import _ResultFilters, _iter_result_attributes
from .helpers import _DISPATCH_COLUMNS, _EXCHANGE_COLUMNS, _SUMMARY_COLUMNS
from ..models import (
    SDOMArea,
    SDOMAreaDispatchMetric,
    SDOMAreaDispatchResult,
    SDOMAreaDispatchSeries,
    SDOMCapacityResult,
    SDOMCostResult,
    SDOMGenerationResult,
    SDOMInstalledCapacityResult,
    SDOMInterregionalExchangeResult,
    SDOMProblemInfoResult,
    SDOMStorage,
    SDOMStorageDispatchResult,
    SDOMSummaryMetricResult,
    SDOMThermalGenerationResult,
    SDOMThermalGenerator,
    SDOMTransmissionInterface,
)
from .ownership import _area_name_from_owner


def _rebuild_problem_info(system: System, *, filters: _ResultFilters) -> dict[str, Any]:
    """Rebuild solver problem information.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    dict[str, Any]
        Problem information dictionary.

    Examples
    --------
    >>> _rebuild_problem_info(System(name="empty"), filters=_ResultFilters())
    {}
    """
    return {
        attr.key: attr.value
        for _, attr in _iter_result_attributes(system, SDOMProblemInfoResult, filters=filters)
    }


def _rebuild_capacity_results(system: System, results: OptimizationResults, *, filters: _ResultFilters) -> None:
    """Rebuild capacity dictionaries from capacity attributes.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    results : sdom.results.OptimizationResults
        Results object to mutate.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    None
        ``results`` is mutated in place.

    Examples
    --------
    >>> _rebuild_capacity_results(System(name="empty"), OptimizationResults(), filters=_ResultFilters())
    """
    for _, attr in _iter_result_attributes(system, SDOMCapacityResult, filters=filters):
        if attr.area is not None:
            if attr.capacity_type == "installed":
                results.area_capacity.setdefault(attr.area, {})[attr.technology] = attr.value
            else:
                results.area_storage_capacity.setdefault(attr.area, {}).setdefault(attr.capacity_type, {})[
                    attr.technology
                ] = attr.value
        elif attr.capacity_type == "installed":
            results.capacity[attr.technology] = attr.value
        else:
            results.storage_capacity.setdefault(attr.capacity_type, {})[attr.technology] = attr.value


def _rebuild_generation_totals(system: System, results: OptimizationResults, *, filters: _ResultFilters) -> None:
    """Rebuild generation total dictionaries.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    results : sdom.results.OptimizationResults
        Results object to mutate.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    None
        ``results`` is mutated in place.

    Examples
    --------
    >>> _rebuild_generation_totals(System(name="empty"), OptimizationResults(), filters=_ResultFilters())
    """
    for _, attr in _iter_result_attributes(system, SDOMGenerationResult, filters=filters):
        if attr.area is None:
            results.generation_totals[attr.technology] = attr.total_mwh
        else:
            results.area_generation_totals.setdefault(attr.area, {})[attr.technology] = attr.total_mwh


def _rebuild_cost_results(system: System, results: OptimizationResults, *, filters: _ResultFilters) -> None:
    """Rebuild cost dictionaries.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    results : sdom.results.OptimizationResults
        Results object to mutate.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    None
        ``results`` is mutated in place.

    Examples
    --------
    >>> _rebuild_cost_results(System(name="empty"), OptimizationResults(), filters=_ResultFilters())
    """
    for _, attr in _iter_result_attributes(system, SDOMCostResult, filters=filters):
        target = results.cost_breakdown if attr.area is None else results.area_cost_breakdown.setdefault(attr.area, {})
        if attr.technology is None:
            target[attr.cost_type] = attr.value
        else:
            target.setdefault(attr.cost_type, {})[attr.technology] = attr.value


def _rebuild_area_dispatch_results(system: System, results: OptimizationResults, *, filters: _ResultFilters) -> None:
    """Rebuild generation dispatch DataFrames.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    results : sdom.results.OptimizationResults
        Results object to mutate.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    None
        ``results`` is mutated in place.

    Examples
    --------
    >>> _rebuild_area_dispatch_results(System(name="empty"), OptimizationResults(), filters=_ResultFilters())
    """
    frames: list[pd.DataFrame] = []
    for owner, attr in _iter_result_attributes(system, SDOMAreaDispatchResult, filters=filters):
        frame = _area_dispatch_to_frame(attr)
        if results.is_zonal:
            area = owner.name if isinstance(owner, SDOMArea) else ""
            results.area_generation_df[area] = frame
            frame_with_area = frame.copy()
            insert_pos = list(frame_with_area.columns).index("Hour") + 1 if "Hour" in frame_with_area.columns else 0
            frame_with_area.insert(insert_pos, "Area", area)
            frames.append(frame_with_area)
        else:
            frames.append(frame)
    if frames:
        results.generation_df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0].reset_index(drop=True)


def _area_dispatch_to_frame(attr: SDOMAreaDispatchResult) -> pd.DataFrame:
    """Convert an area dispatch attribute to a DataFrame.

    Parameters
    ----------
    attr : SDOMAreaDispatchResult
        Area dispatch attribute.

    Returns
    -------
    pandas.DataFrame
        Generation dispatch DataFrame.

    Examples
    --------
    >>> attr = SDOMAreaDispatchResult(run_id="r", scenario="c", hours=[1], series=[SDOMAreaDispatchSeries(metric=SDOMAreaDispatchMetric.LOAD, values=[2.0])])
    >>> list(_area_dispatch_to_frame(attr).columns)
    ['Scenario', 'Hour', 'Load (MW)']
    """
    data: dict[str, Any] = {"Hour": attr.hours}
    if attr.scenario is not None:
        data = {"Scenario": [attr.scenario] * len(attr.hours), **data}
    for item in sorted(attr.series, key=lambda series: _DISPATCH_COLUMNS.index(series.metric.value)):
        data[item.metric.value] = item.values
    return pd.DataFrame(data)


def _rebuild_storage_dispatch_results(system: System, results: OptimizationResults, *, filters: _ResultFilters) -> None:
    """Rebuild storage dispatch DataFrames.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    results : sdom.results.OptimizationResults
        Results object to mutate.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    None
        ``results`` is mutated in place.

    Examples
    --------
    >>> _rebuild_storage_dispatch_results(System(name="empty"), OptimizationResults(), filters=_ResultFilters())
    """
    rows_by_area: dict[str, list[dict[str, Any]]] = {}
    system_rows: list[dict[str, Any]] = []
    for owner, attr in _iter_result_attributes(system, SDOMStorageDispatchResult, filters=filters):
        technology = owner.technology if isinstance(owner, SDOMStorage) else owner.name
        area = owner.bus.area.name if isinstance(owner, SDOMStorage) else None
        rows = [
            {
                "Hour": hour,
                "Technology": technology,
                "Charging power (MW)": charge,
                "Discharging power (MW)": discharge,
                "State of charge (MWh)": soc,
                "__order": attr.row_order,
            }
            for hour, charge, discharge, soc in zip(
                attr.hours,
                attr.charge_mw,
                attr.discharge_mw,
                attr.state_of_charge_mwh,
                strict=True,
            )
        ]
        if results.is_zonal and area is not None:
            rows_by_area.setdefault(area, []).extend(rows)
            for row in rows:
                row_with_area = dict(row)
                row_with_area["Area"] = area
                system_rows.append(row_with_area)
        else:
            system_rows.extend(rows)

    if results.is_zonal:
        results.area_storage_df = {
            area: _sort_storage_frame(pd.DataFrame(rows))[
                ["Hour", "Technology", "Charging power (MW)", "Discharging power (MW)", "State of charge (MWh)"]
            ]
            for area, rows in rows_by_area.items()
        }
        if system_rows:
            frame = _sort_storage_frame(pd.DataFrame(system_rows), area_column=True)
            results.storage_df = frame[["Hour", "Area", "Technology", "Charging power (MW)", "Discharging power (MW)", "State of charge (MWh)"]]
    elif system_rows:
        frame = _sort_storage_frame(pd.DataFrame(system_rows))
        results.storage_df = frame[["Hour", "Technology", "Charging power (MW)", "Discharging power (MW)", "State of charge (MWh)"]]


def _sort_storage_frame(frame: pd.DataFrame, *, area_column: bool = False) -> pd.DataFrame:
    """Sort a storage dispatch frame into SDOM output order.

    Parameters
    ----------
    frame : pandas.DataFrame
        Storage dispatch DataFrame.
    area_column : bool, default=False
        Include ``Area`` as a secondary sort key.

    Returns
    -------
    pandas.DataFrame
        Stable-sorted storage dispatch DataFrame.

    Examples
    --------
    >>> _sort_storage_frame(pd.DataFrame({"Hour": [2, 1], "Technology": ["B", "A"]}))["Hour"].tolist()
    [1, 2]
    """
    keys = ["Hour"]
    if area_column and "Area" in frame.columns:
        keys.append("Area")
    if "__order" in frame.columns:
        keys.append("__order")
    else:
        keys.append("Technology")
    return frame.sort_values(keys, kind="stable").reset_index(drop=True)


def _rebuild_thermal_generation_results(system: System, results: OptimizationResults, *, filters: _ResultFilters) -> None:
    """Rebuild thermal generation DataFrames.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    results : sdom.results.OptimizationResults
        Results object to mutate.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    None
        ``results`` is mutated in place.

    Examples
    --------
    >>> _rebuild_thermal_generation_results(System(name="empty"), OptimizationResults(), filters=_ResultFilters())
    """
    by_area: dict[str | None, list[tuple[str, SDOMThermalGenerationResult]]] = {}
    for owner, attr in _iter_result_attributes(system, SDOMThermalGenerationResult, filters=filters):
        plant = owner.name.removeprefix("thermal:") if isinstance(owner, SDOMThermalGenerator) else owner.name
        area = owner.bus.area.name if isinstance(owner, SDOMThermalGenerator) else None
        by_area.setdefault(area if results.is_zonal else None, []).append((plant, attr))

    frames: list[pd.DataFrame] = []
    for area, entries in by_area.items():
        frame = _thermal_entries_to_frame(entries)
        if results.is_zonal and area is not None:
            results.area_thermal_generation_df[area] = frame
            frame_with_area = frame.copy()
            frame_with_area.insert(1, "Area", area)
            frames.append(frame_with_area)
        else:
            frames.append(frame)
    if frames:
        results.thermal_generation_df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


def _thermal_entries_to_frame(entries: Iterable[tuple[str, SDOMThermalGenerationResult]]) -> pd.DataFrame:
    """Convert thermal generation entries to a DataFrame.

    Parameters
    ----------
    entries : iterable of tuple[str, SDOMThermalGenerationResult]
        Plant names and thermal generation attributes.

    Returns
    -------
    pandas.DataFrame
        Thermal generation DataFrame.

    Examples
    --------
    >>> frame = _thermal_entries_to_frame([("p", SDOMThermalGenerationResult(run_id="r", hours=[1], generation_mw=[2.0]))])
    >>> list(frame.columns)
    ['Hour', 'p']
    """
    entries = list(entries)
    if not entries:
        return pd.DataFrame()
    hours = entries[0][1].hours
    data: dict[str, Any] = {"Hour": hours}
    for plant, attr in sorted(entries, key=lambda item: item[0]):
        data[plant] = attr.generation_mw
    return pd.DataFrame(data)


def _rebuild_installed_capacity_results(system: System, results: OptimizationResults, *, filters: _ResultFilters) -> None:
    """Rebuild installed plant DataFrames.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    results : sdom.results.OptimizationResults
        Results object to mutate.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    None
        ``results`` is mutated in place.

    Examples
    --------
    >>> _rebuild_installed_capacity_results(System(name="empty"), OptimizationResults(), filters=_ResultFilters())
    """
    rows_by_area: dict[str, list[dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    for owner, attr in _iter_result_attributes(system, SDOMInstalledCapacityResult, filters=filters):
        row = {
            "Plant ID": attr.plant_id,
            "Technology": attr.technology,
            "Installed Capacity (MW)": attr.installed_capacity_mw,
            "Max Capacity (MW)": attr.max_capacity_mw,
            "Capacity Fraction": attr.capacity_fraction,
            "__order": attr.row_order,
        }
        area = _area_name_from_owner(system, owner)
        if results.is_zonal and area is not None:
            rows_by_area.setdefault(area, []).append(row)
            row = {"Area": area, **row}
        rows.append(row)
    if rows:
        results.installed_plants_df = _installed_plants_frame(rows)
    results.area_installed_plants_df = {area: _installed_plants_frame(area_rows) for area, area_rows in rows_by_area.items()}


def _installed_plants_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Build an installed-plants DataFrame in original row order.

    Parameters
    ----------
    rows : list[dict[str, Any]]
        Installed plant rows containing a private ``__order`` key.

    Returns
    -------
    pandas.DataFrame
        Installed plants DataFrame without private ordering columns.

    Examples
    --------
    >>> frame = _installed_plants_frame([{"Plant ID": "p", "Technology": "Solar PV", "Installed Capacity (MW)": 1.0, "Max Capacity (MW)": 2.0, "Capacity Fraction": 0.5, "__order": 0}])
    >>> list(frame.columns)
    ['Plant ID', 'Technology', 'Installed Capacity (MW)', 'Max Capacity (MW)', 'Capacity Fraction']
    """
    frame = pd.DataFrame(rows).sort_values("__order", kind="stable").reset_index(drop=True)
    columns = ["Plant ID", "Technology", "Installed Capacity (MW)", "Max Capacity (MW)", "Capacity Fraction"]
    if "Area" in frame.columns:
        columns.insert(0, "Area")
    return frame[columns]


def _rebuild_summary_results(system: System, results: OptimizationResults, *, filters: _ResultFilters) -> None:
    """Rebuild summary DataFrames.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    results : sdom.results.OptimizationResults
        Results object to mutate.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    None
        ``results`` is mutated in place.

    Examples
    --------
    >>> _rebuild_summary_results(System(name="empty"), OptimizationResults(), filters=_ResultFilters())
    """
    rows: list[dict[str, Any]] = []
    rows_by_area: dict[str, list[dict[str, Any]]] = {}
    for owner, attr in _iter_result_attributes(system, SDOMSummaryMetricResult, filters=filters):
        row = _summary_row(attr)
        row["__order"] = attr.row_order
        area = owner.name if results.is_zonal and isinstance(owner, SDOMArea) else None
        if area is None:
            rows.append(row)
        else:
            rows_by_area.setdefault(area, []).append(row)
    if rows:
        results.summary_df = _summary_frame(rows)
    results.area_summary_df = {
        area: _summary_frame(area_rows)
        for area, area_rows in rows_by_area.items()
    }


def _summary_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a summary DataFrame in original row order.

    Parameters
    ----------
    rows : list[dict[str, Any]]
        Summary rows containing a private ``__order`` key.

    Returns
    -------
    pandas.DataFrame
        Summary DataFrame without private ordering columns.

    Examples
    --------
    >>> _summary_frame([{"Metric": "m", "Technology": None, "Run": None, "Optimal Value": 1.0, "Unit": None, "__order": 0}])["Metric"].tolist()
    ['m']
    """
    return pd.DataFrame(rows).sort_values("__order", kind="stable").reset_index(drop=True)[list(_SUMMARY_COLUMNS)]


def _summary_row(attr: SDOMSummaryMetricResult) -> dict[str, Any]:
    """Convert a summary attribute to a table row.

    Parameters
    ----------
    attr : SDOMSummaryMetricResult
        Summary metric attribute.

    Returns
    -------
    dict[str, Any]
        Summary row mapping.

    Examples
    --------
    >>> _summary_row(SDOMSummaryMetricResult(run_id="r", row_order=0, metric="m"))["Metric"]
    'm'
    """
    return {
        "Metric": attr.metric,
        "Technology": attr.technology,
        "Run": attr.run,
        "Optimal Value": attr.optimal_value,
        "Unit": attr.unit,
    }


def _rebuild_interregional_exchanges(system: System, *, filters: _ResultFilters) -> pd.DataFrame:
    """Rebuild the interregional exchanges DataFrame.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    pandas.DataFrame
        Interregional exchanges DataFrame.

    Examples
    --------
    >>> _rebuild_interregional_exchanges(System(name="empty"), filters=_ResultFilters()).empty
    True
    """
    rows: list[dict[str, Any]] = []
    for owner, attr in _iter_result_attributes(system, SDOMInterregionalExchangeResult, filters=filters):
        if not isinstance(owner, SDOMTransmissionInterface):
            continue
        line_id = owner.name.removeprefix("line:")
        from_area = owner.from_bus.area.name
        to_area = owner.to_bus.area.name
        for values in zip(
            attr.hours,
            attr.flow_signed_mw,
            attr.flow_ft_mw,
            attr.flow_tf_mw,
            attr.cap_ft_mw,
            attr.cap_tf_mw,
            attr.utilization_ft,
            attr.utilization_tf,
            strict=True,
        ):
            hour, signed, ft, tf, cap_ft, cap_tf, util_ft, util_tf = values
            rows.append(
                {
                    "line_id": line_id,
                    "from_area": from_area,
                    "to_area": to_area,
                    "hour": hour,
                    "flow_signed_MW": signed,
                    "flow_FT_MW": ft,
                    "flow_TF_MW": tf,
                    "cap_FT_MW": cap_ft,
                    "cap_TF_MW": cap_tf,
                    "utilization_FT": util_ft,
                    "utilization_TF": util_tf,
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=_EXCHANGE_COLUMNS)
