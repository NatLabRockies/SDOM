"""Duration-curve and marginal-price plotting helpers.

The helpers in this module consume collected result DataFrames only. They do
not alter result collection, solver output, or CSV exports.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.cm import ScalarMappable
from matplotlib.collections import PathCollection
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator

from ._colors import HUE_COLORS, get_heatmap_cmap
from ._layout import (
    FONT_SIZE,
    LayoutError,
    LayoutOptions,
    PageLayout,
    PageSize,
    page_dimensions,
    validate_page,
    wrap_text,
)
from ._utils import resolve_areas, save_figure, save_figure_pages

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
    panel: bool = False,
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
    ax.set_xlim(0, 100)
    ax.grid(alpha=0.25)
    if panel:
        ax.tick_params(axis="both", labelsize=FONT_SIZE)
        ax.set_xticks([0, 50, 100])
        ax.yaxis.set_major_locator(MaxNLocator(nbins=3))
        ax.ticklabel_format(axis="y", style="sci", scilimits=(-3, 4), useOffset=False)
        ax.yaxis.get_offset_text().set_fontsize(FONT_SIZE)
        ax.set_title(title, fontsize=FONT_SIZE, pad=8)
    else:
        _format_duration_curve_axes(ax, y_label=y_label)
        ax.set_title(title)
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


@dataclass(frozen=True)
class DurationPanel:
    """Keep group identity and availability separate from numeric observations."""

    name: str
    series: pd.DataFrame | None
    status: str
    stored_count: int


def result_areas(result: OptimizationResults, *, areas: Sequence[str] | None = None) -> list[str]:
    """Resolve area selection from metadata, with observed IDs for legacy results."""
    inventory = list(getattr(result, "areas", ()))
    if not inventory:
        observed: set[str] = set()
        for attribute, column in (("generation_df", "Area"), ("marginal_prices_df", "area_id")):
            frame = getattr(result, attribute, pd.DataFrame())
            if column in frame:
                observed.update(frame[column].dropna().astype(str))
        inventory = sorted(observed)
    else:
        inventory = sorted(inventory)
    return resolve_areas(inventory, areas=areas)


def _prepare_panels(
    data: pd.DataFrame,
    *,
    group_column: str,
    value_column: str,
    groups: Sequence[str] | None = None,
) -> list[DurationPanel]:
    """Prepare groups once, retaining explicit missing and unavailable panels."""
    if groups is None:
        if group_column not in data or value_column not in data:
            logger.warning(
                "duration curves: missing '%s' or '%s'; skipping figure.", group_column, value_column
            )
            return []
        groups = sorted(data[group_column].dropna().unique())
    grouped = (
        {str(name): frame for name, frame in data.groupby(group_column, sort=False)}
        if group_column in data
        else {}
    )
    panels = []
    for name in groups:
        frame = grouped.get(name, pd.DataFrame())
        stored_count = len(frame)
        status = "Missing data"
        if value_column == "marginal_price_USD_per_MWh":
            if "pricing_status" not in frame or not (frame["pricing_status"] == "available").any():
                status = "Prices unavailable"
                frame = frame.iloc[:0]
            else:
                frame = frame.loc[frame["pricing_status"] == "available"]
        series = _prepare_frame_series(frame, column=value_column) if not frame.empty else None
        if series is None:
            logger.warning("duration curves: %s for group %r (%s).", status.lower(), name, value_column)
        panels.append(DurationPanel(name, series, status, stored_count))
    return panels


def _grouped_page(
    panels: list[DurationPanel],
    layout: PageLayout,
    *,
    page_index: int,
    title: str,
    y_label: str,
) -> plt.Figure:
    """Render one bounded page with numeric references outside the data rectangles."""
    fig = plt.figure(figsize=(layout.width, layout.height), dpi=144)
    try:
        fig.suptitle(title, fontsize=18, y=1 - 0.18 / layout.height, va="top")
        fig.text(
            0.5,
            1 - 0.55 / layout.height,
            f"Page {page_index + 1}/{len(layout.pages)} | independent y scales",
            fontsize=FONT_SIZE,
            ha="center",
            va="center",
        )
        norm = Normalize(0, 23)
        for index, panel_index in enumerate(layout.pages[page_index]):
            item = panels[panel_index]
            bounds = layout.bounds(index)
            ax = fig.add_axes(bounds)
            ax.set_gid(item.name)
            wrapped = wrap_text(item.name, figure=fig, width=layout.panel_width)
            if item.series is None:
                ax.set_title(wrapped, fontsize=FONT_SIZE, pad=8)
                ax.set_xlim(0, 100)
                ax.set_xticks([0, 50, 100])
                ax.set_yticks([])
                ax.tick_params(labelsize=FONT_SIZE)
                ax.text(
                    0.5,
                    0.5,
                    item.status,
                    fontsize=FONT_SIZE,
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                )
                continue
            _render_duration_axis(ax, item.series, title=wrapped, y_label=y_label, norm=norm, panel=True)
            labels = []
            references = []
            for position in (5, 50, 95):
                value = np.interp(position, item.series["position"], item.series["value"])
                references.append(value)
                label = f"{value:.2f}"
                labels.append(label if len(label) <= 12 else f"{value:.2e}")
            legend = fig.legend(
                handles=list(ax.collections[1:]),
                labels=labels,
                ncol=3,
                fontsize=FONT_SIZE,
                loc="center",
                bbox_to_anchor=(bounds[0] + bounds[2] / 2, bounds[1] - 0.56 / layout.height),
                frameon=False,
                columnspacing=0.55,
                handlelength=0.9,
                handletextpad=0.3,
                borderpad=0,
            )
            if legend.get_window_extent().width > layout.panel_width * fig.dpi:
                for text, value in zip(legend.get_texts(), references, strict=True):
                    text.set_text(f"{value:.2e}")
            note = "All zero" if (item.series["value"] == 0).all() else ""
            if len(item.series) < item.stored_count:
                note = f"Valid/stored: {len(item.series)}/{item.stored_count}"
            if note:
                ax.text(
                    0.03,
                    0.94,
                    note,
                    fontsize=FONT_SIZE,
                    va="top",
                    transform=ax.transAxes,
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 1},
                )
        fig.text(
            0.10 / layout.width,
            0.53,
            f"Value and references ({y_label})",
            rotation=90,
            fontsize=FONT_SIZE,
            ha="center",
            va="center",
        )
        fig.text(0.5, 1.17 / layout.height, _DURATION_X_LABEL, fontsize=FONT_SIZE, ha="center", va="center")
        keys = [
            Line2D(
                [],
                [],
                color="black",
                marker=marker,
                markerfacecolor="white",
                linestyle="none",
                markersize=8,
                label=f"{position}% duration",
            )
            for position, marker in ((5, "D"), (50, "s"), (95, "^"))
        ]
        fig.legend(
            handles=keys,
            loc="center",
            bbox_to_anchor=(0.5, 0.84 / layout.height),
            fontsize=FONT_SIZE,
            ncol=3,
            frameon=False,
            borderpad=0,
        )
        bar_width = min(4.4, layout.width * 0.4)
        bar_left = (layout.width - bar_width - 1.6) / 2
        bar_ax = fig.add_axes(
            (bar_left / layout.width, 0.34 / layout.height, bar_width / layout.width, 0.12 / layout.height)
        )
        colorbar = fig.colorbar(
            ScalarMappable(norm=norm, cmap="jet"),
            cax=bar_ax,
            orientation="horizontal",
            ticks=[0, 6, 12, 18, 23],
        )
        colorbar.set_ticklabels(["00", "06", "12", "18", "23"])
        colorbar.ax.tick_params(labelsize=FONT_SIZE, length=3)
        fig.text(
            (bar_left + bar_width + 0.15) / layout.width,
            0.4 / layout.height,
            "Hour of day",
            fontsize=FONT_SIZE,
            ha="left",
            va="center",
        )
        validate_page(fig)
        return fig
    finally:
        plt.close(fig)


def _save_grouped_panels(
    panels: list[DurationPanel],
    *,
    title: str,
    y_label: str,
    output_path: str,
    options: LayoutOptions,
) -> None:
    """Reflow measured labels by tightening capacity, without shrinking fonts."""
    capacity = None
    while True:
        layout = options.plan(len(panels), capacity=capacity)
        try:
            save_figure_pages(
                _grouped_figures(panels, layout, title=title, y_label=y_label),
                output_path,
                page_count=len(layout.pages),
            )
            return
        except LayoutError:
            if layout.capacity == 1:
                raise
            capacity = layout.capacity - 1


def _grouped_figures(
    panels: list[DurationPanel], layout: PageLayout, *, title: str, y_label: str
) -> Iterator[plt.Figure]:
    """Render one owned page at a time for bounded working memory."""
    for page_index in range(len(layout.pages)):
        yield _grouped_page(panels, layout, page_index=page_index, title=title, y_label=y_label)


def _plot_grouped_duration_curves(
    data: pd.DataFrame,
    *,
    group_column: str,
    value_column: str,
    title: str,
    y_label: str,
    output_path: str,
    groups: Sequence[str] | None = None,
    options: LayoutOptions | None = None,
) -> bool:
    """Save all group identities on bounded pages with a consistent hour color scale."""
    panels = _prepare_panels(data, group_column=group_column, value_column=value_column, groups=groups)
    if not panels:
        return False
    _save_grouped_panels(
        panels, title=title, y_label=y_label, output_path=output_path, options=options or LayoutOptions()
    )
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
    groups: Sequence[str] | None = None,
    options: LayoutOptions | None = None,
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
                groups=groups,
                options=options,
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


def _plot_price_comparison(
    panels: list[DurationPanel],
    *,
    inventory: Sequence[str],
    options: LayoutOptions,
    output_path: str,
) -> None:
    """Overlay independently sorted prices, using area identity rather than hour colors."""
    if not panels:
        return
    width, height = page_dimensions(options.page_size)
    fig, ax = plt.subplots(figsize=(width, height), dpi=144)
    try:
        styles = ("-", "--", ":", "-.")
        if len(inventory) > len(HUE_COLORS) * len(styles):
            logger.warning(
                "LMP overlay has %d areas; color/style combinations repeat. "
                "Use areas=... or the zonal panels for unambiguous individual comparisons.",
                len(inventory),
            )
        handles = []
        labels = []
        for item in panels:
            index = inventory.index(item.name)
            color = HUE_COLORS[index % len(HUE_COLORS)]
            style = styles[index % len(styles)]
            if item.series is None:
                handles.append(Line2D([], [], color=color, linestyle=style, linewidth=2))
                labels.append(f"{item.name} ({item.status.lower()})")
            else:
                (line,) = ax.plot(
                    item.series["position"],
                    item.series["value"],
                    color=color,
                    linestyle=style,
                    linewidth=2,
                    label=item.name,
                    marker="o" if len(item.series) == 1 else None,
                )
                handles.append(line)
                labels.append(item.name)
        ax.set_xlim(0, 100)
        ax.set_xlabel(_DURATION_X_LABEL, fontsize=FONT_SIZE)
        ax.set_ylabel("USD/MWh", fontsize=FONT_SIZE)
        ax.tick_params(labelsize=FONT_SIZE)
        ax.yaxis.get_offset_text().set_fontsize(FONT_SIZE)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.grid(alpha=0.25)
        fig.suptitle(
            "Marginal-price duration curves - independently sorted",
            fontsize=18,
            y=1 - 0.18 / height,
            va="top",
        )
        if not ax.lines:
            ax.set_yticks([])
            ax.text(
                0.5,
                0.5,
                "Marginal prices unavailable",
                fontsize=FONT_SIZE,
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
        for columns in range(len(panels), 0, -1):
            legend = fig.legend(
                handles=handles,
                labels=labels,
                fontsize=FONT_SIZE,
                ncol=columns,
                loc="lower center",
                bbox_to_anchor=(0.5, 0.02),
                frameon=False,
            )
            fig.canvas.draw()
            box = legend.get_window_extent()
            if box.width / fig.dpi > width - 0.5:
                legend.remove()
                continue
            bottom = box.y1 / fig.dpi + 0.65
            if height - 0.85 - bottom < 1.2:
                legend.remove()
                continue
            y_bounds = ax.yaxis.get_tightbbox()
            left = max(0.85, y_bounds.width / fig.dpi + 0.15 if y_bounds is not None else 0.85)
            ax.set_position(
                (
                    left / width,
                    bottom / height,
                    (width - left - 0.3) / width,
                    (height - 0.85 - bottom) / height,
                )
            )
            validate_page(fig)
            save_figure(fig, output_path, tight=False)
            return
        raise LayoutError(
            "The complete marginal-price overlay legend cannot fit at 14 pt. "
            "Select fewer areas=... or choose a larger page_size; no areas were omitted."
        )
    finally:
        plt.close(fig)


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
    options: LayoutOptions,
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
    _plot_price_comparison(
        [DurationPanel("copperplate", price_series, "", len(prices))],
        inventory=["copperplate"],
        options=options,
        output_path=os.path.join(plots_dir, "duration_curve_system_marginal_prices.png"),
    )


def _plot_zonal_duration_curves(
    result: OptimizationResults,
    *,
    generation_df: pd.DataFrame,
    plots_dir: str,
    areas: Sequence[str],
    options: LayoutOptions,
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
        _plot_generation_metrics(
            zonal_generation, scope="zonal", plots_dir=plots_dir, groups=areas, options=options
        )
    _plot_grouped_duration_curves(
        getattr(result, "interregional_exchanges_df", pd.DataFrame()),
        group_column="line_id",
        value_column="flow_signed_MW",
        title="Interregional signed flows duration curve",
        y_label="MW",
        output_path=os.path.join(plots_dir, "duration_curve_interregional_signed_flows.png"),
        groups=sorted(
            line["line_id"] if isinstance(line, dict) else line for line in getattr(result, "lines", ())
        )
        or None,
        options=options,
    )
    panels = _prepare_panels(
        getattr(result, "marginal_prices_df", pd.DataFrame()),
        group_column="area_id",
        value_column="marginal_price_USD_per_MWh",
        groups=areas,
    )
    if panels:
        _save_grouped_panels(
            panels,
            title="Zonal marginal prices duration curves",
            y_label="USD/MWh",
            options=options,
            output_path=os.path.join(plots_dir, "duration_curve_zonal_marginal_prices.png"),
        )
        _plot_price_comparison(
            panels,
            inventory=result_areas(result),
            options=options,
            output_path=os.path.join(plots_dir, "duration_curve_system_marginal_prices.png"),
        )


def plot_duration_curves(
    result: OptimizationResults,
    *,
    generation_df: pd.DataFrame,
    plots_dir: str,
    areas: Sequence[str] | None = None,
    page_size: PageSize = "slide_16_9",
    max_panels_per_page: int | None = None,
    ncols: int | None = None,
    panel_aspect: float = 2.2,
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
    areas : sequence of str or None, optional
        Ordered zonal subset, including the combined price comparison. None
        includes all zones; full-system aggregates and transmission lines
        remain unchanged. Not applicable to copperplate results.
    page_size : str or tuple of float, optional
        Standard page preset or maximum (width, height) in inches.
    max_panels_per_page : int or None, optional
        Positive upper bound on grouped panels per page; None is automatic.
    ncols : int or None, optional
        Exact grouped column count; None chooses automatically.
    panel_aspect : float, optional
        Preferred data-axis width/height ratio, subordinate to readability.

    Notes
    -----
    Scatter colors retain original hour of day, ``(Hour - 1) % 24``, using
    ``jet`` normalized to 00-23. Descending observations span 0-100% duration
    (a single observation is at 0%); reference values at 5%, 50%, and 95%
    are linearly interpolated on that axis. Zonal and line figures use
    bounded pages, 14 pt text and a shared hour scale. Solar-plus-wind percentages
    divide hourly curtailment by generation plus curtailment, with zero at
    zero availability; system values use summed hourly quantities.
    """
    options = LayoutOptions(page_size, max_panels_per_page, ncols, panel_aspect)
    options.plan(1)
    if getattr(result, "is_zonal", False):
        selected = result_areas(result, areas=areas)
        _plot_zonal_duration_curves(
            result, generation_df=generation_df, plots_dir=plots_dir, areas=selected, options=options
        )
    else:
        if areas is not None:
            raise ValueError("areas is only supported for zonal results; omit it for copperplate results.")
        _plot_copperplate_duration_curves(
            result, generation_df=generation_df, plots_dir=plots_dir, options=options
        )
