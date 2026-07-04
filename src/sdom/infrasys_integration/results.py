"""Attach SDOM optimization results to infrasys systems."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import pandas as pd
from infrasys import System

from sdom.results import OptimizationResults

from .models import (
    SDOMArea,
    SDOMCapacityResult,
    SDOMComponent,
    SDOMCostResult,
    SDOMCurtailmentResult,
    SDOMDualResult,
    SDOMGenerationResult,
    SDOMOptimizationResult,
    SDOMResultAttribute,
    SDOMScenarioMetadata,
    SDOMStorage,
    SDOMStorageDispatchResult,
)

_GENERATOR_PREFIX_BY_TECHNOLOGY = {
    "Solar PV": "solar",
    "Wind": "wind",
    "Thermal": "thermal",
}

_RESULT_ATTRIBUTE_TYPES = (
    SDOMCapacityResult,
    SDOMCostResult,
    SDOMCurtailmentResult,
    SDOMDualResult,
    SDOMGenerationResult,
    SDOMOptimizationResult,
    SDOMScenarioMetadata,
    SDOMStorageDispatchResult,
)


def add_results_to_system(
    system: System,
    results: OptimizationResults,
    *,
    run_id: str,
    scenario_name: str | None = None,
    case_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> System:
    """Attach one SDOM optimization run to a System.

    Parameters
    ----------
    system : infrasys.System
        System containing typed SDOM components.
    results : sdom.results.OptimizationResults
        Optimization results returned by SDOM's solver pipeline.
    run_id : str
        Stable identifier for this optimization run. Existing results with
        other run identifiers are preserved.
    scenario_name : str, optional
        User-facing scenario name to store on every attached result attribute.
    case_name : str, optional
        SDOM case name to store on every attached result attribute.
    metadata : dict, optional
        JSON-serializable metadata for the scenario.

    Returns
    -------
    infrasys.System
        The same ``system`` instance with supplemental attributes attached.

    Raises
    ------
    ValueError
        If ``run_id`` is empty or the system has no SDOM components that can
        own run-level results.

    Examples
    --------
    >>> from sdom.results import OptimizationResults
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> system = load_system("Data/no_exchange_run_of_river")
    >>> add_results_to_system(system, OptimizationResults(total_cost=1.0), run_id="run-1") is system
    True
    """
    if not run_id:
        raise ValueError("run_id must be a non-empty string.")

    context = _ResultContext(
        run_id=run_id,
        scenario_name=scenario_name,
        case_name=case_name,
    )
    owner = _get_scenario_owner(system)

    system.add_supplemental_attribute(
        owner,
        SDOMScenarioMetadata(**context.kwargs, metadata=dict(metadata or {})),
    )
    system.add_supplemental_attribute(
        owner,
        SDOMOptimizationResult(
            **context.kwargs,
            total_cost=float(results.total_cost),
            gen_mix_target=float(results.gen_mix_target),
            termination_condition=results.termination_condition,
            solver_status=results.solver_status,
        ),
    )

    _attach_capacity_results(system, owner, results.capacity, context=context)
    _attach_storage_capacity_results(system, owner, results.storage_capacity, context=context)
    _attach_generation_totals(system, owner, results.generation_totals, context=context)
    _attach_curtailment_results(system, owner, results.generation_df, context=context)
    _attach_cost_results(system, owner, results.cost_breakdown, context=context)
    _attach_installed_plant_results(system, owner, results.installed_plants_df, context=context)
    _attach_storage_dispatch_results(system, owner, results.storage_df, context=context)
    _attach_thermal_generation_results(system, owner, results.thermal_generation_df, context=context)
    _attach_area_results(system, owner, results, context=context)

    return system


def query_result_attributes(
    system: System,
    *,
    run_id: str | None = None,
    scenario_name: str | None = None,
    case_name: str | None = None,
    attribute_type: type[SDOMResultAttribute] = SDOMResultAttribute,
) -> list[SDOMResultAttribute]:
    """Query SDOM result attributes attached to a System.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    run_id : str, optional
        Return only attributes for this run identifier.
    scenario_name : str, optional
        Return only attributes for this scenario name.
    case_name : str, optional
        Return only attributes for this case name.
    attribute_type : type, default=SDOMResultAttribute
        Supplemental attribute subclass to return.

    Returns
    -------
    list[SDOMResultAttribute]
        Matching result supplemental attributes.

    Examples
    --------
    >>> from sdom.results import OptimizationResults
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> system = add_results_to_system(load_system("Data/no_exchange_run_of_river"), OptimizationResults(), run_id="run-1")
    >>> bool(query_result_attributes(system, run_id="run-1"))
    True
    """
    concrete_types = _RESULT_ATTRIBUTE_TYPES if attribute_type is SDOMResultAttribute else (attribute_type,)
    matches: list[SDOMResultAttribute] = []
    for component in system.get_components(SDOMComponent):
        for concrete_type in concrete_types:
            for attribute in system.get_supplemental_attributes_with_component(component, concrete_type):
                if run_id is not None and attribute.run_id != run_id:
                    continue
                if scenario_name is not None and attribute.scenario_name != scenario_name:
                    continue
                if case_name is not None and attribute.case_name != case_name:
                    continue
                matches.append(attribute)
    return matches


class _ResultContext:
    """Store common result-attachment metadata.

    Parameters
    ----------
    run_id : str
        Stable optimization run identifier.
    scenario_name : str, optional
        User-facing scenario name.
    case_name : str, optional
        SDOM case name.

    Examples
    --------
    >>> _ResultContext("run-1").kwargs["run_id"]
    'run-1'
    """

    def __init__(self, run_id: str, scenario_name: str | None, case_name: str | None) -> None:
        self.kwargs = {
            "run_id": run_id,
            "scenario_name": scenario_name,
            "case_name": case_name,
        }


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
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> system = load_system("Data/no_exchange_run_of_river")
    >>> _attach_capacity_results(system, _get_scenario_owner(system), {"Solar PV": 1.0}, context=_ResultContext("run-1", None, None))
    """
    for technology, value in _iter_numeric_leaves(capacity):
        system.add_supplemental_attribute(
            owner,
            SDOMCapacityResult(
                **context.kwargs,
                technology=technology,
                value=value,
                area=area,
            ),
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
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> system = load_system("Data/no_exchange_run_of_river")
    >>> _attach_storage_capacity_results(system, _get_scenario_owner(system), {"charge": {"Battery": 1.0}}, context=_ResultContext("run-1", None, None))
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
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> system = load_system("Data/no_exchange_run_of_river")
    >>> _attach_generation_totals(system, _get_scenario_owner(system), {"Solar PV": 1.0}, context=_ResultContext("run-1", None, None))
    """
    for technology, value in _iter_numeric_leaves(generation_totals):
        system.add_supplemental_attribute(
            owner,
            SDOMGenerationResult(
                **context.kwargs,
                technology=technology,
                total_mwh=value,
                area=area,
            ),
        )


def _attach_curtailment_results(
    system: System,
    owner: SDOMComponent,
    frame: pd.DataFrame,
    *,
    context: _ResultContext,
) -> None:
    """Attach solar and wind curtailment time series.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : SDOMComponent
        Fallback owner for system-level curtailment metrics.
    frame : pandas.DataFrame
        Generation result frame containing curtailment columns.
    context : _ResultContext
        Shared run metadata.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_curtailment_results(System(name="empty"), object(), pd.DataFrame(), context=_ResultContext("run-1", None, None))
    """
    if frame.empty:
        return

    curtailment_columns = {
        "Solar PV": "Solar PV Curtailment (MW)",
        "Wind": "Wind Curtailment (MW)",
    }
    areas = {area.name: area for area in system.get_components(SDOMArea)}
    groups = frame.groupby("Area", sort=False) if "Area" in frame.columns else [(None, frame)]
    for area, group in groups:
        target = areas.get(str(area), owner) if area is not None else owner
        area_name = str(area) if area is not None else None
        for technology, column in curtailment_columns.items():
            if column not in group.columns:
                continue
            hourly = _float_list(group[column])
            system.add_supplemental_attribute(
                target,
                SDOMCurtailmentResult(
                    **context.kwargs,
                    technology=technology,
                    total_mwh=sum(hourly),
                    hourly_mw=hourly,
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
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> system = load_system("Data/no_exchange_run_of_river")
    >>> _attach_cost_results(system, _get_scenario_owner(system), {"capex": {"Solar PV": 1.0}}, context=_ResultContext("run-1", None, None))
    """
    for path, value in _iter_numeric_paths(cost_breakdown):
        cost_type = path[0]
        technology = path[-1] if len(path) > 1 else None
        system.add_supplemental_attribute(
            owner,
            SDOMCostResult(
                **context.kwargs,
                cost_type=cost_type,
                technology=technology,
                value=value,
                area=area,
            ),
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
    >>> _attach_installed_plant_results(System(name="empty"), object(), pd.DataFrame(), context=_ResultContext("run-1", None, None))
    """
    if frame.empty:
        return

    components = _component_by_name(system)
    for _, row in frame.iterrows():
        technology = str(row["Technology"])
        plant_id = str(row["Plant ID"])
        prefix = _GENERATOR_PREFIX_BY_TECHNOLOGY.get(technology)
        component = components.get(f"{prefix}:{plant_id}") if prefix else None
        target = component or owner
        area = str(row["Area"]) if "Area" in frame.columns else None
        system.add_supplemental_attribute(
            target,
            SDOMCapacityResult(
                **context.kwargs,
                technology=technology,
                capacity_type="installed",
                value=float(row["Installed Capacity (MW)"]),
                unit="MW",
                area=area,
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
    >>> _attach_storage_dispatch_results(System(name="empty"), object(), pd.DataFrame(), context=_ResultContext("run-1", None, None))
    """
    if frame.empty:
        return

    storage_by_key = _storage_by_area_and_technology(system)
    group_cols = ["Technology"]
    if "Area" in frame.columns:
        group_cols.insert(0, "Area")

    for key, group in frame.groupby(group_cols, sort=False):
        if isinstance(key, tuple):
            area, technology = str(key[0]), str(key[-1])
        else:
            area, technology = None, str(key)
        target = storage_by_key.get((area, technology)) or storage_by_key.get((None, technology)) or owner
        system.add_supplemental_attribute(
            target,
            SDOMStorageDispatchResult(
                **context.kwargs,
                technology=technology,
                charge_mw=_float_list(group["Charging power (MW)"]),
                discharge_mw=_float_list(group["Discharging power (MW)"]),
                state_of_charge_mwh=_float_list(group["State of charge (MWh)"]),
                area=area,
            ),
        )


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
    >>> _attach_thermal_generation_results(System(name="empty"), object(), pd.DataFrame(), context=_ResultContext("run-1", None, None))
    """
    if frame.empty:
        return

    components = _component_by_name(system)
    area_column = "Area" if "Area" in frame.columns else None
    ignore = {"Hour"}
    if area_column:
        ignore.add(area_column)

    if area_column:
        for area, area_frame in frame.groupby(area_column, sort=False):
            _attach_thermal_generation_columns(system, owner, components, area_frame, context=context, area=str(area), ignore=ignore)
    else:
        _attach_thermal_generation_columns(system, owner, components, frame, context=context, area=None, ignore=ignore)


def _attach_thermal_generation_columns(
    system: System,
    owner: SDOMComponent,
    components: Mapping[str, SDOMComponent],
    frame: pd.DataFrame,
    *,
    context: _ResultContext,
    area: str | None,
    ignore: set[str],
) -> None:
    """Attach each thermal generation column as one time-series attribute.

    Parameters
    ----------
    system : infrasys.System
        System to mutate.
    owner : SDOMComponent
        Fallback owner.
    components : mapping of str to SDOMComponent
        Components keyed by name.
    frame : pandas.DataFrame
        Thermal generation frame for one area or system.
    context : _ResultContext
        Shared run metadata.
    area : str, optional
        Area associated with these columns.
    ignore : set of str
        Non-plant columns to skip.

    Returns
    -------
    None
        Attributes are attached in place.

    Examples
    --------
    >>> _attach_thermal_generation_columns(System(name="empty"), object(), {}, pd.DataFrame(), context=_ResultContext("run-1", None, None), area=None, ignore=set())
    """
    for column in frame.columns:
        if column in ignore:
            continue
        target = components.get(f"thermal:{column}") or owner
        series = _float_list(frame[column])
        system.add_supplemental_attribute(
            target,
            SDOMGenerationResult(
                **context.kwargs,
                technology="Thermal",
                total_mwh=sum(series),
                hourly_mw=series,
                area=area,
            ),
        )


def _attach_area_results(
    system: System,
    owner: SDOMComponent,
    results: OptimizationResults,
    *,
    context: _ResultContext,
) -> None:
    """Attach zonal area-level aggregate result dictionaries.

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
    >>> from sdom.results import OptimizationResults
    >>> _attach_area_results(System(name="empty"), object(), OptimizationResults(), context=_ResultContext("run-1", None, None))
    """
    if not results.is_zonal:
        return

    areas = {area.name: area for area in system.get_components(SDOMArea)}
    for area_id in results.areas:
        target = areas.get(str(area_id)) or owner
        area = str(area_id)
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


def _iter_numeric_leaves(mapping: Mapping[str, Any]) -> Iterator[tuple[str, float]]:
    """Yield string keys and numeric leaf values from a mapping.

    Parameters
    ----------
    mapping : mapping of str to Any
        Mapping to traverse.

    Yields
    ------
    tuple[str, float]
        Leaf key and numeric value pairs.

    Examples
    --------
    >>> list(_iter_numeric_leaves({"a": 1.0}))
    [('a', 1.0)]
    """
    for key, value in mapping.items():
        if isinstance(value, Mapping):
            yield from _iter_numeric_leaves(value)
        elif _is_number(value):
            yield str(key), float(value)


def _iter_numeric_paths(mapping: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], float]]:
    """Yield key paths and numeric leaf values from a nested mapping.

    Parameters
    ----------
    mapping : mapping of str to Any
        Mapping to traverse.
    prefix : tuple of str, default=()
        Current path prefix used during recursion.

    Yields
    ------
    tuple[tuple[str, ...], float]
        Path and numeric value pairs.

    Examples
    --------
    >>> list(_iter_numeric_paths({"a": {"b": 1.0}}))
    [(('a', 'b'), 1.0)]
    """
    for key, value in mapping.items():
        path = (*prefix, str(key))
        if isinstance(value, Mapping):
            yield from _iter_numeric_paths(value, path)
        elif _is_number(value):
            yield path, float(value)


def _is_number(value: Any) -> bool:
    """Return whether a value should be stored as a numeric metric.

    Parameters
    ----------
    value : Any
        Candidate value.

    Returns
    -------
    bool
        ``True`` when the value is an int or float but not a bool.

    Examples
    --------
    >>> _is_number(1.0)
    True
    >>> _is_number(True)
    False
    """
    return isinstance(value, int | float) and not isinstance(value, bool)


def _float_list(series: pd.Series) -> list[float]:
    """Convert a numeric pandas Series to a compact Python float list.

    Parameters
    ----------
    series : pandas.Series
        Series containing numeric values.

    Returns
    -------
    list[float]
        Values converted to Python floats.

    Examples
    --------
    >>> _float_list(pd.Series([1, 2]))
    [1.0, 2.0]
    """
    return [float(value) for value in series.to_numpy(copy=False)]


__all__ = ["add_results_to_system", "query_result_attributes"]
