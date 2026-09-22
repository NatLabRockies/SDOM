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
import pandas as pd  # noqa: E402

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
    from matplotlib.container import BarContainer

    from sdom.analytic_tools import plot_area_generation_stacks

    fig = plot_area_generation_stacks(zonal_results)
    ax = fig.axes[0]

    assert len(fig.axes) == 1
    assert {tick.get_text() for tick in ax.get_xticklabels()} == set(zonal_results.areas)
    assert ax.get_ylabel() == "Annual generation (MWh)"

    leg = ax.get_legend()
    assert leg is not None, "expected a technology legend"
    labels = [t.get_text() for t in leg.get_texts()]
    assert "Hydro" in labels

    bar_containers = [
        container for container in ax.containers if isinstance(container, BarContainer)
    ]
    actual_totals = sum(
        np.array([bar.get_height() for bar in container.patches])
        for container in bar_containers
    )
    expected_totals = []
    generation_columns = (
        "All Thermal Generation (MW)",
        "Solar PV Generation (MW)",
        "Wind Generation (MW)",
        "Hydro Generation (MW)",
        "Nuclear Generation (MW)",
        "Other Renewables Generation (MW)",
    )
    for area in zonal_results.areas:
        generation_df = zonal_results.area_generation_df[area]
        generation_total = sum(
            pd.to_numeric(generation_df[column], errors="coerce").fillna(0.0).sum()
            for column in generation_columns
            if column in generation_df
        )
        storage_df = zonal_results.area_storage_df[area]
        storage_total = pd.to_numeric(
            storage_df.get("Discharging power (MW)", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0.0).sum()
        expected_totals.append(generation_total + storage_total)
    np.testing.assert_allclose(actual_totals, expected_totals, rtol=1e-6, atol=1e-6)


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


def test_plot_results_creates_default_zonal_specific_plots(zonal_results, tmp_path):
    """The default workflow includes the zonal per-area and flow plots."""
    from sdom.analytic_tools import plot_results

    plot_results(zonal_results, plots_dir=str(tmp_path))

    expected = {
        "area_generation_stacks.png",
        "area_capacity_stacks_power.png",
        "line_flow_heatmap.png",
    }
    assert expected <= {path.name for path in tmp_path.iterdir()}


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


def test_duration_curves_create_zonal_outputs_with_signed_flows_and_prices(tmp_path):
    """Zonal duration curves retain signed flows and one series per area."""
    from sdom.analytic_tools._duration_curves import plot_duration_curves

    class Result:
        is_zonal = True
        marginal_prices_df = pd.DataFrame(
            {
                "area_id": ["A1", "A2", "A1", "A2"],
                "pricing_status": ["available"] * 4,
                "hour": [1, 1, 2, 2],
                "marginal_price_USD_per_MWh": [30.0, 20.0, 25.0, 22.0],
            }
        )
        interregional_exchanges_df = pd.DataFrame(
            {
                "line_id": ["L1", "L1", "L2", "L2"],
                "hour": [1, 2, 1, 2],
                "flow_signed_MW": [-5.0, 4.0, -2.0, 1.0],
            }
        )

    generation_df = pd.DataFrame(
        {
            "Hour": [1, 2],
            "All Thermal Generation (MW)": [10.0, 20.0],
            "Load (MW)": [35.0, 30.0],
            "Net Load (MW)": [30.0, 25.0],
        }
    )

    plot_duration_curves(Result(), generation_df=generation_df, plots_dir=str(tmp_path))

    expected = {
        "duration_curve_system_total_thermal_generation.png",
        "duration_curve_system_load.png",
        "duration_curve_system_net_load.png",
        "duration_curve_interregional_signed_flows.png",
        "duration_curve_zonal_marginal_prices.png",
    }
    assert expected <= {path.name for path in tmp_path.iterdir()}
