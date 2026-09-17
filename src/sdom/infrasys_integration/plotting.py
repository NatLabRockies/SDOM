"""Plotting helpers for SDOM infrasys systems."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any

import pandas as pd
from infrasys import System

from sdom.analytic_tools import (
    plot_area_capacity_stacks,
    plot_area_generation_stacks,
    plot_line_flow_heatmap,
    plot_parametric_results,
    plot_results,
)
from sdom.results import OptimizationResults

from .models import SDOMScenarioMetadata
from .results import optimization_results_from_system, query_result_attributes

LOGGER = logging.getLogger(__name__)
_SUMMARY_COLUMNS = ("Metric", "Technology", "Run", "Optimal Value", "Unit")


@dataclass
class _SystemParametricStudyAdapter:
    """Provide the study attributes required by the parametric plotter."""

    case_metadata: list[dict[str, Any]]
    output_dir: str | None = None


def plot_system_results(
    system: System,
    *,
    run_id: str,
    output_dir: str | PathLike[str],
) -> None:
    """Build standard single-run plots from System result attributes.

    Parameters
    ----------
    system : infrasys.System
        SDOM infrasys system containing typed result supplemental attributes.
    run_id : str
        Result run identifier to reconstruct and plot.
    output_dir : str or os.PathLike
        Parent output directory. Copperplate plots are written to
        ``<output_dir>/plots`` using the same filenames as
        :func:`sdom.analytic_tools.plot_results`. Zonal-only plots are also
        written to that directory with stable filenames.

    Returns
    -------
    None
        Plots are written to disk.

    Raises
    ------
    ValueError
        If ``run_id`` is empty, no matching optimization result exists, or
        required result attributes are inconsistent.

    Examples
    --------
    >>> from sdom import load_data
    >>> from sdom.infrasys_integration.make_system import load_system_from_data
    >>> from sdom.infrasys_integration.results import add_results_to_system
    >>> from sdom.results import OptimizationResults
    >>> system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
    >>> _ = add_results_to_system(system, OptimizationResults(termination_condition="infeasible"), run_id="run-1")
    >>> plot_system_results(system, run_id="run-1", output_dir="unused")
    """
    output_path = Path(output_dir)
    plots_dir = output_path / "plots"
    results = optimization_results_from_system(system, run_id=run_id)
    _ensure_single_plot_summary(results)

    plot_results(results, output_dir=str(output_path))
    if not results.is_optimal:
        return

    if results.is_zonal:
        _plot_zonal_system_results(results, plots_dir=plots_dir)


def plot_system_parametric_results(
    system: System,
    *,
    run_id: str,
    group_by: str | list[str],
    hue_by: str | None = None,
    facet_by: str | None = None,
    output_dir: str | Path,
    max_cases_per_figure: int = 24,
) -> None:
    """Generate parametric sensitivity plots from System-attached results.

    Reconstructs every case associated with ``run_id`` and delegates plot
    rendering, validation, filenames, chunking, and legends to
    :func:`sdom.analytic_tools.plot_parametric_results`.

    Parameters
    ----------
    system : infrasys.System
        SDOM infrasys system containing parametric result attributes.
    run_id : str
        Parametric run identifier to plot.
    group_by : str or list of str
        Stored sweep dimension or dimensions defining comparison groups.
    hue_by : str, optional
        Stored sweep dimension defining bars within each group.
    facet_by : str, optional
        Stored sweep dimension defining separate figures.
    output_dir : str or pathlib.Path
        Root directory for per-case and sensitivity plot outputs.
    max_cases_per_figure : int, default=24
        Maximum group and hue combinations rendered in one comparison figure.

    Returns
    -------
    None
        Plots are written to disk.

    Raises
    ------
    ValueError
        If ``run_id`` is empty, has no attached parametric metadata, contains
        incomplete case metadata without a stored scenario identifier or
        attached scenario name, or references invalid plot dimensions.
    """
    study, results = _system_parametric_plot_data(system, run_id=run_id)
    plot_parametric_results(
        study,
        results,
        group_by,
        hue_by=hue_by,
        facet_by=facet_by,
        output_dir=str(output_dir),
        max_cases_per_figure=max_cases_per_figure,
    )


def _system_parametric_plot_data(
    system: System,
    *,
    run_id: str,
) -> tuple[_SystemParametricStudyAdapter, list[OptimizationResults]]:
    """Rebuild ordered parametric metadata and results from a System.

    Each case is identified by its stored ``scenario_id`` when available, or
    by the attached result attribute's ``scenario_name`` for backward
    compatibility.

    Parameters
    ----------
    system : infrasys.System
        SDOM infrasys system containing parametric result attributes.
    run_id : str
        Parametric run identifier to reconstruct.

    Returns
    -------
    tuple[_SystemParametricStudyAdapter, list[sdom.results.OptimizationResults]]
        Ordered plotting adapter and one reconstructed result per case.

    Raises
    ------
    ValueError
        If ``run_id`` is empty, no metadata is attached, or a case has neither
        a stored scenario identifier nor an attached scenario name.
    """
    if not run_id:
        raise ValueError("run_id must be a non-empty string.")

    attributes = query_result_attributes(
        system,
        run_id=run_id,
        attribute_type=SDOMScenarioMetadata,
    )
    if not attributes:
        raise ValueError(f"No SDOMScenarioMetadata found for run_id={run_id!r}.")

    case_entries: list[tuple[int, dict[str, Any], str]] = []
    for attribute in attributes:
        metadata = attribute.metadata
        scenario_id = metadata.get("scenario_id") or attribute.scenario_name
        if not scenario_id:
            raise ValueError(
                f"Parametric metadata for run_id={run_id!r} has no scenario identifier."
            )

        case_index = int(metadata.get("case_index", 0))
        case_metadata = {
            "case_name": str(metadata.get("case_name") or attribute.case_name or scenario_id),
            "case_index": case_index,
            **dict(metadata.get("sweep_values", {})),
        }
        case_entries.append((case_index, case_metadata, str(scenario_id)))

    case_entries.sort(key=lambda entry: entry[0])
    study = _SystemParametricStudyAdapter(
        case_metadata=[metadata for _, metadata, _ in case_entries],
    )
    results = [
        optimization_results_from_system(system, run_id=run_id, scenario_name=scenario_id)
        for _, _, scenario_id in case_entries
    ]
    return study, results


def _ensure_single_plot_summary(results: OptimizationResults) -> None:
    """Populate summary rows needed by legacy single-run plots.

    Parameters
    ----------
    results : sdom.results.OptimizationResults
        Reconstructed results to update when no usable summary table exists.

    Returns
    -------
    None
        ``results.summary_df`` is left unchanged when already usable, otherwise
        it is populated from capacity and generation aggregate dictionaries.

    Examples
    --------
    >>> from sdom.results import OptimizationResults
    >>> result = OptimizationResults(capacity={"Thermal": 1.0}, generation_totals={"Thermal": 2.0})
    >>> _ensure_single_plot_summary(result)
    >>> result.summary_df["Metric"].tolist()
    ['Capacity', 'Total generation']
    """
    if set(_SUMMARY_COLUMNS).issubset(results.summary_df.columns):
        return

    rows: list[dict[str, object]] = []
    for technology, value in results.capacity.items():
        rows.append(_summary_row("Capacity", technology, value, "MW"))

    storage_capacity = results.storage_capacity if isinstance(results.storage_capacity, dict) else {}
    storage_metrics = {
        "charge": ("Charge power capacity", "MW"),
        "discharge": ("Discharge power capacity", "MW"),
        "energy": ("Energy capacity", "MWh"),
    }
    for capacity_type, (metric, unit) in storage_metrics.items():
        for technology, value in storage_capacity.get(capacity_type, {}).items():
            rows.append(_summary_row(metric, technology, value, unit))

    for technology, value in results.generation_totals.items():
        rows.append(_summary_row("Total generation", technology, value, "MWh"))

    if rows:
        results.summary_df = pd.DataFrame(rows, columns=list(_SUMMARY_COLUMNS))
        return

    LOGGER.warning(
        "plot_system_results: no capacity, storage, or generation totals are "
        "available to build summary_df; initializing empty legacy summary "
        "columns and aggregate single-run plots may be skipped."
    )
    results.summary_df = pd.DataFrame(columns=list(_SUMMARY_COLUMNS))


def _summary_row(metric: str, technology: object, value: object, unit: str) -> dict[str, object]:
    """Build one legacy summary row for single-run plots.

    Parameters
    ----------
    metric : str
        Summary metric name.
    technology : object
        Technology label from an aggregate result dictionary.
    value : object
        Numeric value from an aggregate result dictionary.
    unit : str
        Unit label for the metric.

    Returns
    -------
    dict[str, object]
        Summary row with legacy ``summary_df`` columns.

    Examples
    --------
    >>> _summary_row("Capacity", "Thermal", 1.0, "MW")["Technology"]
    'Thermal'
    """
    return {
        "Metric": metric,
        "Technology": technology,
        "Run": None,
        "Optimal Value": value,
        "Unit": unit,
    }


def _plot_zonal_system_results(results: OptimizationResults, *, plots_dir: Path) -> None:
    """Build zonal-only plots for reconstructed OptimizationResults.

    Parameters
    ----------
    results : sdom.results.OptimizationResults
        Reconstructed zonal results.
    plots_dir : pathlib.Path
        Directory where zonal plot files are written.

    Returns
    -------
    None
        Zonal plots are written to disk.

    Examples
    --------
    >>> from sdom.results import OptimizationResults
    >>> _plot_zonal_system_results(OptimizationResults(is_zonal=False), plots_dir=Path("unused"))
    """
    if not results.is_zonal:
        return

    plot_area_generation_stacks(results, save_path=plots_dir / "area_generation_stacks.png")
    plot_area_capacity_stacks(results, save_path=plots_dir / "area_capacity_stacks.png")

    if results.interregional_exchanges_df.empty:
        LOGGER.warning(
            "plot_system_results: zonal result has no interregional exchange data; "
            "skipping line_flow_heatmap.png."
        )
        return
    plot_line_flow_heatmap(results, save_path=plots_dir / "line_flow_heatmap.png")


__all__ = ["plot_system_parametric_results", "plot_system_results"]
