"""Parametric-study plotting functions for SDOM analytic_tools.

Public API
----------
plot_parametric_results(study, results, group_by, ...)
    Generate per-case individual plots and cross-case sensitivity comparison
    plots from a completed ParametricStudy run.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Union

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ._colors import (
    HUE_COLORS,
    get_technology_color_map,
    get_technology_order,
    infer_storage_technologies,
)
from ._single import plot_results
from ._utils import ensure_dir, save_figure

if TYPE_CHECKING:
    from ..parametric.study import ParametricStudy
    from ..results import OptimizationResults

logger = logging.getLogger(__name__)

__all__ = ["plot_parametric_results"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FIGURE_SIZE = (18, 8)
_BAR_WIDTH = 0.25
_DPI = 300


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def plot_parametric_results(
    study: "ParametricStudy",
    results: List["OptimizationResults"],
    group_by: Union[str, List[str]],
    hue_by: Optional[str] = None,
    facet_by: Optional[str] = None,
    output_dir: Optional[str] = None,
    max_cases_per_figure: int = 24,
    plot_per_case: bool = True,
) -> None:
    """Generate sensitivity-analysis plots from a completed :class:`~sdom.parametric.study.ParametricStudy` run.

    Per-case plots (capacity donut, generation donut, heatmaps) are saved under
    ``<output_dir>/<case_name>/plots/``.  Cross-case comparison plots are saved
    under ``<output_dir>/sensitivity_plots/``.

    Parameters
    ----------
    study:
        A :class:`~sdom.parametric.study.ParametricStudy` instance after
        :meth:`~sdom.parametric.study.ParametricStudy.run` has been called.
    results:
        List returned by :meth:`~sdom.parametric.study.ParametricStudy.run`.
    group_by:
        Sweep dimension identifier (or list of identifiers) whose values define
        the x-axis clusters in comparison plots.  Use the same name that was
        passed to :meth:`~sdom.parametric.study.ParametricStudy.add_scalar_sweep`,
        :meth:`~sdom.parametric.study.ParametricStudy.add_storage_factor_sweep`, or
        :meth:`~sdom.parametric.study.ParametricStudy.add_ts_sweep`.
    hue_by:
        Sweep dimension identifier for the bars within each cluster.
    facet_by:
        Sweep dimension identifier to use for faceting: one complete figure is
        produced per unique value of this dimension.
    output_dir:
        Root output directory.  Defaults to ``study.output_dir``.
    max_cases_per_figure:
        When the product of ``n_groups × n_hues`` across groups and hues
        exceeds this threshold, the plot is split into multiple figures named
        ``{plot_name}_part{n}.png``.  Default is 24.
    plot_per_case:
        If ``True`` (default), also generate individual single-case plots
        (capacity donut, generation donut, heatmaps) for every optimal case.

    Raises
    ------
    ValueError
        If ``group_by`` references a dimension name that is not present in the
        study metadata, or if no output directory can be determined.
    """
    meta = study.case_metadata
    if not meta:
        raise ValueError(
            "study.case_metadata is empty. "
            "Did you call study.run() before plot_parametric_results()?"
        )

    resolved_output_dir = output_dir or study.output_dir
    if not resolved_output_dir:
        raise ValueError(
            "No output directory available. "
            "Pass 'output_dir' explicitly or set 'output_dir' on the ParametricStudy."
        )

    # Normalise group_by
    if isinstance(group_by, str):
        group_by_list: List[str] = [group_by]
    else:
        group_by_list = list(group_by)

    # Validate dimension names
    available_dims = _available_dims(meta)
    for dim in group_by_list:
        if dim not in available_dims:
            raise ValueError(
                f"group_by='{dim}' not found in study dimensions. "
                f"Available dimensions: {sorted(available_dims)}"
            )
    if hue_by and hue_by not in available_dims:
        raise ValueError(
            f"hue_by='{hue_by}' not found in study dimensions. "
            f"Available dimensions: {sorted(available_dims)}"
        )
    if facet_by and facet_by not in available_dims:
        raise ValueError(
            f"facet_by='{facet_by}' not found in study dimensions. "
            f"Available dimensions: {sorted(available_dims)}"
        )

    # -----------------------------------------------------------------------
    # Build combined records: metadata + extracted plot data
    # -----------------------------------------------------------------------
    tech_records: List[dict] = []      # for stacked bars
    curtail_records: List[dict] = []   # for curtailment bars
    cost_records: List[dict] = []      # for cost comparison bars

    for meta_entry, result in zip(meta, results):
        if not result.is_optimal:
            logger.warning(
                "plot_parametric_results: skipping non-optimal case '%s'.",
                meta_entry["case_name"],
            )
            continue

        group_label = _make_group_label(meta_entry, group_by_list)
        hue_label = str(meta_entry.get(hue_by, "")) if hue_by else "_all_"
        facet_val = str(meta_entry.get(facet_by, "")) if facet_by else None

        common = {
            "case_name": meta_entry["case_name"],
            "group_label": group_label,
            "hue_label": hue_label,
            "facet_val": facet_val,
        }

        # Capacity and generation by technology
        cap_series = _extract_capacity_series(result.summary_df)
        gen_series = _extract_generation_series(result.summary_df)
        all_techs = sorted(set(cap_series) | set(gen_series))
        for tech in all_techs:
            tech_records.append({
                **common,
                "technology": tech,
                "capacity_mw": cap_series.get(tech, 0.0),
                "generation_mwh": gen_series.get(tech, 0.0),
            })

        curt_mwh, curt_pct = _extract_curtailment(result.summary_df)
        curtail_records.append({**common, "curtailment_mwh": curt_mwh, "curtailment_pct": curt_pct})

        # CAPEX and OPEX by technology
        capex_series, opex_series = _extract_cost_series(result.summary_df)
        all_cost_techs = sorted(set(capex_series) | set(opex_series))
        for tech in all_cost_techs:
            cost_records.append({
                **common,
                "technology": tech,
                "capex_usd": capex_series.get(tech, 0.0),
                "opex_usd": opex_series.get(tech, 0.0),
            })

    if not tech_records:
        logger.warning("plot_parametric_results: no optimal cases to plot.")
        return

    tech_df = pd.DataFrame(tech_records)
    curt_df = pd.DataFrame(curtail_records)
    cost_df = pd.DataFrame(cost_records)

    # -----------------------------------------------------------------------
    # Determine groups, hues, facets
    # -----------------------------------------------------------------------
    groups: List[str] = sorted(tech_df["group_label"].unique())
    hues: List[str] = sorted(tech_df["hue_label"].unique())
    facets: List[Optional[str]] = (
        sorted(tech_df["facet_val"].dropna().unique()) if facet_by else [None]
    )

    # -----------------------------------------------------------------------
    # Per-case individual plots
    # -----------------------------------------------------------------------
    if plot_per_case:
        for meta_entry, result in zip(meta, results):
            if not result.is_optimal:
                continue
            case_plots_dir = os.path.join(
                resolved_output_dir, meta_entry["case_name"], "plots"
            )
            plot_results(result, plots_dir=case_plots_dir)

    # -----------------------------------------------------------------------
    # Cross-case sensitivity plots
    # -----------------------------------------------------------------------
    sensitivity_dir = os.path.join(resolved_output_dir, "sensitivity_plots")
    ensure_dir(sensitivity_dir)

    all_techs_in_data = sorted(tech_df["technology"].unique())
    storage_techs = infer_storage_technologies(all_techs_in_data)
    color_map = get_technology_color_map(storage_techs=storage_techs)
    tech_order = [t for t in get_technology_order(storage_techs=storage_techs)
                  if t in all_techs_in_data]

    for facet_val in facets:
        facet_suffix = f"_{facet_by}{facet_val}" if facet_val is not None else ""

        if facet_val is not None:
            mask = tech_df["facet_val"] == facet_val
            t_sub = tech_df[mask]
            c_sub = curt_df[curt_df["facet_val"] == facet_val]
            co_sub = cost_df[cost_df["facet_val"] == facet_val]
        else:
            t_sub = tech_df
            c_sub = curt_df
            co_sub = cost_df

        facet_groups = sorted(t_sub["group_label"].unique())
        facet_hues = sorted(t_sub["hue_label"].unique())

        # Chunk groups if too many
        group_chunks = _split_into_chunks(facet_groups, max_cases_per_figure, len(facet_hues))

        for part_idx, group_chunk in enumerate(group_chunks):
            part_suffix = f"_part{part_idx + 1}" if len(group_chunks) > 1 else ""
            file_stem = f"{{name}}{facet_suffix}{part_suffix}"

            chunk_mask_t = t_sub["group_label"].isin(group_chunk)
            chunk_mask_c = c_sub["group_label"].isin(group_chunk)
            chunk_mask_co = co_sub["group_label"].isin(group_chunk)
            t_chunk = t_sub[chunk_mask_t]
            c_chunk = c_sub[chunk_mask_c]
            co_chunk = co_sub[chunk_mask_co]

            # Capacity comparison
            _plot_grouped_stacked_bars(
                tech_df=t_chunk,
                value_col="capacity_mw",
                groups=group_chunk,
                hues=facet_hues,
                tech_order=tech_order,
                color_map=color_map,
                title="Installed Capacity by Technology — Sensitivity Analysis",
                ylabel="Capacity (GW)",
                unit_divisor=1000.0,
                output_path=os.path.join(
                    sensitivity_dir, file_stem.format(name="capacity_comparison") + ".png"
                ),
            )

            # Generation comparison
            _plot_grouped_stacked_bars(
                tech_df=t_chunk,
                value_col="generation_mwh",
                groups=group_chunk,
                hues=facet_hues,
                tech_order=tech_order,
                color_map=color_map,
                title="Annual Generation by Technology — Sensitivity Analysis",
                ylabel="Generation (TWh)",
                unit_divisor=1e6,
                output_path=os.path.join(
                    sensitivity_dir, file_stem.format(name="generation_comparison") + ".png"
                ),
            )

            # Curtailment — absolute
            if not c_chunk.empty:
                _plot_curtailment_bars(
                    curt_df=c_chunk,
                    value_col="curtailment_mwh",
                    groups=group_chunk,
                    hues=facet_hues,
                    title="VRE Curtailment (Absolute) — Sensitivity Analysis",
                    ylabel="Curtailment (GWh)",
                    unit_divisor=1000.0,
                    output_path=os.path.join(
                        sensitivity_dir, file_stem.format(name="curtailment_absolute") + ".png"
                    ),
                )

                # Curtailment — percentage
                _plot_curtailment_bars(
                    curt_df=c_chunk,
                    value_col="curtailment_pct",
                    groups=group_chunk,
                    hues=facet_hues,
                    title="VRE Curtailment (%) — Sensitivity Analysis",
                    ylabel="Curtailment (%)",
                    unit_divisor=1.0,
                    output_path=os.path.join(
                        sensitivity_dir,
                        file_stem.format(name="curtailment_percentage") + ".png",
                    ),
                )

            # Cost comparison (CAPEX + OPEX)
            if not co_chunk.empty:
                cost_tech_order = [
                    t for t in tech_order if t in co_chunk["technology"].unique()
                ]
                _plot_cost_comparison_bars(
                    cost_df=co_chunk,
                    groups=group_chunk,
                    hues=facet_hues,
                    tech_order=cost_tech_order,
                    color_map=color_map,
                    title="CAPEX and OPEX by Technology — Sensitivity Analysis",
                    ylabel="Cost ($M USD)",
                    unit_divisor=1e6,
                    output_path=os.path.join(
                        sensitivity_dir,
                        file_stem.format(name="cost_comparison") + ".png",
                    ),
                )

    logger.info(
        "plot_parametric_results: cross-case plots saved to '%s'.", sensitivity_dir
    )


# ---------------------------------------------------------------------------
# Internal: metadata helpers
# ---------------------------------------------------------------------------


def _available_dims(meta: List[dict]) -> set:
    """Return the set of sweep dimension keys present in the metadata."""
    skip = {"case_name", "case_index"}
    dims: set = set()
    for entry in meta:
        dims.update(k for k in entry if k not in skip)
    return dims


def _make_group_label(meta_entry: dict, group_by: List[str]) -> str:
    """Build an x-axis tick label from one or more dimension values."""
    parts = [f"{dim}={meta_entry[dim]}" for dim in group_by if dim in meta_entry]
    return "\n".join(parts) if parts else "?"


# ---------------------------------------------------------------------------
# Internal: data extraction from OptimizationResults.summary_df
# ---------------------------------------------------------------------------


def _extract_capacity_series(summary_df: pd.DataFrame) -> Dict[str, float]:
    """Return {technology: capacity_mw} from summary_df."""
    cap = summary_df[
        (summary_df["Metric"] == "Capacity") & (summary_df["Technology"] != "All")
    ][["Technology", "Optimal Value"]].copy()
    cap["Optimal Value"] = pd.to_numeric(cap["Optimal Value"], errors="coerce").fillna(0.0)

    for metric in ("Charge power capacity", "Average power capacity"):
        sto = summary_df[
            (summary_df["Metric"] == metric) & (summary_df["Technology"] != "All")
        ][["Technology", "Optimal Value"]].copy()
        if not sto.empty:
            sto["Optimal Value"] = pd.to_numeric(sto["Optimal Value"], errors="coerce").fillna(0.0)
            cap = pd.concat([cap, sto], ignore_index=True)
            break

    cap["Optimal Value"] = cap["Optimal Value"].clip(lower=0.0)
    return dict(zip(cap["Technology"], cap["Optimal Value"]))


def _extract_generation_series(summary_df: pd.DataFrame) -> Dict[str, float]:
    """Return {technology: generation_mwh} from summary_df."""
    gen = summary_df[
        (summary_df["Metric"] == "Total generation") & (summary_df["Technology"] != "All")
    ][["Technology", "Optimal Value"]].copy()
    gen["Optimal Value"] = pd.to_numeric(gen["Optimal Value"], errors="coerce").fillna(0.0).clip(lower=0.0)
    return dict(zip(gen["Technology"], gen["Optimal Value"]))


def _extract_curtailment(summary_df: pd.DataFrame) -> Tuple[float, float]:
    """Return ``(curtailment_mwh, curtailment_pct)`` from summary_df."""
    def _get_scalar(metric: str) -> float:
        vals = summary_df[
            (summary_df["Metric"] == metric) & (summary_df["Technology"] == "All")
        ]["Optimal Value"].values
        if len(vals) > 0:
            try:
                return float(vals[0])
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    return _get_scalar("Total VRE curtailment"), _get_scalar("VRE curtailment percentage")


def _extract_cost_series(
    summary_df: pd.DataFrame,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Return ``({tech: capex_usd}, {tech: opex_usd})`` from summary_df.

    Generation technologies (Solar PV, Wind, Thermal) use ``Metric == "CAPEX"``.
    Storage technologies use ``Metric == "Total-CAPEX"`` (power + energy combined).
    All technologies use ``Metric == "OPEX"`` (FOM + VOM).
    """
    # CAPEX — generation techs
    capex_gen = summary_df[
        (summary_df["Metric"] == "CAPEX") & (summary_df["Technology"] != "All")
    ][["Technology", "Optimal Value"]].copy()
    capex_gen["Optimal Value"] = (
        pd.to_numeric(capex_gen["Optimal Value"], errors="coerce").fillna(0.0).clip(lower=0.0)
    )

    # CAPEX — storage techs (power + energy combined)
    capex_sto = summary_df[
        (summary_df["Metric"] == "Total-CAPEX") & (summary_df["Technology"] != "All")
    ][["Technology", "Optimal Value"]].copy()
    capex_sto["Optimal Value"] = (
        pd.to_numeric(capex_sto["Optimal Value"], errors="coerce").fillna(0.0).clip(lower=0.0)
    )

    capex_df = pd.concat([capex_gen, capex_sto], ignore_index=True)
    capex_dict: Dict[str, float] = dict(zip(capex_df["Technology"], capex_df["Optimal Value"]))

    # OPEX — all techs (FOM + VOM)
    opex = summary_df[
        (summary_df["Metric"] == "OPEX") & (summary_df["Technology"] != "All")
    ][["Technology", "Optimal Value"]].copy()
    opex["Optimal Value"] = (
        pd.to_numeric(opex["Optimal Value"], errors="coerce").fillna(0.0).clip(lower=0.0)
    )
    opex_dict: Dict[str, float] = dict(zip(opex["Technology"], opex["Optimal Value"]))

    return capex_dict, opex_dict


# ---------------------------------------------------------------------------
# Internal: figure chunking
# ---------------------------------------------------------------------------


def _split_into_chunks(
    groups: List[str], max_cases_per_figure: int, n_hues: int
) -> List[List[str]]:
    """Split *groups* into chunks so that ``len(chunk) × n_hues ≤ max_cases_per_figure``.

    If ``n_hues == 0`` it is treated as 1 to avoid division by zero.
    """
    n_hues = max(n_hues, 1)
    max_groups_per_chunk = max(1, max_cases_per_figure // n_hues)
    if len(groups) <= max_groups_per_chunk:
        return [list(groups)]

    logger.warning(
        "_split_into_chunks: %d groups × %d hues = %d bars exceeds "
        "max_cases_per_figure=%d. Splitting into multiple figures.",
        len(groups), n_hues, len(groups) * n_hues, max_cases_per_figure,
    )
    return [
        groups[i: i + max_groups_per_chunk]
        for i in range(0, len(groups), max_groups_per_chunk)
    ]


# ---------------------------------------------------------------------------
# Internal: grouped stacked bar plot (capacity / generation)
# ---------------------------------------------------------------------------


def _plot_grouped_stacked_bars(
    tech_df: pd.DataFrame,
    value_col: str,
    groups: List[str],
    hues: List[str],
    tech_order: List[str],
    color_map: dict,
    title: str,
    ylabel: str,
    unit_divisor: float,
    output_path: str,
) -> None:
    """Grouped stacked bar chart for capacity or generation.

    Parameters
    ----------
    tech_df:
        Long-form DataFrame with columns
        ``group_label``, ``hue_label``, ``technology``, ``{value_col}``.
    value_col:
        Column name of the numeric value (``"capacity_mw"`` or ``"generation_mwh"``).
    groups:
        Ordered list of group labels (x-axis clusters).
    hues:
        Ordered list of hue labels (bars within each cluster).
    tech_order:
        Ordered list of technology names for stacking (bottom → top).
    color_map:
        Technology → color mapping.
    title, ylabel:
        Plot labels.
    unit_divisor:
        Divide values by this factor before plotting (e.g. 1000 for MW → GW).
    output_path:
        Full path to save the PNG.
    """
    n_groups = len(groups)
    n_hues = len(hues)
    bar_width = min(_BAR_WIDTH, 0.8 / max(n_hues, 1))
    bar_offset = bar_width * (n_hues - 1) / 2

    fig, ax = plt.subplots(figsize=_FIGURE_SIZE)
    group_positions = np.arange(n_groups)

    for h_idx, hue in enumerate(hues):
        x_positions = group_positions - bar_offset + h_idx * bar_width
        bottoms = np.zeros(n_groups)

        hue_data = tech_df[tech_df["hue_label"] == hue]

        for tech in tech_order:
            heights = []
            for g_idx, grp in enumerate(groups):
                cell = hue_data[
                    (hue_data["group_label"] == grp) & (hue_data["technology"] == tech)
                ]
                val = float(cell[value_col].values[0]) if not cell.empty else 0.0
                heights.append(val / unit_divisor)

            heights_arr = np.array(heights)
            # Only add label for first hue to avoid duplicate legend entries
            label = tech if h_idx == 0 else None
            ax.bar(
                x_positions,
                heights_arr,
                bar_width,
                bottom=bottoms,
                label=label,
                color=color_map.get(tech, "#CCCCCC"),
                edgecolor="white",
                linewidth=0.5,
            )
            bottoms += heights_arr

    # X-axis
    ax.set_xticks(group_positions)
    ax.set_xticklabels(groups, fontsize=11)

    # Technology legend
    tech_handles = [
        mpatches.Patch(facecolor=color_map.get(t, "#CCCCCC"), label=t)
        for t in tech_order
        if t in tech_df["technology"].unique()
    ]
    tech_legend = ax.legend(
        handles=tech_handles,
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        frameon=False,
        fontsize=10,
        title="Technology",
    )
    ax.add_artist(tech_legend)

    # Hue legend (only when multiple hues)
    if n_hues > 1:
        hue_handles = [
            mpatches.Patch(facecolor="gray", alpha=0.4 + 0.5 * i / max(n_hues - 1, 1), label=h)
            for i, h in enumerate(hues)
        ]
        ax.legend(
            handles=hue_handles,
            loc="upper left",
            bbox_to_anchor=(1.02, 0.5),
            frameon=False,
            fontsize=10,
            title="Scenarios",
        )

    ax.set_xlabel("Case group", fontsize=13, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=13, fontweight="bold")
    ax.set_title(title, fontsize=16, fontweight="bold", pad=20)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)

    plt.tight_layout()
    save_figure(fig, output_path, dpi=_DPI)


# ---------------------------------------------------------------------------
# Internal: curtailment bar plot (non-stacked)
# ---------------------------------------------------------------------------


def _plot_curtailment_bars(
    curt_df: pd.DataFrame,
    value_col: str,
    groups: List[str],
    hues: List[str],
    title: str,
    ylabel: str,
    unit_divisor: float,
    output_path: str,
) -> None:
    """Grouped (non-stacked) bar chart for curtailment values.

    Parameters
    ----------
    curt_df:
        DataFrame with columns ``group_label``, ``hue_label``, ``curtailment_mwh``,
        ``curtailment_pct``.
    value_col:
        ``"curtailment_mwh"`` or ``"curtailment_pct"``.
    groups, hues:
        Ordered lists of group and hue labels.
    title, ylabel:
        Plot labels.
    unit_divisor:
        Divide raw values by this before plotting.
    output_path:
        Full path to save the PNG.
    """
    n_groups = len(groups)
    n_hues = len(hues)
    bar_width = min(_BAR_WIDTH, 0.8 / max(n_hues, 1))
    bar_offset = bar_width * (n_hues - 1) / 2

    fig, ax = plt.subplots(figsize=_FIGURE_SIZE)
    group_positions = np.arange(n_groups)

    for h_idx, hue in enumerate(hues):
        x_positions = group_positions - bar_offset + h_idx * bar_width
        hue_data = curt_df[curt_df["hue_label"] == hue]
        color = HUE_COLORS[h_idx % len(HUE_COLORS)]

        heights = []
        for grp in groups:
            cell = hue_data[hue_data["group_label"] == grp]
            val = float(cell[value_col].values[0]) if not cell.empty else 0.0
            heights.append(val / unit_divisor)

        heights_arr = np.array(heights)
        bars = ax.bar(
            x_positions,
            heights_arr,
            bar_width,
            label=hue,
            color=color,
            edgecolor="white",
            linewidth=0.5,
            alpha=0.85,
        )

        for bar, h in zip(bars, heights_arr):
            if h > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    h,
                    f"{h:.1f}",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                )

    ax.set_xticks(group_positions)
    ax.set_xticklabels(groups, fontsize=11)

    if n_hues > 1:
        ax.legend(
            loc="upper left",
            bbox_to_anchor=(1.02, 1.0),
            frameon=False,
            fontsize=10,
            title="Scenarios",
        )

    ax.set_xlabel("Case group", fontsize=13, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=13, fontweight="bold")
    ax.set_title(title, fontsize=16, fontweight="bold", pad=20)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)

    plt.tight_layout()
    save_figure(fig, output_path, dpi=_DPI)


# ---------------------------------------------------------------------------
# Internal: cost comparison bar plot (CAPEX solid + OPEX hatched)
# ---------------------------------------------------------------------------


def _plot_cost_comparison_bars(
    cost_df: pd.DataFrame,
    groups: List[str],
    hues: List[str],
    tech_order: List[str],
    color_map: dict,
    title: str,
    ylabel: str,
    unit_divisor: float,
    output_path: str,
) -> None:
    """Grouped stacked bar chart showing CAPEX (solid fill) and OPEX (hatched) per technology.

    Each bar is divided into two sections stacked in the same technology order:

    * **Bottom** — CAPEX contributions per technology (solid fill).
    * **Top** — OPEX contributions per technology (same color, hatched ``///``).

    A secondary legend distinguishes CAPEX vs OPEX via solid / hatched grey patches.

    Parameters
    ----------
    cost_df:
        Long-form DataFrame with columns
        ``group_label``, ``hue_label``, ``technology``, ``capex_usd``, ``opex_usd``.
    groups:
        Ordered list of group labels (x-axis clusters).
    hues:
        Ordered list of hue labels (bars within each cluster).
    tech_order:
        Ordered list of technology names for stacking (bottom → top).
    color_map:
        Technology → color mapping.
    title, ylabel:
        Plot labels.
    unit_divisor:
        Divide values by this factor before plotting (e.g. ``1e6`` for $ → $M).
    output_path:
        Full path to save the PNG.
    """
    n_groups = len(groups)
    n_hues = len(hues)
    bar_width = min(_BAR_WIDTH, 0.8 / max(n_hues, 1))
    bar_offset = bar_width * (n_hues - 1) / 2

    fig, ax = plt.subplots(figsize=_FIGURE_SIZE)
    group_positions = np.arange(n_groups)

    for h_idx, hue in enumerate(hues):
        x_positions = group_positions - bar_offset + h_idx * bar_width
        hue_data = cost_df[cost_df["hue_label"] == hue]

        # --- CAPEX stack (solid fill) ---
        capex_bottoms = np.zeros(n_groups)
        for tech in tech_order:
            heights = []
            for grp in groups:
                cell = hue_data[
                    (hue_data["group_label"] == grp) & (hue_data["technology"] == tech)
                ]
                val = float(cell["capex_usd"].values[0]) if not cell.empty else 0.0
                heights.append(val / unit_divisor)
            heights_arr = np.array(heights)
            label = tech if h_idx == 0 else None
            ax.bar(
                x_positions,
                heights_arr,
                bar_width,
                bottom=capex_bottoms,
                label=label,
                color=color_map.get(tech, "#CCCCCC"),
                edgecolor="white",
                linewidth=0.5,
            )
            capex_bottoms += heights_arr

        # --- OPEX stack (hatched), starting from the top of the CAPEX stack ---
        # After the CAPEX loop, capex_bottoms == total CAPEX per group for this hue.
        opex_bottoms = capex_bottoms.copy()
        for tech in tech_order:
            heights = []
            for grp in groups:
                cell = hue_data[
                    (hue_data["group_label"] == grp) & (hue_data["technology"] == tech)
                ]
                val = float(cell["opex_usd"].values[0]) if not cell.empty else 0.0
                heights.append(val / unit_divisor)
            heights_arr = np.array(heights)
            ax.bar(
                x_positions,
                heights_arr,
                bar_width,
                bottom=opex_bottoms,
                color=color_map.get(tech, "#CCCCCC"),
                edgecolor="white",
                linewidth=0.5,
                hatch="///",
            )
            opex_bottoms += heights_arr

    # X-axis
    ax.set_xticks(group_positions)
    ax.set_xticklabels(groups, fontsize=11)

    # Technology legend
    tech_handles = [
        mpatches.Patch(facecolor=color_map.get(t, "#CCCCCC"), label=t)
        for t in tech_order
        if t in cost_df["technology"].unique()
    ]
    tech_legend = ax.legend(
        handles=tech_handles,
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        frameon=False,
        fontsize=10,
        title="Technology",
    )
    ax.add_artist(tech_legend)

    # Cost-type legend (CAPEX solid vs OPEX hatched)
    cost_type_handles = [
        mpatches.Patch(facecolor="gray", edgecolor="white", label="CAPEX"),
        mpatches.Patch(facecolor="gray", edgecolor="white", hatch="///", label="OPEX"),
    ]
    cost_legend = ax.legend(
        handles=cost_type_handles,
        loc="upper left",
        bbox_to_anchor=(1.02, 0.55),
        frameon=False,
        fontsize=10,
        title="Cost type",
    )
    ax.add_artist(cost_legend)

    # Hue legend (only when multiple hues)
    if n_hues > 1:
        hue_handles = [
            mpatches.Patch(facecolor="gray", alpha=0.4 + 0.5 * i / max(n_hues - 1, 1), label=h)
            for i, h in enumerate(hues)
        ]
        ax.legend(
            handles=hue_handles,
            loc="upper left",
            bbox_to_anchor=(1.02, 0.25),
            frameon=False,
            fontsize=10,
            title="Scenarios",
        )

    ax.set_xlabel("Case group", fontsize=13, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=13, fontweight="bold")
    ax.set_title(title, fontsize=16, fontweight="bold", pad=20)
    ax.yaxis.grid(True, linestyle="--", alpha=0.3)
    ax.set_axisbelow(True)

    plt.tight_layout()
    save_figure(fig, output_path, dpi=_DPI)
