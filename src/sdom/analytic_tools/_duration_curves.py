"""Duration-curve and marginal-price plotting helpers.

The helpers in this module consume collected result DataFrames only. They do
not alter result collection, solver output, or CSV exports.
"""

from __future__ import annotations

from itertools import cycle
import logging
import os
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ._colors import get_heatmap_cmap
from ._utils import save_figure

if TYPE_CHECKING:
    from ..results import OptimizationResults

logger = logging.getLogger(__name__)

_DURATION_X_LABEL = "Duration-curve position"
_DURATION_CURVE_FONT_SIZE_INCREASE = 2
_DURATION_CURVE_FONT_SIZE = (
    plt.rcParams["font.size"] + _DURATION_CURVE_FONT_SIZE_INCREASE
)
_COLOR_CYCLE = plt.rcParams["axes.prop_cycle"].by_key()["color"]
_LINESTYLE_CYCLE = ("-", "--", ":", "-.")


def _prepare_duration_series(values: pd.Series) -> pd.Series | None:
    """Coerce, sort, and rank a duration-curve series.

    Parameters
    ----------
    values : pandas.Series
        Source values to convert to numeric duration-curve observations.

    Returns
    -------
    pandas.Series or None
        Numeric values sorted descending with a one-based rank index, or
        ``None`` when no numeric values remain.
    """
    numeric_values = pd.to_numeric(values, errors="coerce").dropna()
    if numeric_values.empty:
        return None

    ranked_values = numeric_values.sort_values(ascending=False).reset_index(drop=True)
    ranked_values.index = pd.RangeIndex(1, len(ranked_values) + 1)
    ranked_values.index.name = _DURATION_X_LABEL
    return ranked_values


def _format_duration_curve_axes(ax: plt.Axes, *, y_label: str) -> None:
    """Apply common labels and enlarged typography to a duration-curve axis."""
    ax.set_xlabel(_DURATION_X_LABEL, fontsize=_DURATION_CURVE_FONT_SIZE)
    ax.set_ylabel(y_label, fontsize=_DURATION_CURVE_FONT_SIZE)
    ax.tick_params(axis="both", labelsize=_DURATION_CURVE_FONT_SIZE)


def _plot_duration_curve(
    series: pd.Series,
    *,
    title: str,
    y_label: str,
    output_path: str,
) -> None:
    """Save one duration-curve figure from a prepared series."""
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.plot(series.index, series.values, linewidth=2)
    _format_duration_curve_axes(ax, y_label=y_label)
    ax.set_title(title)
    ax.grid(alpha=0.25)
    save_figure(fig, output_path)


def _plot_grouped_duration_curves(
    data: pd.DataFrame,
    *,
    group_column: str,
    value_column: str,
    title: str,
    y_label: str,
    output_path: str,
) -> bool:
    """Save independently ranked duration curves for each group in *data*."""
    if group_column not in data or value_column not in data:
        logger.warning(
            "duration curves: missing '%s' or '%s'; skipping '%s'.",
            group_column,
            value_column,
            os.path.basename(output_path),
        )
        return False

    fig, ax = plt.subplots(figsize=(12, 7))
    color_values = cycle(_COLOR_CYCLE)
    linestyle_values = cycle(_LINESTYLE_CYCLE)
    plotted = False
    for group_name, group_data in data.groupby(group_column, sort=True):
        series = _prepare_duration_series(group_data[value_column])
        if series is None:
            logger.warning(
                "duration curves: no numeric values for '%s' group '%s'; skipping group.",
                value_column,
                group_name,
            )
            continue
        ax.plot(
            series.index,
            series.values,
            label=str(group_name),
            color=next(color_values),
            linestyle=next(linestyle_values),
            linewidth=2,
        )
        plotted = True

    if not plotted:
        plt.close(fig)
        logger.warning(
            "duration curves: no numeric '%s' data; skipping '%s'.",
            value_column,
            os.path.basename(output_path),
        )
        return False

    _format_duration_curve_axes(ax, y_label=y_label)
    ax.set_title(title)
    ax.grid(alpha=0.25)
    ax.legend(title=group_column)
    save_figure(fig, output_path)
    return True


def _plot_generation_duration_curve(
    generation_df: pd.DataFrame,
    *,
    column: str,
    title: str,
    filename: str,
    plots_dir: str,
) -> bool:
    """Extract and save one generation-frame duration curve when valid."""
    if column not in generation_df:
        logger.warning("duration curves: '%s' is unavailable; skipping '%s'.", column, filename)
        return False

    series = _prepare_duration_series(generation_df[column])
    if series is None:
        logger.warning("duration curves: '%s' has no numeric data; skipping '%s'.", column, filename)
        return False

    _plot_duration_curve(
        series,
        title=title,
        y_label="MW",
        output_path=os.path.join(plots_dir, filename),
    )
    return True


def _available_prices(price_df: pd.DataFrame, *, area_id: str | None = None) -> pd.DataFrame:
    """Return available numeric price rows, optionally for one area."""
    required_columns = {"area_id", "pricing_status", "marginal_price_USD_per_MWh"}
    if not required_columns <= set(price_df.columns):
        return pd.DataFrame()

    prices = price_df.loc[price_df["pricing_status"] == "available"].copy()
    if area_id is not None:
        prices = prices.loc[prices["area_id"] == area_id]
    prices["marginal_price_USD_per_MWh"] = pd.to_numeric(
        prices["marginal_price_USD_per_MWh"], errors="coerce"
    )
    return prices.dropna(subset=["marginal_price_USD_per_MWh"])


def _plot_marginal_price_heatmap(prices: pd.DataFrame, *, output_path: str) -> bool:
    """Save a copperplate marginal-price heatmap using actual numeric hours."""
    hour_column = next((column for column in ("hour", "Hour") if column in prices), None)
    if hour_column is None:
        logger.warning("duration curves: marginal prices have no hour field; skipping heatmap.")
        return False

    hourly_prices = prices[[hour_column, "marginal_price_USD_per_MWh"]].copy()
    hourly_prices[hour_column] = pd.to_numeric(hourly_prices[hour_column], errors="coerce")
    hourly_prices = hourly_prices.dropna().sort_values(hour_column)
    if hourly_prices.empty:
        logger.warning("duration curves: marginal prices have no numeric hours; skipping heatmap.")
        return False

    hourly_prices = hourly_prices.groupby(hour_column, as_index=False).mean(numeric_only=True)
    last_complete_hour = int(hourly_prices[hour_column].max() // 24) * 24
    if last_complete_hour == 0:
        logger.warning(
            "duration curves: fewer than 24 priced hours available; skipping marginal-price heatmap."
        )
        return False

    hourly_prices = hourly_prices.loc[hourly_prices[hour_column].between(1, last_complete_hour)]
    n_days = last_complete_hour // 24
    grid = np.full((24, n_days), np.nan)
    for hour, price in hourly_prices.itertuples(index=False):
        hour_index = int(hour) - 1
        grid[hour_index % 24, hour_index // 24] = price

    fig, ax = plt.subplots(figsize=(12, 10))
    heatmap = ax.pcolormesh(np.arange(n_days + 1), np.arange(25), grid, cmap=get_heatmap_cmap())
    colorbar = fig.colorbar(heatmap, ax=ax)
    colorbar.set_label("Marginal price (USD/MWh)")
    ax.set_xlabel("Day of the year")
    ax.set_ylabel("Hour of the day")
    ax.set_title("Marginal price (USD/MWh)")
    save_figure(fig, output_path)
    return True


def _plot_copperplate_duration_curves(
    result: "OptimizationResults",
    *,
    generation_df: pd.DataFrame,
    plots_dir: str,
) -> None:
    """Save copperplate duration curves and optional marginal-price figures."""
    if generation_df.empty:
        logger.warning("duration curves: generation data are empty; skipping generation curves.")
    else:
        _plot_generation_duration_curve(
            generation_df,
            column="All Thermal Generation (MW)",
            title="Total thermal generation duration curve",
            filename="duration_curve_total_thermal_generation.png",
            plots_dir=plots_dir,
        )
        _plot_generation_duration_curve(
            generation_df,
            column="Load (MW)",
            title="Load duration curve",
            filename="duration_curve_load.png",
            plots_dir=plots_dir,
        )
        _plot_generation_duration_curve(
            generation_df,
            column="Net Load (MW)",
            title="Net load duration curve",
            filename="duration_curve_net_load.png",
            plots_dir=plots_dir,
        )
        for column, title, filename in (
            ("Imports (MW)", "Imports duration curve", "duration_curve_imports.png"),
            ("Exports (MW)", "Exports duration curve", "duration_curve_exports.png"),
        ):
            _plot_generation_duration_curve(
                generation_df,
                column=column,
                title=title,
                filename=filename,
                plots_dir=plots_dir,
            )

    prices = _available_prices(getattr(result, "marginal_prices_df", pd.DataFrame()), area_id="copperplate")
    price_series = (
        _prepare_duration_series(prices["marginal_price_USD_per_MWh"])
        if not prices.empty
        else None
    )
    if price_series is None:
        logger.warning("duration curves: copperplate marginal prices are unavailable; skipping price figures.")
        return

    _plot_duration_curve(
        price_series,
        title="Marginal price duration curve",
        y_label="USD/MWh",
        output_path=os.path.join(plots_dir, "duration_curve_marginal_price.png"),
    )
    _plot_marginal_price_heatmap(
        prices, output_path=os.path.join(plots_dir, "heatmap_marginal_price.png")
    )


def _plot_zonal_duration_curves(
    result: "OptimizationResults",
    *,
    generation_df: pd.DataFrame,
    plots_dir: str,
) -> None:
    """Save system and grouped zonal duration curves."""
    if generation_df.empty:
        logger.warning("duration curves: generation data are empty; skipping generation curves.")
    else:
        _plot_generation_duration_curve(
            generation_df,
            column="All Thermal Generation (MW)",
            title="System total thermal generation duration curve",
            filename="duration_curve_system_total_thermal_generation.png",
            plots_dir=plots_dir,
        )
        _plot_generation_duration_curve(
            generation_df,
            column="Load (MW)",
            title="System load duration curve",
            filename="duration_curve_system_load.png",
            plots_dir=plots_dir,
        )
        _plot_generation_duration_curve(
            generation_df,
            column="Net Load (MW)",
            title="System net load duration curve",
            filename="duration_curve_system_net_load.png",
            plots_dir=plots_dir,
        )
    _plot_grouped_duration_curves(
        getattr(result, "interregional_exchanges_df", pd.DataFrame()),
        group_column="line_id",
        value_column="flow_signed_MW",
        title="Interregional signed flows duration curve",
        y_label="MW",
        output_path=os.path.join(plots_dir, "duration_curve_interregional_signed_flows.png"),
    )
    _plot_grouped_duration_curves(
        _available_prices(getattr(result, "marginal_prices_df", pd.DataFrame())),
        group_column="area_id",
        value_column="marginal_price_USD_per_MWh",
        title="Zonal marginal prices duration curve",
        y_label="USD/MWh",
        output_path=os.path.join(plots_dir, "duration_curve_zonal_marginal_prices.png"),
    )


def plot_duration_curves(
    result: "OptimizationResults",
    *,
    generation_df: pd.DataFrame,
    plots_dir: str,
) -> None:
    """Generate duration curves for a single optimal result.

    Parameters
    ----------
    result : OptimizationResults
        Collected SDOM results containing optional price and zonal-flow data.
    generation_df : pandas.DataFrame
        System-level hourly generation data used for generation duration curves.
    plots_dir : str
        Destination directory for figure files.
    """
    if getattr(result, "is_zonal", False):
        _plot_zonal_duration_curves(result, generation_df=generation_df, plots_dir=plots_dir)
    else:
        _plot_copperplate_duration_curves(result, generation_df=generation_df, plots_dir=plots_dir)