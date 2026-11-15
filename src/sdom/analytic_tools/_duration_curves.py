"""Duration-curve and marginal-price plotting helpers.

The helpers in this module consume collected result DataFrames only. They do
not alter result collection, solver output, or CSV exports.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import PathCollection
from matplotlib.colors import Normalize

from ._colors import get_heatmap_cmap
from ._utils import save_figure

if TYPE_CHECKING:
    from ..results import OptimizationResults

logger = logging.getLogger(__name__)

_DURATION_X_LABEL = "Duration (%)"
_DURATION_CURVE_FONT_SIZE_INCREASE = 2
_DURATION_CURVE_FONT_SIZE = plt.rcParams["font.size"] + _DURATION_CURVE_FONT_SIZE_INCREASE
_GENERATION_METRICS = (
    ("All Thermal Generation (MW)", "Total thermal generation", "total_thermal_generation", "MW"),
    ("Load (MW)", "Load", "load", "MW"),
    ("Net Load (MW)", "Net load", "net_load", "MW"),
    ("Imports (MW)", "Imports", "imports", "MW"),
    ("Exports (MW)", "Exports", "exports", "MW"),
    ("VRE Curtailment (MW)", "Solar + wind curtailment", "vre_curtailment_mw", "MW"),
    ("VRE Curtailment (%)", "Solar + wind curtailment", "vre_curtailment_pct", "%"),
)


def _prepare_duration_series(values: pd.Series, hours: pd.Series) -> pd.DataFrame | None:
    """Validate and sort paired values and original hours descending.

    Parameters
    ----------
    values : pandas.Series
        Source values to convert to numeric duration-curve observations.
    hours : pandas.Series
        Corresponding stored one-based SDOM hours, in the same row order.

    Returns
    -------
    pandas.DataFrame or None
        Aligned ``value``, hour-of-day ``hour``, and percentage ``position``
        columns, or ``None`` when no valid observations remain.
    """
    observations = pd.DataFrame(
        {
            "value": pd.to_numeric(values, errors="coerce").to_numpy(),
            "hour": pd.to_numeric(hours, errors="coerce").to_numpy(),
        }
    )
    valid = (
        np.isfinite(observations).all(axis=1) & (observations["hour"] >= 1) & (observations["hour"] % 1 == 0)
    )
    if not valid.all():
        logger.warning("duration curves: discarding %d invalid value/hour observations.", (~valid).sum())
    observations = observations.loc[valid].sort_values("value", ascending=False, kind="stable")
    if observations.empty:
        return None

    observations["hour"] = (observations["hour"] - 1) % 24
    observations["position"] = np.linspace(0, 100, len(observations))
    return observations.reset_index(drop=True)


def _prepare_frame_series(data: pd.DataFrame, *, column: str) -> pd.DataFrame | None:
    """Prepare paired observations from a result frame with either hour spelling."""
    hour_column = next((name for name in ("Hour", "hour") if name in data), None)
    if column not in data or hour_column is None:
        logger.warning("duration curves: '%s' or its hour field is unavailable; skipping curve.", column)
        return None
    series = _prepare_duration_series(data[column], data[hour_column])
    if series is None:
        logger.warning("duration curves: '%s' has no numeric value/hour data; skipping curve.", column)
    return series


def _format_duration_curve_axes(ax: plt.Axes, *, y_label: str) -> None:
    """Apply common labels and enlarged typography to a duration-curve axis."""
    ax.set_xlabel(_DURATION_X_LABEL, fontsize=_DURATION_CURVE_FONT_SIZE)
    ax.set_ylabel(y_label, fontsize=_DURATION_CURVE_FONT_SIZE)
    ax.tick_params(axis="both", labelsize=_DURATION_CURVE_FONT_SIZE)


def _render_duration_axis(
    ax: plt.Axes,
    series: pd.DataFrame,
    *,
    title: str,
    y_label: str,
    norm: Normalize,
) -> PathCollection:
    """Render hourly scatter observations and interpolated duration references."""
    scatter = ax.scatter(
        series["position"],
        series["value"],
        c=series["hour"],
        cmap="jet",
        norm=norm,
        s=18,
        alpha=0.8,
    )
    for position, marker in ((5, "D"), (50, "s"), (95, "^")):
        value = np.interp(position, series["position"], series["value"])
        ax.scatter(
            [position],
            [value],
            marker=marker,
            s=90,
            facecolor="white",
            edgecolor="black",
            zorder=3,
            label=f"{position}%: {value:.2f} {y_label}",
        )
    _format_duration_curve_axes(ax, y_label=y_label)
    ax.set_xlim(0, 100)
    ax.set_title(title)
    ax.grid(alpha=0.25)
    ax.legend(loc="best", fontsize=_DURATION_CURVE_FONT_SIZE)
    return scatter


def _add_hour_colorbar(fig: plt.Figure, scatter: PathCollection, *, axes: list[plt.Axes]) -> None:
    """Add one fixed 00-23 hour-of-day colorbar for all figure panels."""
    ticks = [0, 6, 12, 18, 23]
    colorbar = fig.colorbar(scatter, ax=axes, ticks=ticks)
    colorbar.set_label("Hour of day", fontsize=_DURATION_CURVE_FONT_SIZE)
    colorbar.set_ticklabels([f"{hour:02d}" for hour in ticks])


def _plot_duration_curve(
    series: pd.DataFrame,
    *,
    title: str,
    y_label: str,
    output_path: str,
) -> None:
    """Save one duration-curve figure from a prepared series."""
    fig, ax = plt.subplots(figsize=(12, 7), layout="constrained")
    scatter = _render_duration_axis(ax, series, title=title, y_label=y_label, norm=Normalize(0, 23))
    _add_hour_colorbar(fig, scatter, axes=[ax])
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
    """Save independently sorted group panels with a shared hour colorbar."""
    if group_column not in data or value_column not in data:
        logger.warning(
            "duration curves: missing '%s' or '%s'; skipping '%s'.",
            group_column,
            value_column,
            os.path.basename(output_path),
        )
        return False

    panels = {}
    for group_name, group_data in data.groupby(group_column, sort=True):
        series = _prepare_frame_series(group_data, column=value_column)
        if series is None:
            logger.warning(
                "duration curves: no numeric values for '%s' group '%s'; skipping group.",
                value_column,
                group_name,
            )
            continue
        panels[str(group_name)] = series

    if not panels:
        logger.warning(
            "duration curves: no numeric '%s' data; skipping '%s'.",
            value_column,
            os.path.basename(output_path),
        )
        return False

    n_columns = min(2, len(panels))
    n_rows = (len(panels) + n_columns - 1) // n_columns
    fig, grid = plt.subplots(
        n_rows,
        n_columns,
        figsize=(7 * n_columns + 1, 5 * n_rows),
        squeeze=False,
        layout="constrained",
    )
    axes = list(grid.flat)
    norm = Normalize(0, 23)
    for ax, (name, series) in zip(axes, panels.items(), strict=False):
        scatter = _render_duration_axis(ax, series, title=name, y_label=y_label, norm=norm)
    for ax in axes[len(panels) :]:
        fig.delaxes(ax)
    fig.suptitle(title)
    _add_hour_colorbar(fig, scatter, axes=axes[: len(panels)])
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

    series = _prepare_frame_series(generation_df, column=column)
    if series is None:
        logger.warning("duration curves: '%s' has no numeric data; skipping '%s'.", column, filename)
        return False

    _plot_duration_curve(
        series,
        title=title,
        y_label="%" if column.endswith("(%)") else "MW",
        output_path=os.path.join(plots_dir, filename),
    )
    return True


def _with_curtailment(generation_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate hourly solar-plus-wind curtailment, retaining zero availability."""
    columns = [
        "Solar PV Generation (MW)",
        "Wind Generation (MW)",
        "Solar PV Curtailment (MW)",
        "Wind Curtailment (MW)",
    ]
    if not set(columns) <= set(generation_df):
        logger.warning(
            "duration curves: solar/wind generation or curtailment data unavailable; skipping curtailment."
        )
        return generation_df
    data = generation_df.copy()
    values = data[columns].apply(pd.to_numeric, errors="coerce")
    curtailment = values[columns[2]] + values[columns[3]]
    availability = values[columns[0]] + values[columns[1]] + curtailment
    data["VRE Curtailment (MW)"] = curtailment
    data["VRE Curtailment (%)"] = np.divide(
        100 * curtailment.to_numpy(),
        availability.to_numpy(),
        out=np.zeros(len(data)),
        where=availability.to_numpy() != 0,
    )
    return data


def _plot_generation_metrics(
    generation_df: pd.DataFrame,
    *,
    scope: str,
    plots_dir: str,
) -> None:
    """Save each generation metric for copperplate, system, or zonal scope."""
    if generation_df.empty:
        logger.warning("duration curves: generation data are empty; skipping generation curves.")
        return
    data = _with_curtailment(generation_df)
    prefix = f"{scope}_" if scope else ""
    for column, title, metric, unit in _GENERATION_METRICS:
        filename = f"duration_curve_{prefix}{metric}.png"
        if scope == "zonal":
            _plot_grouped_duration_curves(
                data,
                group_column="Area",
                value_column=column,
                title=f"Zonal {title.lower()} duration curves",
                y_label=unit,
                output_path=os.path.join(plots_dir, filename),
            )
        else:
            _plot_generation_duration_curve(
                data,
                column=column,
                title=f"System {title.lower()} duration curve" if scope else f"{title} duration curve",
                filename=filename,
                plots_dir=plots_dir,
            )


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
    result: OptimizationResults,
    *,
    generation_df: pd.DataFrame,
    plots_dir: str,
) -> None:
    """Save copperplate duration curves and optional marginal-price figures."""
    _plot_generation_metrics(generation_df, scope="", plots_dir=plots_dir)

    prices = _available_prices(getattr(result, "marginal_prices_df", pd.DataFrame()), area_id="copperplate")
    price_series = (
        _prepare_frame_series(prices, column="marginal_price_USD_per_MWh") if not prices.empty else None
    )
    if price_series is None:
        logger.warning(
            "duration curves: copperplate marginal prices are unavailable; skipping price figures."
        )
        return

    _plot_duration_curve(
        price_series,
        title="Marginal price duration curve",
        y_label="USD/MWh",
        output_path=os.path.join(plots_dir, "duration_curve_marginal_price.png"),
    )
    _plot_marginal_price_heatmap(prices, output_path=os.path.join(plots_dir, "heatmap_marginal_price.png"))


def _plot_zonal_duration_curves(
    result: OptimizationResults,
    *,
    generation_df: pd.DataFrame,
    plots_dir: str,
) -> None:
    """Save system and grouped zonal duration curves."""
    _plot_generation_metrics(generation_df, scope="system", plots_dir=plots_dir)
    accessor = getattr(result, "get_generation_dataframe", None)
    zonal_generation = accessor() if callable(accessor) else getattr(result, "generation_df", pd.DataFrame())
    if zonal_generation.empty or "Area" not in zonal_generation:
        logger.warning(
            "duration curves: per-zone generation data unavailable; skipping zonal generation panels."
        )
    else:
        _plot_generation_metrics(zonal_generation, scope="zonal", plots_dir=plots_dir)
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
    result: OptimizationResults,
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

    Notes
    -----
    Scatter colors retain original hour of day, ``(Hour - 1) % 24``, using
    ``jet`` normalized to 00-23. Descending observations span 0-100% duration
    (a single observation is at 0%); reference values at 5%, 50%, and 95%
    are linearly interpolated on that axis. Zonal and line figures use at
    most two columns with one shared colorbar. Solar-plus-wind percentages
    divide hourly curtailment by generation plus curtailment, with zero at
    zero availability; system values use summed hourly quantities.
    """
    if getattr(result, "is_zonal", False):
        _plot_zonal_duration_curves(result, generation_df=generation_df, plots_dir=plots_dir)
    else:
        _plot_copperplate_duration_curves(result, generation_df=generation_df, plots_dir=plots_dir)
