"""Smoke tests for zonal plotting helpers (PR #53 follow-up).

Spec: ``dev_guidelines/zonal_model/plots_followup.md``.

Drives the canonical 2-area RoR fixture under ``Data/zonal_test/`` end-to-end
through HiGHS, then exercises the three new plotting helpers in
:mod:`sdom.analytic_tools._zonal`. Skips the entire module when HiGHS is not
available.
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")  # noqa: E402  must precede pyplot import

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pyomo.environ as pyo  # noqa: E402
import pytest  # noqa: E402

from sdom import initialize_model, load_data  # noqa: E402
from sdom.optimization_main import (  # noqa: E402
    get_default_solver_config_dict,
    run_solver,
)


REL_ZONAL_FIXTURE = "Data/zonal_test"


def _abs_data_path(rel: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", rel))


def _highs_available() -> bool:
    for name in ("appsi_highs", "highs"):
        try:
            s = pyo.SolverFactory(name)
            if s is not None and s.available(exception_flag=False):
                return True
        except Exception:
            continue
    return False


def _highs_config():
    config = get_default_solver_config_dict(solver_name="highs")
    config["solve_keywords"]["tee"] = False
    config["solve_keywords"]["report_timing"] = False
    config["solve_keywords"]["keepfiles"] = False
    return config


pytestmark = pytest.mark.skipif(
    not _highs_available(), reason="HiGHS solver not available"
)


# ---------------------------------------------------------------------------
# Module-scoped fixture: solve the 2-area zonal fixture once.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def zonal_results():
    data = load_data(_abs_data_path(REL_ZONAL_FIXTURE))
    model = initialize_model(data, n_hours=24)
    return run_solver(model, _highs_config(), case_name="zonal_plot_test")


@pytest.fixture(autouse=True)
def _close_figures():
    """Make sure each test starts and ends with no leftover figures."""
    plt.close("all")
    yield
    plt.close("all")


# ---------------------------------------------------------------------------
# 1. Per-area generation stacks
# ---------------------------------------------------------------------------
def test_plot_area_generation_stacks_runs(zonal_results):
    from sdom.analytic_tools import plot_area_generation_stacks

    fig = plot_area_generation_stacks(zonal_results)

    # N areas -> N subplots.
    assert len(fig.axes) == len(zonal_results.areas)

    # Every subplot legend carries at least the canonical generation techs that
    # have data (Hydro is the only non-zero one in the RoR fixture, but the
    # legend includes whatever was stacked).
    for ax in fig.axes:
        leg = ax.get_legend()
        assert leg is not None, "expected a legend on each generation subplot"
        labels = [t.get_text() for t in leg.get_texts()]
        # Hydro must appear (RoR fixture has nonzero hydro).
        assert "Hydro" in labels


def test_plot_area_generation_stacks_save_path_works(zonal_results, tmp_path):
    from sdom.analytic_tools import plot_area_generation_stacks

    out = tmp_path / "gen_stacks.png"
    plot_area_generation_stacks(zonal_results, save_path=out)
    assert out.exists()
    assert out.stat().st_size > 0


# ---------------------------------------------------------------------------
# 2. Per-area capacity stacks
# ---------------------------------------------------------------------------
def test_plot_area_capacity_stacks_runs(zonal_results):
    from sdom.analytic_tools import plot_area_capacity_stacks

    # Power mode (MW)
    fig_p = plot_area_capacity_stacks(zonal_results, mode="power")
    ax_p = fig_p.axes[0]
    # One bar per area (matplotlib creates one BarContainer per technology, but
    # the x-tick labels list the areas).
    xticks = [t.get_text() for t in ax_p.get_xticklabels()]
    assert set(xticks) == set(zonal_results.areas)

    # Sum of stacked segments per area must approximately match
    # area_capacity[a] (Thermal+Solar PV+Wind) plus storage discharge.
    from matplotlib.container import BarContainer

    bar_containers = [c for c in ax_p.containers if isinstance(c, BarContainer)]
    assert bar_containers, "expected at least one BarContainer on the axis"

    n_areas = len(zonal_results.areas)
    summed = np.zeros(n_areas)
    for bc in bar_containers:
        # one bar per area
        heights = np.array([rect.get_height() for rect in bc.patches])
        assert heights.shape == (n_areas,)
        summed += heights

    expected = []
    for a in zonal_results.areas:
        cap = zonal_results.area_capacity[a]
        gen_total = cap.get("Thermal", 0) + cap.get("Solar PV", 0) + cap.get("Wind", 0)
        sto = zonal_results.area_storage_capacity.get(a, {}).get("discharge", {})
        sto_total = sum(v for k, v in sto.items() if k != "All")
        expected.append(gen_total + sto_total)
    np.testing.assert_allclose(summed, expected, rtol=1e-6, atol=1e-6)

    # Energy mode (MWh): also produces a non-empty figure.
    fig_e = plot_area_capacity_stacks(zonal_results, mode="energy")
    assert len(fig_e.axes) >= 1
    bcs = [c for c in fig_e.axes[0].containers if isinstance(c, BarContainer)]
    # Energy mode = storage only; if the fixture builds zero storage we still
    # expect at least one BarContainer (per storage tech).
    assert bcs, "expected storage BarContainers in energy mode"


def test_plot_area_capacity_stacks_invalid_mode(zonal_results):
    from sdom.analytic_tools import plot_area_capacity_stacks

    with pytest.raises(ValueError, match="mode"):
        plot_area_capacity_stacks(zonal_results, mode="garbage")
    with pytest.raises(ValueError, match="orientation"):
        plot_area_capacity_stacks(zonal_results, orientation="diagonal")
    with pytest.raises(ValueError, match="energy"):
        plot_area_capacity_stacks(
            zonal_results, mode="energy", include_storage=False
        )


def test_plot_area_capacity_stacks_save_path_works(zonal_results, tmp_path):
    from sdom.analytic_tools import plot_area_capacity_stacks

    out = tmp_path / "cap_stacks.png"
    plot_area_capacity_stacks(zonal_results, save_path=out)
    assert out.exists()
    assert out.stat().st_size > 0


# ---------------------------------------------------------------------------
# 3. Line-flow heatmap
# ---------------------------------------------------------------------------
def test_plot_line_flow_heatmap_runs(zonal_results):
    from sdom.analytic_tools import plot_line_flow_heatmap

    fig = plot_line_flow_heatmap(zonal_results)
    ax = fig.axes[0]
    images = ax.get_images()
    assert images, "expected a heatmap image"
    arr = images[0].get_array()
    n_lines = len(zonal_results.lines)
    n_hours = zonal_results.interregional_exchanges_df["hour"].nunique()
    assert arr.shape == (n_lines, n_hours)

    # Symmetric color limits when not normalizing.
    vmin, vmax = images[0].get_clim()
    assert vmin == pytest.approx(-vmax)


def test_plot_line_flow_heatmap_save_path_works(zonal_results, tmp_path):
    from sdom.analytic_tools import plot_line_flow_heatmap

    out = tmp_path / "line_flow.png"
    plot_line_flow_heatmap(zonal_results, save_path=out)
    assert out.exists()
    assert out.stat().st_size > 0


# ---------------------------------------------------------------------------
# Validation: all three reject non-zonal results.
# ---------------------------------------------------------------------------
def test_helpers_reject_non_zonal_results():
    from sdom.results import OptimizationResults
    from sdom.analytic_tools import (
        plot_area_generation_stacks,
        plot_area_capacity_stacks,
        plot_line_flow_heatmap,
    )

    r = OptimizationResults()  # is_zonal=False by default
    for fn in (
        plot_area_generation_stacks,
        plot_area_capacity_stacks,
        plot_line_flow_heatmap,
    ):
        with pytest.raises(ValueError, match="zonal"):
            fn(r)
