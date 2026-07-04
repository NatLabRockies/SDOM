"""Attach SDOM optimization results to infrasys systems."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

import pandas as pd
from infrasys import System

from sdom.results import OptimizationResults

from .models import (
    SDOMArea,
    SDOMAreaDispatchMetric,
    SDOMAreaDispatchResult,
    SDOMAreaDispatchSeries,
    SDOMBus,
    SDOMCapacityResult,
    SDOMComponent,
    SDOMCostResult,
    SDOMCurtailmentResult,
    SDOMDualResult,
    SDOMGenerationResult,
    SDOMInstalledCapacityResult,
    SDOMInterregionalExchangeResult,
    SDOMOptimizationResult,
    SDOMProblemInfoResult,
    SDOMResultAttribute,
    SDOMResultTopologyMetadata,
    SDOMScenarioMetadata,
    SDOMStorage,
    SDOMStorageDispatchResult,
    SDOMSummaryMetricResult,
    SDOMThermalGenerationResult,
    SDOMThermalGenerator,
    SDOMTransmissionInterface,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_COPPERPLATE_AREA_NAME = "Copperplate"

_GENERATOR_PREFIX_BY_TECHNOLOGY = {
    "Solar PV": "solar",
    "Wind": "wind",
    "Thermal": "thermal",
}

_RESULT_ATTRIBUTE_TYPES = (
    SDOMAreaDispatchResult,
    SDOMCapacityResult,
    SDOMCostResult,
    SDOMCurtailmentResult,
    SDOMDualResult,
    SDOMGenerationResult,
    SDOMInstalledCapacityResult,
    SDOMInterregionalExchangeResult,
    SDOMOptimizationResult,
    SDOMProblemInfoResult,
    SDOMResultTopologyMetadata,
    SDOMScenarioMetadata,
    SDOMStorageDispatchResult,
    SDOMSummaryMetricResult,
    SDOMThermalGenerationResult,
)
_DISPATCH_COLUMNS = tuple(metric.value for metric in SDOMAreaDispatchMetric)
_SUMMARY_COLUMNS = ("Metric", "Technology", "Run", "Optimal Value", "Unit")
_EXCHANGE_COLUMNS = (
    "line_id",
    "from_area",
    "to_area",
    "hour",
    "flow_signed_MW",
    "flow_FT_MW",
    "flow_TF_MW",
    "cap_FT_MW",
    "cap_TF_MW",
    "utilization_FT",
    "utilization_TF",
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

    system.add_supplemental_attribute(owner, SDOMScenarioMetadata(**context.kwargs, metadata=dict(metadata or {})))
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
    system.add_supplemental_attribute(
        owner,
        SDOMResultTopologyMetadata(
            **context.kwargs,
            is_zonal=bool(results.is_zonal),
            areas=[str(area) for area in results.areas],
            lines=_line_records(results.lines),
        ),
    )

    _attach_problem_info_results(system, owner, results.problem_info, context=context)
    _attach_capacity_results(system, owner, results.capacity, context=context)
    _attach_storage_capacity_results(system, owner, results.storage_capacity, context=context)
    _attach_generation_totals(system, owner, results.generation_totals, context=context)
    _attach_area_dispatch_results(system, results, context=context)
    _attach_curtailment_results(system, results, context=context)
    _attach_cost_results(system, owner, results.cost_breakdown, context=context)
    _attach_installed_plant_results(system, owner, results.installed_plants_df, context=context)
    _attach_storage_dispatch_results(system, owner, results.storage_df, context=context)
    _attach_thermal_generation_results(system, owner, results.thermal_generation_df, context=context)
    _attach_summary_results(system, owner, results.summary_df, context=context)
    _attach_interregional_exchange_results(system, results.interregional_exchanges_df, context=context)
    _attach_area_results(system, owner, results, context=context)

    return system


def optimization_results_from_system(
    system: System,
    *,
    run_id: str,
    scenario_name: str | None = None,
    case_name: str | None = None,
) -> OptimizationResults:
    """Rebuild OptimizationResults from typed System result attributes.

    Parameters
    ----------
    system : infrasys.System
        System containing SDOM result supplemental attributes.
    run_id : str
        Optimization run identifier to load.
    scenario_name : str, optional
        Scenario name filter. When provided, only a matching run is loaded.
    case_name : str, optional
        Case name filter. When provided, only a matching run is loaded.

    Returns
    -------
    sdom.results.OptimizationResults
        Reconstructed optimization results assembled from typed supplemental
        attributes.

    Raises
    ------
    ValueError
        If ``run_id`` is empty or no matching optimization result exists.

    Examples
    --------
    >>> from sdom.results import OptimizationResults
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> system = load_system("Data/no_exchange_run_of_river")
    >>> _ = add_results_to_system(system, OptimizationResults(total_cost=1.0), run_id="run-1")
    >>> optimization_results_from_system(system, run_id="run-1").total_cost
    1.0
    """
    if not run_id:
        raise ValueError("run_id must be a non-empty string.")

    filters = _ResultFilters(run_id=run_id, scenario_name=scenario_name, case_name=case_name)
    optimization = _single_attribute(system, SDOMOptimizationResult, filters=filters)
    topology = _optional_single_attribute(system, SDOMResultTopologyMetadata, filters=filters)

    results = OptimizationResults(
        termination_condition=optimization.termination_condition,
        solver_status=optimization.solver_status,
        total_cost=optimization.total_cost,
        gen_mix_target=optimization.gen_mix_target,
        is_zonal=bool(topology and topology.is_zonal),
        areas=list(topology.areas) if topology else [],
        lines=[dict(line) for line in topology.lines] if topology else [],
    )

    results.problem_info = _rebuild_problem_info(system, filters=filters)
    _rebuild_capacity_results(system, results, filters=filters)
    _rebuild_generation_totals(system, results, filters=filters)
    _rebuild_cost_results(system, results, filters=filters)
    _rebuild_area_dispatch_results(system, results, filters=filters)
    _rebuild_storage_dispatch_results(system, results, filters=filters)
    _rebuild_thermal_generation_results(system, results, filters=filters)
    _rebuild_installed_capacity_results(system, results, filters=filters)
    _rebuild_summary_results(system, results, filters=filters)
    results.interregional_exchanges_df = _rebuild_interregional_exchanges(system, filters=filters)
    return results


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
    filters = _ResultFilters(run_id=run_id, scenario_name=scenario_name, case_name=case_name)
    return [
        attribute
        for _, attribute in _iter_result_attributes(system, attribute_type, filters=filters)
    ]


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
    >>> _ResultContext("run-1", None, None).kwargs["run_id"]
    'run-1'
    """

    def __init__(self, run_id: str, scenario_name: str | None, case_name: str | None) -> None:
        self.kwargs = {
            "run_id": run_id,
            "scenario_name": scenario_name,
            "case_name": case_name,
        }


class _ResultFilters:
    """Store optional result-query filters.

    Parameters
    ----------
    run_id : str, optional
        Run identifier filter.
    scenario_name : str, optional
        Scenario name filter.
    case_name : str, optional
        Case name filter.

    Examples
    --------
    >>> _ResultFilters(run_id="run-1").matches(SDOMScenarioMetadata(run_id="run-1"))
    True
    """

    def __init__(
        self,
        *,
        run_id: str | None = None,
        scenario_name: str | None = None,
        case_name: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.scenario_name = scenario_name
        self.case_name = case_name

    def matches(self, attribute: SDOMResultAttribute) -> bool:
        """Return whether an attribute matches this filter set.

        Parameters
        ----------
        attribute : SDOMResultAttribute
            Attribute to test.

        Returns
        -------
        bool
            ``True`` when all non-``None`` filters match.

        Examples
        --------
        >>> _ResultFilters(run_id="run-1").matches(SDOMScenarioMetadata(run_id="run-1"))
        True
        """
        if self.run_id is not None and attribute.run_id != self.run_id:
            return False
        if self.scenario_name is not None and attribute.scenario_name != self.scenario_name:
            return False
        return self.case_name is None or attribute.case_name == self.case_name


def _iter_result_attributes(
    system: System,
    attribute_type: type[SDOMResultAttribute],
    *,
    filters: _ResultFilters,
) -> Iterator[tuple[SDOMComponent, SDOMResultAttribute]]:
    """Yield result attributes with their owning component.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    attribute_type : type[SDOMResultAttribute]
        Attribute type to query.
    filters : _ResultFilters
        Run, scenario, and case filters.

    Yields
    ------
    tuple[SDOMComponent, SDOMResultAttribute]
        Owning component and matching attribute.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> list(_iter_result_attributes(load_system("Data/no_exchange_run_of_river"), SDOMScenarioMetadata, filters=_ResultFilters()))
    []
    """
    concrete_types = _RESULT_ATTRIBUTE_TYPES if attribute_type is SDOMResultAttribute else (attribute_type,)
    for component in system.get_components(SDOMComponent):
        for concrete_type in concrete_types:
            for attribute in system.get_supplemental_attributes_with_component(component, concrete_type):
                if filters.matches(attribute):
                    yield component, attribute


def _line_records(lines: Iterable[Any]) -> list[dict[str, str]]:
    """Convert result line metadata to typed topology records.

    Parameters
    ----------
    lines : iterable of Any
        Line metadata from :class:`OptimizationResults`.

    Returns
    -------
    list[dict[str, str]]
        JSON-serializable line metadata records.

    Examples
    --------
    >>> _line_records([{"line_id": "L", "from_area": "A", "to_area": "B"}])
    [{'line_id': 'L', 'from_area': 'A', 'to_area': 'B'}]
    """
    records: list[dict[str, str]] = []
    for line in lines:
        if isinstance(line, Mapping):
            records.append({str(key): str(value) for key, value in line.items()})
        else:
            records.append({"line_id": str(line)})
    return records


def _unique_string(series: pd.Series) -> str | None:
    """Return the unique non-null string value from a Series.

    Parameters
    ----------
    series : pandas.Series
        Series to inspect.

    Returns
    -------
    str | None
        The only non-null string value, or ``None`` when no value exists.

    Raises
    ------
    ValueError
        If multiple distinct values are present.

    Examples
    --------
    >>> _unique_string(pd.Series(["case", "case"]))
    'case'
    """
    values = [str(value) for value in series.dropna().unique()]
    if not values:
        return None
    if len(values) > 1:
        raise ValueError("dispatch Scenario column must contain at most one value per result attribute.")
    return values[0]


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
    if frame.empty or "line_id" not in frame.columns:
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


def _single_attribute(
    system: System,
    attribute_type: type[SDOMResultAttribute],
    *,
    filters: _ResultFilters,
) -> SDOMResultAttribute:
    """Return exactly one matching attribute.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    attribute_type : type[SDOMResultAttribute]
        Attribute type to query.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    SDOMResultAttribute
        Single matching attribute.

    Raises
    ------
    ValueError
        If zero or multiple attributes match.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> _single_attribute(load_system("Data/no_exchange_run_of_river"), SDOMOptimizationResult, filters=_ResultFilters(run_id="missing")) # doctest: +ELLIPSIS
    Traceback (most recent call last):
    ...
    ValueError: No SDOMOptimizationResult found...
    """
    matches = [attribute for _, attribute in _iter_result_attributes(system, attribute_type, filters=filters)]
    if not matches:
        raise ValueError(f"No {attribute_type.__name__} found for run_id={filters.run_id!r}.")
    if len(matches) > 1:
        raise ValueError(f"Multiple {attribute_type.__name__} attributes found for run_id={filters.run_id!r}.")
    return matches[0]


def _optional_single_attribute(
    system: System,
    attribute_type: type[SDOMResultAttribute],
    *,
    filters: _ResultFilters,
) -> SDOMResultAttribute | None:
    """Return zero or one matching attribute.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    attribute_type : type[SDOMResultAttribute]
        Attribute type to query.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    SDOMResultAttribute | None
        Matching attribute or ``None``.

    Raises
    ------
    ValueError
        If multiple attributes match.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> _optional_single_attribute(load_system("Data/no_exchange_run_of_river"), SDOMOptimizationResult, filters=_ResultFilters()) is None
    True
    """
    matches = [attribute for _, attribute in _iter_result_attributes(system, attribute_type, filters=filters)]
    if len(matches) > 1:
        raise ValueError(f"Multiple {attribute_type.__name__} attributes found for run_id={filters.run_id!r}.")
    return matches[0] if matches else None


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


def _optional_float_list(series: pd.Series) -> list[float | None]:
    """Convert a pandas Series to optional Python floats.

    Parameters
    ----------
    series : pandas.Series
        Series containing numeric or missing values.

    Returns
    -------
    list[float | None]
        Values converted to floats, with missing values as ``None``.

    Examples
    --------
    >>> _optional_float_list(pd.Series([1, None]))
    [1.0, None]
    """
    return [_optional_float(value) for value in series.to_numpy(copy=False)]


def _int_list(series: pd.Series) -> list[int]:
    """Convert a numeric pandas Series to Python ints.

    Parameters
    ----------
    series : pandas.Series
        Series containing integer-like values.

    Returns
    -------
    list[int]
        Values converted to Python ints.

    Examples
    --------
    >>> _int_list(pd.Series([1, 2]))
    [1, 2]
    """
    return [int(value) for value in series.to_numpy(copy=False)]


def _optional_float(value: Any) -> float | None:
    """Convert a scalar value to an optional float.

    Parameters
    ----------
    value : Any
        Scalar value.

    Returns
    -------
    float | None
        Float value or ``None`` for missing inputs.

    Examples
    --------
    >>> _optional_float(None) is None
    True
    """
    if value is None or pd.isna(value):
        return None
    return float(value)


def _optional_str(value: Any) -> str | None:
    """Convert a scalar value to an optional string.

    Parameters
    ----------
    value : Any
        Scalar value.

    Returns
    -------
    str | None
        String value or ``None`` for missing inputs.

    Examples
    --------
    >>> _optional_str(None) is None
    True
    """
    if value is None or pd.isna(value):
        return None
    return str(value)


def _json_scalar(value: Any) -> str | int | float | bool | None:
    """Convert scalar values to JSON-compatible scalars.

    Parameters
    ----------
    value : Any
        Scalar value to convert.

    Returns
    -------
    str | int | float | bool | None
        JSON-compatible scalar value.

    Examples
    --------
    >>> _json_scalar(float("nan")) is None
    True
    """
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, str | int | float | bool):
        return value
    return str(value)


__all__ = [
    "DEFAULT_COPPERPLATE_AREA_NAME",
    "add_results_to_system",
    "optimization_results_from_system",
    "query_result_attributes",
]
