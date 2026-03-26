"""Single-simulation plotting functions for SDOM analytic_tools.

Public API
----------
plot_results(result, output_dir=None, plots_dir=None)
    Generate all standard plots for one OptimizationResults and save them to
    disk.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ._colors import (
    get_heatmap_cmap,
    get_technology_color_map,
    infer_storage_technologies,
)
from ._utils import save_figure

if TYPE_CHECKING:
    from ..results import OptimizationResults

logger = logging.getLogger(__name__)

__all__ = ["plot_results"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SKIP_GEN_COLS = {"Scenario", "Hour"}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def plot_results(
    result: "OptimizationResults",
    output_dir: Optional[str] = None,
    plots_dir: Optional[str] = None,
) -> None:
    """Generate and save all standard plots for a single SDOM optimization run.

    Figures saved
    -------------
    - ``capacity_donut.png``       — installed capacity by technology (donut)
    - ``capacity_generation_donuts.png`` — side-by-side capacity + generation donuts
    - ``heatmap_{col}.png``        — hourly dispatch heatmaps for all generation
      columns in the generation DataFrame

    Parameters
    ----------
    result:
        An :class:`~sdom.results.OptimizationResults` instance returned by
        :func:`~sdom.run_solver`.
    output_dir:
        Parent directory that already contains (or will contain) the simulation
        output files. Plots will be saved to ``<output_dir>/plots/``.
        Ignored when *plots_dir* is provided.
    plots_dir:
        Explicit directory where plots are saved.  Takes priority over
        *output_dir*.

    Raises
    ------
    Warning
        If neither *output_dir* nor *plots_dir* is provided, or if the result
        is not optimal.
    """
    if not result.is_optimal:
        logger.warning(
            "plot_results: result is not optimal (termination_condition=%r). "
            "Skipping plots.",
            result.termination_condition,
        )
        return

    resolved_plots_dir = _resolve_plots_dir(output_dir, plots_dir)

    _plot_capacity_donut(result.summary_df, resolved_plots_dir)
    _plot_capacity_generation_donuts(result.summary_df, resolved_plots_dir)
    _plot_heatmaps(result.generation_df, resolved_plots_dir)

    logger.info("plot_results: all plots saved to '%s'.", resolved_plots_dir)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_plots_dir(
    output_dir: Optional[str],
    plots_dir: Optional[str],
) -> str:
    if plots_dir is not None:
        return plots_dir
    if output_dir is not None:
        return os.path.join(output_dir, "plots")
    raise ValueError(
        "plot_results requires either 'output_dir' or 'plots_dir' to be provided."
    )


def _build_capacity_df(summary_df: pd.DataFrame) -> pd.DataFrame:
    """Extract combined generation + storage capacity from summary_df.

    Returns a DataFrame with columns ['Technology', 'Optimal Value'] where
    'Optimal Value' is in MW (numeric), containing only rows with value > 0.
    """
    # Generation capacity
    cap = summary_df[
        (summary_df["Metric"] == "Capacity") & (summary_df["Technology"] != "All")
    ][["Technology", "Optimal Value"]].copy()
    cap["Optimal Value"] = pd.to_numeric(cap["Optimal Value"], errors="coerce").fillna(0.0)

    # Storage capacity: prefer "Charge power capacity", fall back to "Average power capacity"
    for metric in ("Charge power capacity", "Average power capacity"):
        sto = summary_df[
            (summary_df["Metric"] == metric) & (summary_df["Technology"] != "All")
        ][["Technology", "Optimal Value"]].copy()
        if not sto.empty:
            sto["Optimal Value"] = pd.to_numeric(sto["Optimal Value"], errors="coerce").fillna(0.0)
            cap = pd.concat([cap, sto], ignore_index=True)
            break

    cap["Optimal Value"] = cap["Optimal Value"].clip(lower=0.0)
    return cap[cap["Optimal Value"] > 0].reset_index(drop=True)


def _build_generation_df(summary_df: pd.DataFrame) -> pd.DataFrame:
    """Extract total generation by technology from summary_df (MWh, >0 only)."""
    gen = summary_df[
        (summary_df["Metric"] == "Total generation") & (summary_df["Technology"] != "All")
    ][["Technology", "Optimal Value"]].copy()
    gen["Optimal Value"] = pd.to_numeric(gen["Optimal Value"], errors="coerce").fillna(0.0)
    gen["Optimal Value"] = gen["Optimal Value"].clip(lower=0.0)
    return gen[gen["Optimal Value"] > 0].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Capacity donut
# ---------------------------------------------------------------------------


def _plot_capacity_donut(
    summary_df: pd.DataFrame,
    plots_dir: str,
) -> None:
    """Save ``capacity_donut.png`` to *plots_dir*."""
    cap_df = _build_capacity_df(summary_df)
    if cap_df.empty:
        logger.warning("_plot_capacity_donut: no capacity data found, skipping.")
        return

    storage_techs = infer_storage_technologies(cap_df["Technology"].tolist())
    color_map = get_technology_color_map(storage_techs=storage_techs)
    colors = [color_map.get(t, "#CCCCCC") for t in cap_df["Technology"]]
    total_gw = round(cap_df["Optimal Value"].sum() / 1000)

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.pie(
        cap_df["Optimal Value"],
        startangle=90,
        colors=colors,
        autopct="%1.1f%%",
        pctdistance=0.8,
        textprops={"fontsize": 20, "fontweight": "bold", "color": "black"},
    )

    centre_circle = plt.Circle((0, 0), 0.60, fc="white")
    ax.add_artist(centre_circle)
    ax.axis("equal")

    plt.title("Capacity per technology (MW)", y=0.95, fontsize=28)
    plt.legend(
        cap_df["Technology"],
        bbox_to_anchor=(1.15, 0.9),
        loc="upper right",
        frameon=False,
        fontsize=20,
        labelcolor="black",
    )

    ax.text(0, 0.1, f"{total_gw}GW", ha="center", va="center",
            fontsize=32, fontweight="bold", color="black")
    ax.text(0, -0.1, "Total Capacity", ha="center", va="center",
            fontsize=30, fontweight="bold", color="black")

    plt.tight_layout()
    save_figure(fig, os.path.join(plots_dir, "capacity_donut.png"))


# ---------------------------------------------------------------------------
# Side-by-side capacity + generation donuts
# ---------------------------------------------------------------------------


def _plot_capacity_generation_donuts(
    summary_df: pd.DataFrame,
    plots_dir: str,
) -> None:
    """Save ``capacity_generation_donuts.png`` to *plots_dir*."""
    cap_df = _build_capacity_df(summary_df)
    gen_df = _build_generation_df(summary_df)

    if cap_df.empty and gen_df.empty:
        logger.warning(
            "_plot_capacity_generation_donuts: no data found, skipping."
        )
        return

    all_techs = sorted(
        set(cap_df["Technology"].tolist()) | set(gen_df["Technology"].tolist())
    )
    storage_techs = infer_storage_technologies(all_techs)
    color_map = get_technology_color_map(storage_techs=storage_techs)

    cap_colors = [color_map.get(t, "#CCCCCC") for t in cap_df["Technology"]]
    gen_colors = [color_map.get(t, "#CCCCCC") for t in gen_df["Technology"]]

    fig, axes = plt.subplots(1, 2, figsize=(16, 8))

    # --- Capacity donut ---
    if not cap_df.empty:
        axes[0].pie(
            cap_df["Optimal Value"],
            startangle=90,
            colors=cap_colors,
            autopct="%1.1f%%",
            pctdistance=0.8,
            textprops={"fontsize": 12, "fontweight": "bold", "color": "black"},
        )
        axes[0].add_artist(plt.Circle((0, 0), 0.60, fc="white"))
        axes[0].axis("equal")
        axes[0].set_title("Capacity per technology (MW)", y=0.95, fontsize=16)
        total_cap_gw = round(cap_df["Optimal Value"].sum() / 1000)
        axes[0].text(0, 0.1, f"{total_cap_gw}GW", ha="center", va="center",
                     fontsize=20, fontweight="bold", color="black")
        axes[0].text(0, -0.1, "Total Capacity", ha="center", va="center",
                     fontsize=18, fontweight="bold", color="black")

    # --- Generation donut ---
    if not gen_df.empty:
        axes[1].pie(
            gen_df["Optimal Value"],
            startangle=90,
            colors=gen_colors,
            autopct="%1.1f%%",
            pctdistance=0.8,
            textprops={"fontsize": 12, "fontweight": "bold", "color": "black"},
        )
        axes[1].add_artist(plt.Circle((0, 0), 0.60, fc="white"))
        axes[1].axis("equal")
        axes[1].set_title("Generation per technology (TWh)", y=0.95, fontsize=16)
        total_gen_twh = round(gen_df["Optimal Value"].sum() / 1e6)
        axes[1].text(0, 0.1, f"{total_gen_twh}TWh", ha="center", va="center",
                     fontsize=20, fontweight="bold", color="black")
        axes[1].text(0, -0.1, "Total Generation", ha="center", va="center",
                     fontsize=18, fontweight="bold", color="black")

    # Shared legend
    legend_techs = list(
        dict.fromkeys(cap_df["Technology"].tolist() + gen_df["Technology"].tolist())
    )
    legend_colors = [color_map.get(t, "#CCCCCC") for t in legend_techs]
    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=c) for c in legend_colors]
    fig.legend(handles, legend_techs, loc="center right", frameon=False, fontsize=12)

    plt.tight_layout(rect=[0, 0, 0.85, 1])
    save_figure(fig, os.path.join(plots_dir, "capacity_generation_donuts.png"))


# ---------------------------------------------------------------------------
# Hourly dispatch heatmaps
# ---------------------------------------------------------------------------


def _make_vre_df(generation_df: pd.DataFrame) -> pd.DataFrame:
    """Combine Solar PV and Wind columns into aggregated VRE columns.

    Returns a copy of *generation_df* where the individual Solar PV and Wind
    generation/curtailment columns are replaced by:
    - ``VRE Generation (MW)``
    - ``VRE Curtailment (MW)``
    """
    df = generation_df.copy()
    pv_gen = "Solar PV Generation (MW)"
    wind_gen = "Wind Generation (MW)"
    pv_curt = "Solar PV Curtailment (MW)"
    wind_curt = "Wind Curtailment (MW)"

    cols_present = set(df.columns)
    has_pv_gen = pv_gen in cols_present
    has_wind_gen = wind_gen in cols_present
    has_pv_curt = pv_curt in cols_present
    has_wind_curt = wind_curt in cols_present

    if has_pv_gen or has_wind_gen:
        pv_series = df[pv_gen].fillna(0) if has_pv_gen else 0
        wind_series = df[wind_gen].fillna(0) if has_wind_gen else 0
        df["VRE Generation (MW)"] = pv_series + wind_series
        for col in (pv_gen, wind_gen):
            if col in df.columns:
                df = df.drop(columns=[col])

    if has_pv_curt or has_wind_curt:
        pv_series = df[pv_curt].fillna(0) if has_pv_curt else 0
        wind_series = df[wind_curt].fillna(0) if has_wind_curt else 0
        df["VRE Curtailment (MW)"] = pv_series + wind_series
        for col in (pv_curt, wind_curt):
            if col in df.columns:
                df = df.drop(columns=[col])

    return df


def _plot_heatmaps(
    generation_df: pd.DataFrame,
    plots_dir: str,
) -> None:
    """Save one heatmap PNG per dispatch column in *generation_df*."""
    if generation_df.empty:
        logger.warning("_plot_heatmaps: generation_df is empty, skipping.")
        return

    df = _make_vre_df(generation_df)
    cmap = get_heatmap_cmap()
    n_periods = len(df)

    # Heatmaps always have 24-hour rows; truncate to the largest multiple of 24.
    n_usable = (n_periods // 24) * 24
    if n_usable == 0:
        logger.warning(
            "_plot_heatmaps: fewer than 24 periods available (%d). Skipping all heatmaps.",
            n_periods,
        )
        return
    if n_usable < n_periods:
        logger.warning(
            "_plot_heatmaps: %d periods is not a multiple of 24; truncating to %d.",
            n_periods,
            n_usable,
        )
    n_days = n_usable // 24

    plot_cols = [c for c in df.columns if c not in _SKIP_GEN_COLS]

    for col_name in plot_cols:
        series = pd.to_numeric(df[col_name], errors="coerce").fillna(0.0)
        if series.abs().sum() == 0:
            continue  # skip all-zero columns

        reshaped = series.values[:n_usable].reshape(24, n_days, order="F")

        # x-grid: one edge per day boundary (n_days + 1 edges for n_days columns)
        xgrid = np.arange(n_days + 1)
        ygrid = np.arange(25)  # 25 edges for 24 hour rows

        fig, ax = plt.subplots(figsize=(12, 10))
        heatmap = ax.pcolormesh(xgrid, ygrid, reshaped, cmap=cmap)
        ax.xaxis.set_tick_params(labelsize=16)
        ax.yaxis.set_tick_params(labelsize=16)
        ax.set_frame_on(False)
        plt.xlim(0, n_days)
        plt.ylim(0, 24)

        cbar = plt.colorbar(heatmap)
        cbar.ax.tick_params(labelsize=16)

        plt.xlabel("Day of the year", fontsize=20)
        plt.ylabel("Hour of the day", fontsize=20)
        plt.title(col_name, y=1.05, fontsize=20)

        safe_col = col_name.replace("/", "_").replace(" ", "_")
        save_figure(fig, os.path.join(plots_dir, f"heatmap_{safe_col}.png"))
