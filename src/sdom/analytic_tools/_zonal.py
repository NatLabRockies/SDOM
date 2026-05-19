"""Zonal plotting helpers for SDOM analytic_tools.

Public API (per :file:`dev_guidelines/zonal_model/plots_followup.md` MVP):

- :func:`plot_area_generation_stacks` -- per-area stacked generation profile
  (one subplot per area).
- :func:`plot_area_capacity_stacks` -- per-area total installed capacity as a
  stacked bar (one bar per area).
- :func:`plot_line_flow_heatmap` -- ``lines x hours`` heatmap of signed
  interregional flow.

All three functions consume an :class:`~sdom.results.OptimizationResults`
populated by the zonal collector (``is_zonal == True``). Colors and stacking
order come from :mod:`sdom.analytic_tools._colors` (the single source of truth
for the package's palette).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Iterable, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ._colors import (
    get_heatmap_cmap,
    get_technology_color_map,
    get_technology_order,
    infer_storage_technologies,
)
from ._utils import save_figure

if TYPE_CHECKING:  # pragma: no cover
    from ..results import OptimizationResults

logger = logging.getLogger(__name__)

__all__ = [
    "plot_area_generation_stacks",
    "plot_area_capacity_stacks",
    "plot_line_flow_heatmap",
]


# ---------------------------------------------------------------------------
# Mapping from canonical technology name -> column in
# ``OptimizationResults.area_generation_df[a]``. Storage technologies are
# pulled from ``area_storage_df[a]`` (per-tech ``Discharging power (MW)``).
# ---------------------------------------------------------------------------
_GEN_TECH_COLUMNS = {
    "Thermal": "All Thermal Generation (MW)",
    "Solar PV": "Solar PV Generation (MW)",
    "Wind": "Wind Generation (MW)",
    "Hydro": "Hydro Generation (MW)",
    "Nuclear": "Nuclear Generation (MW)",
    "Other renewables": "Other Renewables Generation (MW)",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_zonal(results: "OptimizationResults") -> None:
    if not getattr(results, "is_zonal", False):
        raise ValueError(
            "Zonal plotting helper requires an OptimizationResults produced "
            "by the zonal collector (is_zonal=True)."
        )


def _resolve_areas(
    results: "OptimizationResults",
    areas: Optional[Iterable[str]],
) -> list:
    if areas is None:
        return list(results.areas)
    resolved = list(areas)
    unknown = [a for a in resolved if a not in results.areas]
    if unknown:
        raise ValueError(
            f"Unknown area(s) {unknown!r}; available: {list(results.areas)!r}"
        )
    return resolved


def _collect_storage_techs(
    results: "OptimizationResults",
    areas: Iterable[str],
) -> list:
    """Union of per-tech storage names across *areas* (excludes ``"All"``)."""
    techs: set = set()
    for a in areas:
        sc = results.area_storage_capacity.get(a, {})
        for sub in ("discharge", "energy", "charge"):
            for k in sc.get(sub, {}):
                if k != "All":
                    techs.add(k)
        sdf = results.area_storage_df.get(a, pd.DataFrame())
        if not sdf.empty and "Technology" in sdf.columns:
            techs.update(t for t in sdf["Technology"].unique() if t != "All")
    return infer_storage_technologies(sorted(techs))


# ---------------------------------------------------------------------------
# 1. Per-area generation stacks
# ---------------------------------------------------------------------------


def plot_area_generation_stacks(
    results: "OptimizationResults",
    *,
    areas: Optional[Iterable[str]] = None,
    hours: Optional[Iterable[int]] = None,
    ax: Optional[plt.Axes] = None,
    save_path: Optional[str] = None,
) -> plt.Figure:
    """Plot per-area stacked generation (one subplot per area).

    Parameters
    ----------
    results : OptimizationResults
        Zonal-mode result (``is_zonal == True``).
    areas : iterable of str, optional
        Subset of areas to plot, in the order provided. Defaults to
        ``results.areas``.
    hours : iterable of int, optional
        Subset of hours to plot. Defaults to all hours in
        ``area_generation_df``.
    ax : matplotlib.axes.Axes, optional
        Existing axis to plot into. Ignored (with a warning) when more than
        one area is being plotted, since this helper requires a 2D figure.
    save_path : str or os.PathLike, optional
        If provided, the figure is saved with
        :func:`sdom.analytic_tools._utils.save_figure` (which closes it).

    Returns
    -------
    matplotlib.figure.Figure
        The figure containing the per-area subplots.

    Raises
    ------
    ValueError
        If *results* is not a zonal result.

    Examples
    --------
    >>> fig = plot_area_generation_stacks(results)  # doctest: +SKIP
    """
    _validate_zonal(results)
    areas_list = _resolve_areas(results, areas)

    storage_techs = _collect_storage_techs(results, areas_list)
    color_map = get_technology_color_map(storage_techs)
    tech_order = get_technology_order(storage_techs)

    if ax is not None and len(areas_list) > 1:
        logger.warning(
            "plot_area_generation_stacks: 'ax' is ignored when len(areas) > 1; "
            "creating a fresh figure with %d subplots.",
            len(areas_list),
        )
        ax = None

    if ax is None:
        fig, axes_arr = plt.subplots(
            len(areas_list),
            1,
            figsize=(12, max(2.5, 2.5 * len(areas_list))),
            sharex=True,
            squeeze=False,
        )
        axes_list = list(axes_arr.flatten())
    else:
        fig = ax.figure
        axes_list = [ax]

    for i, a in enumerate(areas_list):
        ax_a = axes_list[i]
        gdf = results.area_generation_df.get(a, pd.DataFrame())
        sdf = results.area_storage_df.get(a, pd.DataFrame())

        if gdf.empty:
            ax_a.set_title(f"Area {a} (no generation data)")
            continue

        all_hours = list(gdf["Hour"])
        plot_hours = list(hours) if hours is not None else all_hours
        gdf_h = gdf[gdf["Hour"].isin(plot_hours)]
        x = list(gdf_h["Hour"])

        tech_series: dict = {}
        for tech, col in _GEN_TECH_COLUMNS.items():
            if col in gdf_h.columns:
                vals = pd.to_numeric(gdf_h[col], errors="coerce").fillna(0.0).values
                if np.any(vals != 0):
                    tech_series[tech] = vals

        if not sdf.empty and "Technology" in sdf.columns:
            for t in storage_techs:
                rows = sdf[
                    (sdf["Technology"] == t) & sdf["Hour"].isin(plot_hours)
                ]
                if rows.empty:
                    continue
                series = (
                    rows.set_index("Hour")["Discharging power (MW)"]
                    .reindex(x)
                    .fillna(0.0)
                    .values
                )
                if np.any(series != 0):
                    tech_series[t] = series

        labels = [t for t in tech_order if t in tech_series]
        if not labels:
            ax_a.set_title(f"Area {a} (no generation in selected window)")
            continue

        ys = [tech_series[t] for t in labels]
        colors = [color_map.get(t, "#CCCCCC") for t in labels]
        ax_a.stackplot(x, ys, labels=labels, colors=colors)
        ax_a.set_title(f"Area {a}")
        ax_a.set_ylabel("Generation (MW)")
        ax_a.legend(loc="upper right", fontsize=8, ncol=2)
        ax_a.margins(x=0)

    axes_list[-1].set_xlabel("Hour")
    fig.tight_layout()

    if save_path is not None:
        save_figure(fig, str(save_path))
    return fig


# ---------------------------------------------------------------------------
# 2. Per-area capacity stacks
# ---------------------------------------------------------------------------


def plot_area_capacity_stacks(
    results: "OptimizationResults",
    *,
    areas: Optional[Iterable[str]] = None,
    mode: str = "power",
    include_storage: bool = True,
    orientation: str = "vertical",
    ax: Optional[plt.Axes] = None,
    save_path: Optional[str] = None,
) -> plt.Figure:
    """Plot per-area total installed capacity as a stacked bar chart.

    Parameters
    ----------
    results : OptimizationResults
        Zonal-mode result.
    areas : iterable of str, optional
        Subset of areas (preserves order). Defaults to ``results.areas``.
    mode : {"power", "energy"}
        ``"power"`` stacks generation capacity (MW) plus storage discharge
        capacity (MW) when *include_storage* is True. ``"energy"`` stacks
        storage energy capacity only (MWh) and requires *include_storage*.
    include_storage : bool
        Whether to include storage in the stack. Default True.
    orientation : {"vertical", "horizontal"}
        Bar orientation; ``"vertical"`` puts areas on the x-axis.
    ax : matplotlib.axes.Axes, optional
        Existing axis to plot into. A new figure is created otherwise.
    save_path : str or os.PathLike, optional
        If given, figure is saved via :func:`save_figure` (which closes it).

    Returns
    -------
    matplotlib.figure.Figure
        Figure containing the stacked bar chart.

    Raises
    ------
    ValueError
        If *results* is not zonal, *mode* / *orientation* are unrecognized,
        or ``mode="energy"`` is combined with ``include_storage=False``.

    Examples
    --------
    >>> fig = plot_area_capacity_stacks(results, mode="power")  # doctest: +SKIP
    """
    _validate_zonal(results)
    if mode not in {"power", "energy"}:
        raise ValueError(f"mode must be 'power' or 'energy', got {mode!r}")
    if orientation not in {"vertical", "horizontal"}:
        raise ValueError(
            f"orientation must be 'vertical' or 'horizontal', got {orientation!r}"
        )
    if mode == "energy" and not include_storage:
        raise ValueError(
            "mode='energy' requires include_storage=True (no meaningful "
            "non-storage energy capacity is collected)."
        )

    areas_list = _resolve_areas(results, areas)

    storage_techs = (
        _collect_storage_techs(results, areas_list) if include_storage else []
    )
    color_map = get_technology_color_map(storage_techs)

    gen_techs = ["Thermal", "Solar PV", "Wind"] if mode == "power" else []
    techs_in_order = [
        t
        for t in get_technology_order(storage_techs)
        if t in gen_techs or t in storage_techs
    ]

    storage_subkey = "discharge" if mode == "power" else "energy"

    data: dict = {t: [] for t in techs_in_order}
    for a in areas_list:
        cap = results.area_capacity.get(a, {})
        sc = results.area_storage_capacity.get(a, {}).get(storage_subkey, {})
        for t in techs_in_order:
            if t in gen_techs:
                data[t].append(float(cap.get(t, 0.0) or 0.0))
            else:
                data[t].append(float(sc.get(t, 0.0) or 0.0))

    if ax is None:
        fig, ax = plt.subplots(figsize=(max(6, 1.5 * len(areas_list) + 4), 6))
    else:
        fig = ax.figure

    n = len(areas_list)
    bottom = np.zeros(n)
    for t in techs_in_order:
        vals = np.asarray(data[t], dtype=float)
        color = color_map.get(t, "#CCCCCC")
        if orientation == "vertical":
            ax.bar(areas_list, vals, bottom=bottom, label=t, color=color)
        else:
            ax.barh(areas_list, vals, left=bottom, label=t, color=color)
        bottom = bottom + vals

    unit = "MW" if mode == "power" else "MWh"
    if orientation == "vertical":
        ax.set_xlabel("Area")
        ax.set_ylabel(f"Installed capacity ({unit})")
    else:
        ax.set_xlabel(f"Installed capacity ({unit})")
        ax.set_ylabel("Area")
    ax.set_title(f"Per-area installed capacity ({mode})")
    if techs_in_order:
        ax.legend(fontsize=8, loc="best")
    fig.tight_layout()

    if save_path is not None:
        save_figure(fig, str(save_path))
    return fig


# ---------------------------------------------------------------------------
# 3. Line-flow heatmap
# ---------------------------------------------------------------------------


def plot_line_flow_heatmap(
    results: "OptimizationResults",
    *,
    hours: Optional[Iterable[int]] = None,
    normalize_by_capacity: bool = False,
    ax: Optional[plt.Axes] = None,
    save_path: Optional[str] = None,
) -> plt.Figure:
    """Plot a ``lines x hours`` heatmap of signed interregional flow.

    Parameters
    ----------
    results : OptimizationResults
        Zonal-mode result with non-empty ``interregional_exchanges_df``.
    hours : iterable of int, optional
        Subset of hours to plot. Defaults to all hours in the exchanges
        DataFrame.
    normalize_by_capacity : bool
        If True, each line's row is divided by ``max(|cap_FT|, |cap_TF|)``
        and the color limits are fixed to ``[-1, 1]``. If False, color
        limits are symmetric: ``vmax = max(|flow|)``, ``vmin = -vmax``.
    ax : matplotlib.axes.Axes, optional
        Existing axis to plot into. A new figure is created otherwise.
    save_path : str or os.PathLike, optional
        If given, figure is saved via :func:`save_figure`.

    Returns
    -------
    matplotlib.figure.Figure
        The figure containing the heatmap.

    Raises
    ------
    ValueError
        If *results* is not zonal, or if
        ``results.interregional_exchanges_df`` is empty.

    Notes
    -----
    The colormap is the project-wide :func:`get_heatmap_cmap` from
    :mod:`sdom.analytic_tools._colors`. It is applied with symmetric color
    limits so that zero flow renders consistently across runs.

    Examples
    --------
    >>> fig = plot_line_flow_heatmap(results)  # doctest: +SKIP
    """
    _validate_zonal(results)
    df = results.interregional_exchanges_df
    if df is None or df.empty:
        raise ValueError(
            "interregional_exchanges_df is empty; this result does not "
            "contain inter-area lines (zonal-with-lines required)."
        )

    if hours is not None:
        df = df[df["hour"].isin(list(hours))]
        if df.empty:
            raise ValueError(
                "No exchange rows remain after filtering by 'hours'."
            )

    line_ids = sorted(df["line_id"].unique().tolist())
    matrix = (
        df.pivot(index="line_id", columns="hour", values="flow_signed_MW")
        .reindex(line_ids)
        .sort_index(axis=1)
        .fillna(0.0)
    )

    if normalize_by_capacity:
        caps = df.groupby("line_id")[["cap_FT_MW", "cap_TF_MW"]].max().abs()
        denom = caps.max(axis=1).reindex(line_ids).replace(0, np.nan)
        matrix = matrix.div(denom, axis=0).fillna(0.0)
        vmin, vmax = -1.0, 1.0
    else:
        amax = float(np.abs(matrix.values).max()) if matrix.size else 0.0
        if amax == 0.0:
            amax = 1.0
        vmin, vmax = -amax, amax

    if ax is None:
        height = max(2.0, 0.5 * len(line_ids) + 2.0)
        fig, ax = plt.subplots(figsize=(12, height))
    else:
        fig = ax.figure

    cmap = get_heatmap_cmap()
    hours_axis = list(matrix.columns)
    im = ax.imshow(
        matrix.values,
        aspect="auto",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        interpolation="nearest",
    )
    ax.set_yticks(range(len(line_ids)))
    ax.set_yticklabels([str(l) for l in line_ids])
    if hours_axis:
        n_xticks = min(12, len(hours_axis))
        idx = np.linspace(0, len(hours_axis) - 1, n_xticks, dtype=int)
        ax.set_xticks(idx)
        ax.set_xticklabels([str(hours_axis[i]) for i in idx])
    ax.set_xlabel("Hour")
    ax.set_ylabel("Line")
    title = (
        "Interregional flow, normalized [-1, 1]"
        if normalize_by_capacity
        else "Interregional flow (MW, signed FT positive)"
    )
    ax.set_title(title)
    fig.colorbar(im, ax=ax)
    fig.tight_layout()

    if save_path is not None:
        save_figure(fig, str(save_path))
    return fig
