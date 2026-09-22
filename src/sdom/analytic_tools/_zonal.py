"""Zonal plotting helpers for SDOM analytic_tools.

Public API (per :file:`dev_guidelines/zonal_model/plots_followup.md` MVP):

- :func:`plot_area_generation_stacks` -- annual generation by area as stacked
    bars.
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


def _result_unit(results: "OptimizationResults", name: str, fallback: str) -> str:
    """Return result metadata display units while supporting legacy results."""
    accessor = getattr(results, "get_attribute_unit", None)
    return accessor(name) if accessor is not None and accessor(name) else fallback


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
    """Plot annual generation by area as a stacked bar chart.

    Parameters
    ----------
    results : OptimizationResults
        Zonal-mode result (``is_zonal == True``).
    areas : iterable of str, optional
        Subset of areas to plot, in the order provided. Defaults to
        ``results.areas``.
    hours : iterable of int, optional
        Subset of hours to aggregate. Defaults to all simulated hours.
    ax : matplotlib.axes.Axes, optional
        Existing axis to plot into. A new figure is created otherwise.
    save_path : str or os.PathLike, optional
        If provided, the figure is saved with
        :func:`sdom.analytic_tools._utils.save_figure` (which closes it).

    Returns
    -------
    matplotlib.figure.Figure
        The figure containing the annual generation stacked bars.

    Notes
    -----
    SDOM models one-hour dispatch periods, so summing hourly generation in MW
    produces energy in MWh.

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

    if ax is None:
        fig, ax = plt.subplots(figsize=(max(6, 1.5 * len(areas_list) + 4), 7))
    else:
        fig = ax.figure

    annual_generation: dict[str, dict[str, float]] = {}
    for area in areas_list:
        gdf = results.area_generation_df.get(area, pd.DataFrame())
        sdf = results.area_storage_df.get(area, pd.DataFrame())
        annual_generation[area] = {}

        if gdf.empty:
            continue

        plot_hours = list(hours) if hours is not None else list(gdf["Hour"])
        gdf_h = gdf[gdf["Hour"].isin(plot_hours)]

        for tech, col in _GEN_TECH_COLUMNS.items():
            if col in gdf_h.columns:
                value = pd.to_numeric(gdf_h[col], errors="coerce").fillna(0.0).sum()
                if value != 0:
                    annual_generation[area][tech] = value

        if not sdf.empty and "Technology" in sdf.columns:
            for tech in storage_techs:
                rows = sdf[
                    (sdf["Technology"] == tech) & sdf["Hour"].isin(plot_hours)
                ]
                if rows.empty:
                    continue
                value = pd.to_numeric(
                    rows["Discharging power (MW)"], errors="coerce"
                ).fillna(0.0).sum()
                if value != 0:
                    annual_generation[area][tech] = value

    bottoms = np.zeros(len(areas_list))
    for tech in tech_order:
        values = np.array(
            [annual_generation[area].get(tech, 0.0) for area in areas_list]
        )
        if not np.any(values != 0):
            continue
        ax.bar(
            areas_list,
            values,
            bottom=bottoms,
            label=tech,
            color=color_map.get(tech, "#CCCCCC"),
        )
        bottoms += values

    ax.set_xlabel("Area")
    ax.set_ylabel("Annual generation (MWh)")
    ax.set_title("Annual Generation by Area")
    if np.any(bottoms != 0):
        ax.legend(title="Technology")
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

    unit_name = "capacity" if mode == "power" else "storage_capacity.energy"
    unit = _result_unit(results, unit_name, "MW" if mode == "power" else "MWh")
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
