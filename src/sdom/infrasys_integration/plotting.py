"""Plotting helpers for SDOM infrasys systems."""

from __future__ import annotations

import logging
from os import PathLike
from pathlib import Path

import pandas as pd
from infrasys import System

from sdom.analytic_tools import (
    plot_area_capacity_stacks,
    plot_area_generation_stacks,
    plot_line_flow_heatmap,
    plot_results,
)
from sdom.results import OptimizationResults

from .results import optimization_results_from_system

LOGGER = logging.getLogger(__name__)


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
    required = {"Metric", "Technology", "Run", "Optimal Value", "Unit"}
    if not results.summary_df.empty and required.issubset(results.summary_df.columns):
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
        results.summary_df = pd.DataFrame(rows)


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


__all__ = ["plot_system_results"]
