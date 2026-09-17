"""Public APIs for attaching and rebuilding SDOM optimization results."""

from __future__ import annotations

from typing import Any

from infrasys import System

from sdom.results import OptimizationResults

from .attach import (
    _attach_area_dispatch_results,
    _attach_area_results,
    _attach_capacity_results,
    _attach_cost_results,
    _attach_curtailment_results,
    _attach_generation_totals,
    _attach_installed_plant_results,
    _attach_interregional_exchange_results,
    _attach_problem_info_results,
    _attach_storage_capacity_results,
    _attach_storage_dispatch_results,
    _attach_summary_results,
    _attach_thermal_generation_results,
    _validate_storage_dispatch_owners,
)
from .context import (
    _ResultContext,
    _ResultFilters,
    _iter_result_attributes,
    _line_records,
    _optional_single_attribute,
    _single_attribute,
)
from ..models import (
    SDOMOptimizationResult,
    SDOMResultAttribute,
    SDOMResultTopologyMetadata,
    SDOMScenarioMetadata,
)
from .ownership import _get_scenario_owner
from .rebuild import (
    _rebuild_area_dispatch_results,
    _rebuild_capacity_results,
    _rebuild_cost_results,
    _rebuild_generation_totals,
    _rebuild_installed_capacity_results,
    _rebuild_interregional_exchanges,
    _rebuild_problem_info,
    _rebuild_storage_dispatch_results,
    _rebuild_summary_results,
    _rebuild_thermal_generation_results,
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
    _validate_storage_dispatch_owners(system, results.storage_df)

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
