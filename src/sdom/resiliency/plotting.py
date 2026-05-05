"""Distribution plots for :class:`sdom.resiliency.ResiliencyResults`.

Phase 6 deliverable C. Matplotlib is imported lazily so the module can be
imported in head-less environments without a display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:  # pragma: no cover - typing only
    from matplotlib.axes import Axes

    from sdom.resiliency.system_state import ResiliencyResults


_VALID_KINDS = ("hist", "ecdf", "exceedance")


__all__ = ["plot_metric_distribution"]


def plot_metric_distribution(
    results: "ResiliencyResults",
    *,
    metric: str = "EUE",
    kind: str = "hist",
    ax: "Axes | None" = None,
    **plot_kwargs: Any,
) -> "Axes":
    """Plot the empirical distribution of a per-hour metric.

    Parameters
    ----------
    results : ResiliencyResults
        Container produced by :func:`sdom.resiliency.run_resiliency_evaluation`.
    metric : str, optional
        Numeric column of ``results.per_hour`` to plot. Default ``"EUE"``.
    kind : {"hist", "ecdf", "exceedance"}, optional
        Plot style. Default ``"hist"``.

        * ``"hist"`` - histogram of metric values.
        * ``"ecdf"`` - empirical CDF, monotonically non-decreasing in ``[0, 1]``.
        * ``"exceedance"`` - exceedance curve ``1 - ECDF``, monotonically
          non-increasing.
    ax : matplotlib.axes.Axes, optional
        Existing axes to draw on. A new figure/axes is created when ``None``.
    **plot_kwargs
        Forwarded to the underlying matplotlib call (``ax.hist`` for
        ``kind="hist"``; ``ax.plot`` otherwise).

    Returns
    -------
    matplotlib.axes.Axes

    Raises
    ------
    ImportError
        If matplotlib is not importable.
    ValueError
        If ``kind`` is not a supported value or ``metric`` is not a numeric
        column of ``results.per_hour``.
    """
    if kind not in _VALID_KINDS:
        raise ValueError(
            f"Invalid kind={kind!r}. Expected one of {_VALID_KINDS}."
        )

    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover - matplotlib is a hard dep
        raise ImportError(
            "plot_metric_distribution requires matplotlib. Install with "
            "'pip install matplotlib'."
        ) from exc

    df = results.per_hour
    if "solver_status" in df.columns:
        df = df[df["solver_status"] != "error"]

    if metric not in df.columns:
        numeric_cols = sorted(
            c for c in df.columns if np.issubdtype(df[c].dtype, np.number)
        )
        raise ValueError(
            f"Unknown metric={metric!r}. Available numeric columns: {numeric_cols}."
        )

    values = df[metric].astype(float).to_numpy()
    values = values[~np.isnan(values)]

    if ax is None:
        _, ax = plt.subplots()

    if kind == "hist":
        ax.hist(values, **plot_kwargs)
        if not ax.get_ylabel():
            ax.set_ylabel("count")
    else:
        x = np.sort(values)
        n = len(x)
        if n == 0:
            y = np.array([], dtype=float)
        else:
            y = np.arange(1, n + 1, dtype=float) / n
        if kind == "exceedance":
            y = 1.0 - y + (1.0 / n if n else 0.0)
        ax.plot(x, y, **plot_kwargs)
        if not ax.get_ylabel():
            ax.set_ylabel(
                "P(X \u2264 x)" if kind == "ecdf" else "P(X > x)"
            )

    if not ax.get_xlabel():
        ax.set_xlabel(metric)

    return ax
