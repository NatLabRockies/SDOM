"""Phase 6 - Deliverable C: distribution plots over per-hour metrics."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # noqa: E402  - must precede pyplot import

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from sdom.resiliency import ResiliencyResults  # noqa: E402
from sdom.resiliency.plotting import plot_metric_distribution  # noqa: E402


def _make_results(*, n=100, seed=0):
    rng = np.random.default_rng(seed)
    eue = np.clip(rng.normal(loc=10.0, scale=5.0, size=n), 0.0, None)
    df = pd.DataFrame(
        {
            "EUE": eue,
            "USE_hours": rng.integers(0, 5, size=n),
            "max_unserved_MW": eue / 2,
            "objective_value": np.zeros(n),
            "solver_status": ["optimal"] * n,
            "solve_time_s": [0.01] * n,
            "truncated": [False] * n,
            "error_message": [""] * n,
        },
        index=pd.Index(list(range(1, n + 1)), name="hour"),
    )
    return ResiliencyResults(per_hour=df, metadata={"n_hours": n})


def test_plot_hist_returns_axes():
    results = _make_results()
    ax = plot_metric_distribution(results, metric="EUE", kind="hist")
    assert isinstance(ax, plt.Axes)
    assert len(ax.patches) > 0
    plt.close(ax.figure)


def test_plot_ecdf():
    results = _make_results()
    ax = plot_metric_distribution(results, metric="EUE", kind="ecdf")
    assert isinstance(ax, plt.Axes)
    lines = ax.get_lines()
    assert len(lines) == 1
    x, y = lines[0].get_xdata(), lines[0].get_ydata()
    assert np.all(np.diff(x) >= 0)
    assert np.all(np.diff(y) >= 0)
    assert y[0] >= 0.0 and y[-1] == pytest.approx(1.0)
    plt.close(ax.figure)


def test_plot_exceedance():
    results = _make_results()
    ax = plot_metric_distribution(results, metric="EUE", kind="exceedance")
    assert isinstance(ax, plt.Axes)
    lines = ax.get_lines()
    assert len(lines) == 1
    y = lines[0].get_ydata()
    assert np.all(np.diff(y) <= 0)
    assert y[0] == pytest.approx(1.0)
    assert y[-1] >= 0.0
    plt.close(ax.figure)


def test_plot_with_external_ax():
    results = _make_results()
    fig, ax = plt.subplots()
    out_ax = plot_metric_distribution(results, metric="EUE", kind="hist", ax=ax)
    assert out_ax is ax
    assert ax.has_data()
    plt.close(fig)


def test_plot_invalid_kind_raises():
    results = _make_results()
    with pytest.raises(ValueError, match="kind"):
        plot_metric_distribution(results, metric="EUE", kind="bogus")


def test_plot_invalid_metric_raises():
    results = _make_results()
    with pytest.raises(ValueError, match="EUE_xyz_not_a_column"):
        plot_metric_distribution(results, metric="EUE_xyz_not_a_column", kind="hist")
