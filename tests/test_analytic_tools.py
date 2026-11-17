"""Tests for sdom.analytic_tools.

Covers:
- _colors.py: color-map completeness and dynamic storage assignment
- _single.py: plot_results() creates expected files in the correct directory
- _parametric.py: _split_into_chunks() and _available_dims() / case_metadata
"""

from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# _colors.py tests
# ---------------------------------------------------------------------------
from sdom.analytic_tools._colors import (
    STORAGE_COLORS,
    TECH_COLORS,
    get_technology_color_map,
    get_technology_order,
    infer_storage_technologies,
)


class TestColors:
    def test_base_tech_colors_present(self):
        """All canonical generation technologies have a color entry."""
        expected = {"Thermal", "Solar PV", "Wind", "Nuclear", "Hydro", "Other renewables"}
        assert expected == set(TECH_COLORS.keys())

    def test_get_technology_color_map_no_storage(self):
        cmap = get_technology_color_map(storage_techs=[])
        assert "Thermal" in cmap
        assert "Solar PV" in cmap
        assert "Wind" in cmap

    def test_get_technology_color_map_with_storage(self):
        storage = ["Battery", "Flywheel"]
        cmap = get_technology_color_map(storage_techs=storage)
        assert cmap["Battery"] == STORAGE_COLORS[0]
        assert cmap["Flywheel"] == STORAGE_COLORS[1]

    def test_storage_colors_cycle(self):
        """More storage techs than STORAGE_COLORS entries cycles the palette."""
        techs = [f"Storage_{i}" for i in range(len(STORAGE_COLORS) + 2)]
        cmap = get_technology_color_map(storage_techs=techs)
        assert cmap["Storage_0"] == cmap[f"Storage_{len(STORAGE_COLORS)}"]

    def test_get_technology_order_includes_all_base(self):
        order = get_technology_order()
        for tech in ("Thermal", "Solar PV", "Wind", "Nuclear", "Hydro", "Other renewables"):
            assert tech in order

    def test_get_technology_order_storage_appended_last(self):
        order = get_technology_order(storage_techs=["ZBattery", "ABattery"])
        # Storage appears after Wind
        assert order.index("ABattery") > order.index("Wind")
        assert order.index("ZBattery") > order.index("Wind")

    def test_infer_storage_technologies(self):
        techs = ["Thermal", "Solar PV", "Wind", "Li-Ion", "Flow Battery"]
        storage = infer_storage_technologies(techs)
        assert set(storage) == {"Li-Ion", "Flow Battery"}

    def test_infer_storage_excludes_all_keyword(self):
        techs = ["All", "Wind", "BatteryX"]
        storage = infer_storage_technologies(techs)
        assert "All" not in storage
        assert "BatteryX" in storage


# ---------------------------------------------------------------------------
# _single.py tests
# ---------------------------------------------------------------------------
from sdom.analytic_tools._single import plot_results, _resolve_plots_dir
from sdom.analytic_tools._duration_curves import (
    _plot_duration_curve,
    _plot_grouped_duration_curves,
    _plot_marginal_price_heatmap,
    _prepare_duration_series,
    plot_duration_curves,
)


def _make_minimal_summary_df() -> pd.DataFrame:
    """Minimal summary_df that the plotter can work with without crashing."""
    rows = [
        # Generation capacities
        {"Metric": "Capacity", "Technology": "Thermal",  "Optimal Value": 2000.0, "Unit": "MW", "Run": 1},
        {"Metric": "Capacity", "Technology": "Solar PV", "Optimal Value": 500.0,  "Unit": "MW", "Run": 1},
        {"Metric": "Capacity", "Technology": "Wind",     "Optimal Value": 800.0,  "Unit": "MW", "Run": 1},
        # Storage capacity
        {"Metric": "Charge power capacity", "Technology": "Li-Ion", "Optimal Value": 100.0, "Unit": "MW", "Run": 1},
        # Total generation
        {"Metric": "Total generation", "Technology": "Thermal",  "Optimal Value": 8e6,  "Unit": "MWh", "Run": 1},
        {"Metric": "Total generation", "Technology": "Solar PV", "Optimal Value": 2e6,  "Unit": "MWh", "Run": 1},
        {"Metric": "Total generation", "Technology": "Wind",     "Optimal Value": 3e6,  "Unit": "MWh", "Run": 1},
        # Curtailment
        {"Metric": "Total VRE curtailment",      "Technology": "All", "Optimal Value": 50000.0, "Unit": "MWh", "Run": 1},
        {"Metric": "VRE curtailment percentage", "Technology": "All", "Optimal Value": 1.5,      "Unit": "%",   "Run": 1},
    ]
    return pd.DataFrame(rows)


def _make_minimal_generation_df(n_hours: int = 24) -> pd.DataFrame:
    """Minimal generation_df with 24 hourly rows."""
    import numpy as np
    hours = list(range(1, n_hours + 1))
    data = {
        "Scenario": ["test"] * n_hours,
        "Hour": hours,
        "Solar PV Generation (MW)":   list(np.random.rand(n_hours) * 200),
        "Solar PV Curtailment (MW)":  [0.0] * n_hours,
        "Wind Generation (MW)":       list(np.random.rand(n_hours) * 300),
        "Wind Curtailment (MW)":      [0.0] * n_hours,
        "All Thermal Generation (MW)": list(np.random.rand(n_hours) * 800),
    }
    return pd.DataFrame(data)


class _FakeResult:
    """Minimal OptimizationResults-like object for tests."""

    is_optimal = True
    termination_condition = "optimal"

    def __init__(self):
        self.summary_df = _make_minimal_summary_df()
        self.generation_df = _make_minimal_generation_df()


class TestSinglePlots:
    def test_resolve_plots_dir_explicit(self):
        assert _resolve_plots_dir(None, "/my/plots") == "/my/plots"

    def test_resolve_plots_dir_from_output_dir(self):
        result = _resolve_plots_dir("/output", None)
        assert result == os.path.join("/output", "plots")

    def test_resolve_plots_dir_raises_when_both_none(self):
        with pytest.raises(ValueError, match="output_dir"):
            _resolve_plots_dir(None, None)

    def test_plot_results_creates_files(self):
        """plot_results should write PNG files into the resolved plots directory."""
        result = _FakeResult()
        with tempfile.TemporaryDirectory() as tmpdir:
            plot_results(result, output_dir=tmpdir)
            plots_dir = os.path.join(tmpdir, "plots")
            assert os.path.isdir(plots_dir), "plots sub-directory should be created"
            files = os.listdir(plots_dir)
            pngs = [f for f in files if f.endswith(".png")]
            assert len(pngs) > 0, "At least one PNG should be saved"
            # Specific expected files
            assert "capacity_donut.png" in pngs
            assert "capacity_generation_donuts.png" in pngs

    def test_plot_results_explicit_plots_dir(self):
        result = _FakeResult()
        with tempfile.TemporaryDirectory() as tmpdir:
            plots_dir = os.path.join(tmpdir, "custom_plots")
            plot_results(result, plots_dir=plots_dir)
            assert os.path.isdir(plots_dir)
            pngs = [f for f in os.listdir(plots_dir) if f.endswith(".png")]
            assert len(pngs) > 0

    def test_plot_results_skips_non_optimal(self):
        """Non-optimal results should not produce any files."""
        result = _FakeResult()
        result.is_optimal = False
        result.termination_condition = "infeasible"
        with tempfile.TemporaryDirectory() as tmpdir:
            plot_results(result, output_dir=tmpdir)
            plots_dir = os.path.join(tmpdir, "plots")
            assert not os.path.isdir(plots_dir)

    def test_plot_results_raises_no_dir(self):
        result = _FakeResult()
        with pytest.raises(ValueError):
            plot_results(result)

    def test_heatmap_files_created(self):
        """Heatmap PNG files should be generated for non-zero dispatch columns."""
        result = _FakeResult()
        with tempfile.TemporaryDirectory() as tmpdir:
            plot_results(result, output_dir=tmpdir)
            plots_dir = os.path.join(tmpdir, "plots")
            files = os.listdir(plots_dir)
            heatmaps = [f for f in files if f.startswith("heatmap_")]
            assert len(heatmaps) > 0, "At least one heatmap should be saved"


class TestDurationCurves:
    def test_duration_curve_increases_axis_label_and_tick_font_sizes(
        self, tmp_path, monkeypatch
    ):
        import matplotlib.pyplot as plt

        captured = {}

        def fake_save(fig, output_path):
            captured["fig"] = fig

        monkeypatch.setattr("sdom.analytic_tools._duration_curves.save_figure", fake_save)
        _plot_duration_curve(
            _prepare_duration_series(pd.Series([5.0, 3.0]), pd.Series([1, 2])),
            title="Duration curve",
            y_label="MW",
            output_path=str(tmp_path / "duration_curve.png"),
        )

        ax = captured["fig"].axes[0]
        expected_size = plt.rcParams["font.size"] + 4
        assert ax.xaxis.label.get_size() == expected_size
        assert ax.yaxis.label.get_size() == expected_size
        assert ax.get_xticklabels()[0].get_size() == expected_size
        assert ax.get_yticklabels()[0].get_size() == expected_size
        assert ax.title.get_fontsize() == 14
        assert all(text.get_fontsize() == expected_size for text in ax.get_legend().get_texts())
        colorbar_ax = captured["fig"].axes[1]
        assert colorbar_ax.yaxis.label.get_fontsize() == expected_size
        assert all(label.get_fontsize() == 12 for label in colorbar_ax.get_yticklabels())
        plt.close(captured["fig"])

    def test_prepare_duration_series_sorts_values_and_preserves_hours(self):
        series = _prepare_duration_series(
            pd.Series([2, "bad", 5, 3]), pd.Series([1, 24, 25, 8760])
        )

        assert series is not None
        assert series["value"].tolist() == [5.0, 3.0, 2.0]
        assert series["hour"].tolist() == [0, 23, 0]
        assert series["position"].tolist() == [0, 50, 100]

    def test_prepare_duration_series_returns_none_for_empty_or_non_numeric_data(self):
        assert _prepare_duration_series(pd.Series([], dtype=object), pd.Series([], dtype=float)) is None
        assert _prepare_duration_series(pd.Series(["bad", None]), pd.Series([1, 24])) is None

    def test_plot_duration_curves_creates_copperplate_outputs_and_skips_unavailable_prices(
        self, tmp_path
    ):
        result = _FakeResult()
        result.generation_df["Load (MW)"] = [120.0] * len(result.generation_df)
        result.generation_df["Net Load (MW)"] = [100.0] * len(result.generation_df)
        result.generation_df["Imports (MW)"] = [2.0] * len(result.generation_df)
        result.generation_df["Exports (MW)"] = [3.0] * len(result.generation_df)
        result.marginal_prices_df = pd.DataFrame(
            {
                "area_id": ["copperplate"] * 24,
                "pricing_status": ["available"] * 24,
                "hour": list(range(24, 0, -1)),
                "marginal_price_USD_per_MWh": list(range(20, 44)),
            }
        )

        plot_duration_curves(
            result,
            generation_df=result.generation_df,
            plots_dir=str(tmp_path),
        )

        expected = {
            "duration_curve_total_thermal_generation.png",
            "duration_curve_load.png",
            "duration_curve_net_load.png",
            "duration_curve_imports.png",
            "duration_curve_exports.png",
            "duration_curve_vre_curtailment_mw.png",
            "duration_curve_vre_curtailment_pct.png",
            "duration_curve_marginal_price.png",
            "heatmap_marginal_price.png",
        }
        assert expected <= {path.name for path in tmp_path.iterdir()}

    def test_plot_duration_curves_skips_invalid_optional_data(self, tmp_path, caplog):
        result = _FakeResult()
        result.generation_df["Net Load (MW)"] = "not numeric"
        result.marginal_prices_df = pd.DataFrame()

        plot_duration_curves(
            result,
            generation_df=result.generation_df,
            plots_dir=str(tmp_path),
        )

        assert "duration_curve_total_thermal_generation.png" in {
            path.name for path in tmp_path.iterdir()
        }
        assert "duration_curve_net_load.png" not in {
            path.name for path in tmp_path.iterdir()
        }
        assert "skipping" in caplog.text.lower()

    def test_plot_duration_curves_skips_empty_generation_once_and_keeps_prices(
        self, tmp_path, caplog
    ):
        result = _FakeResult()
        result.generation_df = pd.DataFrame()
        result.marginal_prices_df = pd.DataFrame(
            {
                "area_id": ["copperplate"] * 24,
                "pricing_status": ["available"] * 24,
                "hour": range(1, 25),
                "marginal_price_USD_per_MWh": range(20, 44),
            }
        )

        plot_duration_curves(
            result,
            generation_df=result.generation_df,
            plots_dir=str(tmp_path),
        )

        warnings = [
            record.message
            for record in caplog.records
            if record.name == "sdom.analytic_tools._duration_curves"
            and record.levelname == "WARNING"
        ]
        assert warnings == [
            "duration curves: generation data are empty; skipping generation curves."
        ]
        assert (tmp_path / "duration_curve_marginal_price.png").is_file()
        assert (tmp_path / "heatmap_marginal_price.png").is_file()

    def test_plot_results_includes_duration_curves(self, tmp_path):
        result = _FakeResult()
        result.generation_df["Load (MW)"] = [120.0] * len(result.generation_df)
        result.generation_df["Net Load (MW)"] = [100.0] * len(result.generation_df)

        plot_results(result, plots_dir=str(tmp_path))

        assert (tmp_path / "duration_curve_total_thermal_generation.png").is_file()
        assert (tmp_path / "duration_curve_load.png").is_file()
        assert (tmp_path / "duration_curve_net_load.png").is_file()

    def test_marginal_price_heatmap_uses_hour_grid_and_price_labels(self, tmp_path, monkeypatch):
        import matplotlib.pyplot as plt

        captured = {}

        def fake_save(fig, output_path):
            captured["fig"] = fig
            captured["output_path"] = output_path

        monkeypatch.setattr("sdom.analytic_tools._duration_curves.save_figure", fake_save)
        prices = pd.DataFrame(
            {
                "hour": [24, 1, 1],
                "marginal_price_USD_per_MWh": [30.0, 10.0, 20.0],
            }
        )

        assert _plot_marginal_price_heatmap(
            prices, output_path=str(tmp_path / "price_heatmap.png")
        )
        ax, colorbar_ax = captured["fig"].axes
        assert ax.get_title() == "Marginal price (USD/MWh)"
        assert colorbar_ax.get_ylabel() == "Marginal price (USD/MWh)"
        assert ax.collections[0].get_array()[0] == pytest.approx(15.0)
        plt.close(captured["fig"])

    def test_grouped_duration_curves_use_bounded_panels_and_shared_colorbar(
        self, tmp_path, monkeypatch
    ):
        import matplotlib.pyplot as plt

        captured = {}

        def fake_save(fig, output_path, **kwargs):
            captured["fig"] = fig
            with open(output_path, "wb") as stream:
                stream.write(b"preview")

        monkeypatch.setattr("matplotlib.figure.Figure.savefig", fake_save)
        data = pd.DataFrame(
            {
                "area_id": [f"A{index}" for index in range(5)],
                "price": [float(index) for index in range(5)],
                "hour": [1, 24, 25, 8760, 2],
            }
        )

        assert _plot_grouped_duration_curves(
            data,
            group_column="area_id",
            value_column="price",
            title="Prices",
            y_label="USD/MWh",
            output_path=str(tmp_path / "prices.png"),
        )
        axes = captured["fig"].axes
        assert len(axes) == 6
        for ax in axes[:-1]:
            assert not ax.get_lines()
            assert ax.collections[0].get_clim() == (0, 23)
            assert ax.collections[0].get_offsets()[0, 0] == 0
            np.testing.assert_allclose(
                [reference.get_offsets()[0, 1] for reference in ax.collections[1:]],
                [ax.collections[0].get_offsets()[0, 1]] * 3,
            )
        assert axes[-1].get_xlim() == (0, 23)
        assert any(text.get_text() == "Hour of day" for text in captured["fig"].texts)
        np.testing.assert_allclose(captured["fig"].get_size_inches(), [40 / 3, 7.5])
        plt.close(captured["fig"])


def test_duration_scatter_hour_colors_and_interpolated_references(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr("sdom.analytic_tools._duration_curves.save_figure", lambda fig, path: captured.append(fig))
    series = _prepare_duration_series(
        pd.Series([10, -10, 30, 20]), pd.Series([1, 24, 25, 8760])
    )
    _plot_duration_curve(series, title="Prices", y_label="USD/MWh", output_path=str(tmp_path / "price.png"))
    fig = captured[0]
    ax, colorbar = fig.axes
    points = ax.collections[0]
    np.testing.assert_allclose(points.get_offsets(), [[0, 30], [100 / 3, 20], [200 / 3, 10], [100, -10]])
    np.testing.assert_array_equal(points.get_array(), [0, 23, 0, 23])
    assert points.cmap.name == "jet"
    assert points.get_clim() == (0, 23)
    assert ax.get_xlabel() == "Duration (%)"
    assert not ax.get_lines()
    assert colorbar.get_ylim() == (0, 23)
    assert colorbar.get_yticklabels()[0].get_text() == "00"
    assert colorbar.get_yticklabels()[-1].get_text() == "23"
    references = ax.collections[1:]
    np.testing.assert_allclose([point.get_offsets()[0] for point in references], [[5, 28.5], [50, 15], [95, -7]])
    assert len({point.get_paths()[0].vertices.tobytes() for point in references}) == 3
    labels = [text.get_text() for text in ax.get_legend().get_texts()]
    assert labels == ["5%: 28.50 USD/MWh", "50%: 15.00 USD/MWh", "95%: -7.00 USD/MWh"]
    plt.close(fig)


def test_duration_invalid_hours_are_dropped_with_aligned_values(caplog):
    series = _prepare_duration_series(
        pd.Series([10, 100, 20, np.inf, 50]), pd.Series([24, "bad", 1, 25, np.nan])
    )
    assert series["value"].tolist() == [20, 10]
    assert series["hour"].tolist() == [0, 23]
    assert "discard" in caplog.text.lower()


def test_zonal_price_overlay_and_panels_honor_area_selection(tmp_path, monkeypatch):
    figures = {}

    def capture(fig, path, **kwargs):
        figures[os.path.basename(path)] = fig
        with open(path, "wb") as stream:
            stream.write(b"preview")

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", capture)
    prices = pd.DataFrame({
        "area_id": ["B", "B", "A", "A", "C", "C"],
        "hour": [1, 24] * 3,
        "pricing_status": ["available"] * 6,
        "marginal_price_USD_per_MWh": [10, -10, 30, 20, 0, 0],
    })
    result = SimpleNamespace(is_zonal=True, areas=["A", "B", "C"], marginal_prices_df=prices)
    before = prices.copy(deep=True)
    plot_duration_curves(result, generation_df=pd.DataFrame(), plots_dir=str(tmp_path))
    full_styles = {
        line.get_label(): (line.get_color(), line.get_linestyle())
        for line in figures["duration_curve_system_marginal_prices.png"].axes[0].lines
    }

    plot_duration_curves(
        result, generation_df=pd.DataFrame(), plots_dir=str(tmp_path), areas=["B", "A"]
    )

    panel = figures["duration_curve_zonal_marginal_prices.png"]
    assert [ax.get_gid() for ax in panel.axes[:-1]] == ["B", "A"]
    overlay = figures["duration_curve_system_marginal_prices.png"].axes[0]
    assert overlay.xaxis.label.get_fontsize() == 16
    assert overlay.yaxis.label.get_fontsize() == 16
    assert overlay.get_xticklabels()[0].get_fontsize() == 16
    assert [line.get_label() for line in overlay.lines] == ["B", "A"]
    np.testing.assert_array_equal(overlay.lines[0].get_xdata(), [0, 100])
    np.testing.assert_array_equal(overlay.lines[0].get_ydata(), [10, -10])
    np.testing.assert_array_equal(overlay.lines[1].get_ydata(), [30, 20])
    assert len({(line.get_color(), line.get_linestyle()) for line in overlay.lines}) == 2
    assert {
        line.get_label(): (line.get_color(), line.get_linestyle()) for line in overlay.lines
    } == {name: full_styles[name] for name in ["B", "A"]}
    pd.testing.assert_frame_equal(before, prices)


def test_omitted_areas_keeps_missing_prices_and_all_zones(tmp_path, monkeypatch):
    figures = {}

    def capture(fig, path, **kwargs):
        figures[os.path.basename(path)] = fig
        with open(path, "wb") as stream:
            stream.write(b"preview")

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", capture)
    result = SimpleNamespace(
        is_zonal=True,
        areas=["A", "B"],
        marginal_prices_df=pd.DataFrame({
            "area_id": ["A", "B"], "hour": [1, 1],
            "pricing_status": ["available", "unavailable"],
            "marginal_price_USD_per_MWh": [0.0, np.nan],
        }),
    )

    plot_duration_curves(result, generation_df=pd.DataFrame(), plots_dir=str(tmp_path))

    panel = figures["duration_curve_zonal_marginal_prices.png"]
    assert [ax.get_gid() for ax in panel.axes[:-1]] == ["A", "B"]
    np.testing.assert_array_equal(panel.axes[0].collections[0].get_offsets()[:, 1], [0])
    assert not panel.axes[1].collections
    assert any("unavailable" in text.get_text().lower() for text in panel.axes[1].texts)
    legend = figures["duration_curve_system_marginal_prices.png"].legends[0]
    assert any("B" in text.get_text() and "unavailable" in text.get_text() for text in legend.get_texts())
    assert figures["duration_curve_system_marginal_prices.png"].axes[0].lines[0].get_marker() != "None"


@pytest.mark.parametrize("areas", [[], ["A", "A"], ["unknown"], "A"])
def test_plot_results_rejects_bad_area_selection_before_writing(areas, tmp_path):
    result = SimpleNamespace(is_optimal=True, is_zonal=True, areas=["A", "B"])
    with pytest.raises(ValueError, match=r"area|Unknown"):
        plot_results(result, plots_dir=str(tmp_path), areas=areas)
    assert not list(tmp_path.iterdir())


def test_area_subset_does_not_change_system_aggregates_or_line_groups(tmp_path, monkeypatch):
    figures = {}
    bar_areas = []

    def capture(fig, path, **kwargs):
        figures[os.path.basename(path)] = fig
        with open(path, "wb") as stream:
            stream.write(b"preview")

    def area_plot(result, *, areas, **kwargs):
        bar_areas.append(areas)

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", capture)
    monkeypatch.setattr("sdom.analytic_tools._single._plot_capacity_donut", lambda *args: None)
    monkeypatch.setattr("sdom.analytic_tools._single._plot_capacity_generation_donuts", lambda *args: None)
    monkeypatch.setattr("sdom.analytic_tools._single._plot_heatmaps", lambda *args: None)
    monkeypatch.setattr("sdom.analytic_tools._single.plot_area_generation_stacks", area_plot)
    monkeypatch.setattr("sdom.analytic_tools._single.plot_area_capacity_stacks", area_plot)
    monkeypatch.setattr("sdom.analytic_tools._single.plot_line_flow_heatmap", lambda *args, **kwargs: None)
    zonal = pd.DataFrame({
        "Area": ["A", "A", "B", "B"], "Hour": [1, 2, 1, 2],
        "Load (MW)": [10, 20, 90, 180], "All Thermal Generation (MW)": [10, 20, 90, 180],
    })
    system = zonal.drop(columns="Area").groupby("Hour", as_index=False).sum()
    result = SimpleNamespace(
        is_optimal=True, is_zonal=True, areas=["A", "B"], generation_df=zonal,
        lines=[{"line_id": "L2"}, {"line_id": "L1"}, {"line_id": "L3"}],
        get_generation_dataframe=lambda: zonal.copy(),
        get_system_generation_dataframe=lambda: system.copy(),
        interregional_exchanges_df=pd.DataFrame({
            "line_id": ["L1", "L2"], "hour": [1, 1], "flow_signed_MW": [-10, 20],
        }),
    )
    plot_results(result, plots_dir=str(tmp_path), areas=["A"])

    assert bar_areas == [["A"], ["A"]]
    np.testing.assert_array_equal(
        figures["duration_curve_system_load.png"].axes[0].collections[0].get_offsets()[:, 1], [200, 100]
    )
    np.testing.assert_array_equal(
        figures["duration_curve_zonal_load.png"].axes[0].collections[0].get_offsets()[:, 1], [20, 10]
    )
    assert [ax.get_gid() for ax in figures["duration_curve_interregional_signed_flows.png"].axes[:-1]] == ["L1", "L2", "L3"]


def test_curtailment_hourly_calculation_excludes_hydro_and_retains_zero(tmp_path, monkeypatch):
    figures = {}
    monkeypatch.setattr("sdom.analytic_tools._duration_curves.save_figure", lambda fig, path: figures.setdefault(os.path.basename(path), fig))
    frame = pd.DataFrame({
        "Hour": [1, 2, 3],
        "Solar PV Generation (MW)": [10, 0, 5],
        "Wind Generation (MW)": [20, 0, 15],
        "Solar PV Curtailment (MW)": [5, 0, 10],
        "Wind Curtailment (MW)": [5, 0, 10],
        "Hydro Curtailment (MW)": [1000, 1000, 1000],
    })
    plot_duration_curves(SimpleNamespace(is_zonal=False), generation_df=frame, plots_dir=str(tmp_path))
    np.testing.assert_allclose(figures["duration_curve_vre_curtailment_mw.png"].axes[0].collections[0].get_offsets()[:, 1], [20, 10, 0])
    np.testing.assert_allclose(figures["duration_curve_vre_curtailment_pct.png"].axes[0].collections[0].get_offsets()[:, 1], [50, 25, 0])
    for fig in figures.values():
        plt.close(fig)


@pytest.mark.parametrize("data", [
    pd.DataFrame(),
    pd.DataFrame({"area_id": ["A1"], "price": [10]}),
    pd.DataFrame({"area_id": ["A1"], "price": ["bad"], "hour": [1]}),
])
def test_duration_optional_groups_keep_known_missing_groups(data, tmp_path, caplog):
    plotted = _plot_grouped_duration_curves(
        data, group_column="area_id", value_column="price",
        title="Prices", y_label="USD/MWh", output_path=str(tmp_path / "prices.png"),
    )
    assert plotted == (not data.empty)
    assert (tmp_path / "prices.png").exists() == (not data.empty)
    assert "missing" in caplog.text.lower()


def test_duration_invalid_group_does_not_suppress_eligible_panel(tmp_path, monkeypatch, caplog):
    captured = []

    def capture(fig, path, **kwargs):
        captured.append(fig)
        with open(path, "wb") as stream:
            stream.write(b"preview")

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", capture)
    assert _plot_grouped_duration_curves(
        pd.DataFrame({"area_id": ["A1", "A2"], "price": ["bad", -10], "hour": [1, 24]}),
        group_column="area_id", value_column="price", title="Prices",
        y_label="USD/MWh", output_path=str(tmp_path / "prices.png"),
    )
    assert [ax.get_gid() for ax in captured[0].axes[:-1]] == ["A1", "A2"]
    assert not captured[0].axes[0].collections
    assert captured[0].axes[1].collections[0].get_offsets()[0, 1] == -10
    assert "missing data" in caplog.text
    plt.close(captured[0])


def test_parametric_per_case_inherits_duration_scatter_contract(tmp_path, monkeypatch):
    study = SimpleNamespace(
        case_metadata=[{"case_name": "case_1", "case_index": 0, "sweep": 1.0}],
        output_dir=str(tmp_path),
    )
    result = _FakeResult()
    figures = {}

    def capture(fig, path):
        figures[os.path.basename(path)] = fig

    monkeypatch.setattr("sdom.analytic_tools._duration_curves.save_figure", capture)
    monkeypatch.setattr(
        "sdom.analytic_tools._parametric._extract_cost_series",
        lambda summary_df: ({"Thermal": 1.0}, {"Thermal": 1.0}),
    )
    plot_parametric_results(study, [result], group_by="sweep", plot_per_case=True)
    for filename in (
        "duration_curve_total_thermal_generation.png",
        "duration_curve_vre_curtailment_mw.png",
        "duration_curve_vre_curtailment_pct.png",
    ):
        ax = figures[filename].axes[0]
        assert not ax.lines
        assert ax.get_xlabel() == "Duration (%)"
        assert ax.collections[0].cmap.name == "jet"
        assert ax.collections[0].get_clim() == (0, 23)
        assert len(ax.get_legend().get_texts()) == 3
    for fig in figures.values():
        plt.close(fig)


# ---------------------------------------------------------------------------
# _parametric.py tests
# ---------------------------------------------------------------------------
from sdom.analytic_tools._parametric import (
    _available_dims,
    _plot_cost_comparison_bars,
    _plot_grouped_stacked_bars,
    _save_parametric_figure,
    _split_into_chunks,
    plot_parametric_results,
)


def _make_parametric_tech_df(hues=None) -> pd.DataFrame:
    """Create small long-form technology data for parametric plot tests."""
    hues = hues or ["_all_"]
    rows = []
    values = {
        "Thermal": 1200.0,
        "Solar PV": 2400.0,
        "Wind": 1800.0,
        "PHS": 300.0,
        "H2": 100.0,
    }
    for group_idx, group in enumerate(["GenMix_Target=0.0", "GenMix_Target=1.0"]):
        for hue_idx, hue in enumerate(hues):
            for tech, value in values.items():
                rows.append(
                    {
                        "group_label": group,
                        "hue_label": hue,
                        "technology": tech,
                        "capacity_mw": value + 100 * group_idx + 10 * hue_idx,
                        "generation_mwh": (value + 100 * group_idx + 10 * hue_idx) * 1000,
                    }
                )
    return pd.DataFrame(rows)


def _make_parametric_cost_df(hues=None) -> pd.DataFrame:
    """Create small long-form cost data for parametric plot tests."""
    hues = hues or ["_all_"]
    rows = []
    values = {
        "Thermal": (1_200_000.0, 120_000.0),
        "Solar PV": (2_400_000.0, 24_000.0),
        "Wind": (1_800_000.0, 36_000.0),
        "PHS": (300_000.0, 12_000.0),
        "H2": (100_000.0, 8_000.0),
    }
    for group_idx, group in enumerate(["GenMix_Target=0.0", "GenMix_Target=1.0"]):
        for hue_idx, hue in enumerate(hues):
            for tech, (capex, opex) in values.items():
                rows.append(
                    {
                        "group_label": group,
                        "hue_label": hue,
                        "technology": tech,
                        "capex_usd": capex + 1000 * group_idx + 100 * hue_idx,
                        "opex_usd": opex + 100 * group_idx + 10 * hue_idx,
                    }
                )
    return pd.DataFrame(rows)


class TestParametricLegends:
    def test_plot_per_case_false_skips_duration_curve_generation(self, tmp_path, monkeypatch):
        """Per-case plotting opt-out suppresses all plot_results artifacts."""
        study = SimpleNamespace(
            case_metadata=[{"case_name": "case_1", "case_index": 0, "sweep": 1.0}],
            output_dir=str(tmp_path),
        )
        result = _FakeResult()
        called = []

        monkeypatch.setattr(
            "sdom.analytic_tools._parametric.plot_results",
            lambda *args, **kwargs: called.append((args, kwargs)),
        )
        monkeypatch.setattr(
            "sdom.analytic_tools._parametric._extract_cost_series",
            lambda summary_df: ({"Thermal": 1.0}, {"Thermal": 1.0}),
        )

        plot_parametric_results(
            study,
            [result],
            group_by="sweep",
            plot_per_case=False,
        )

        assert called == []
        assert not (tmp_path / "case_1" / "plots").exists()

    def test_save_parametric_figure_writes_png_with_extra_artists(self, tmp_path):
        """The parametric save helper should write figures with outside legends."""
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1], label="Thermal")
        legend = ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), title="Technology")
        ax.add_artist(legend)
        output_path = tmp_path / "capacity_comparison.png"

        _save_parametric_figure(fig, str(output_path), extra_artists=[legend])

        assert output_path.is_file()
        assert output_path.stat().st_size > 0

    def test_grouped_stacked_bars_exports_technology_legend(self, tmp_path, monkeypatch):
        """Capacity/generation plots should save outside technology legends."""
        captured = {}

        def fake_save(fig, output_path, *, extra_artists=None):
            import matplotlib.pyplot as plt

            captured["output_path"] = output_path
            captured["legend_titles"] = [artist.get_title().get_text() for artist in extra_artists]
            plt.close(fig)

        monkeypatch.setattr("sdom.analytic_tools._parametric._save_parametric_figure", fake_save)
        tech_order = ["Thermal", "Solar PV", "Wind", "PHS", "H2"]
        color_map = {tech: f"C{i}" for i, tech in enumerate(tech_order)}

        _plot_grouped_stacked_bars(
            tech_df=_make_parametric_tech_df(),
            value_col="capacity_mw",
            groups=["GenMix_Target=0.0", "GenMix_Target=1.0"],
            hues=["_all_"],
            tech_order=tech_order,
            color_map=color_map,
            title="Installed Capacity by Technology — Sensitivity Analysis",
            ylabel="Capacity (GW)",
            unit_divisor=1000.0,
            output_path=str(tmp_path / "capacity_comparison.png"),
        )

        assert captured["output_path"].endswith("capacity_comparison.png")
        assert captured["legend_titles"] == ["Technology"]

    def test_grouped_stacked_bars_exports_technology_and_hue_legends(self, tmp_path, monkeypatch):
        """Scenario/hue legends should remain visible with technology legends."""
        captured = {}

        def fake_save(fig, output_path, *, extra_artists=None):
            import matplotlib.pyplot as plt

            captured["legend_titles"] = [artist.get_title().get_text() for artist in extra_artists]
            plt.close(fig)

        monkeypatch.setattr("sdom.analytic_tools._parametric._save_parametric_figure", fake_save)
        tech_order = ["Thermal", "Solar PV", "Wind", "PHS", "H2"]
        color_map = {tech: f"C{i}" for i, tech in enumerate(tech_order)}

        _plot_grouped_stacked_bars(
            tech_df=_make_parametric_tech_df(hues=["scenario_a", "scenario_b"]),
            value_col="generation_mwh",
            groups=["GenMix_Target=0.0", "GenMix_Target=1.0"],
            hues=["scenario_a", "scenario_b"],
            tech_order=tech_order,
            color_map=color_map,
            title="Annual Generation by Technology — Sensitivity Analysis",
            ylabel="Generation (TWh)",
            unit_divisor=1e6,
            output_path=str(tmp_path / "generation_comparison.png"),
        )

        assert captured["legend_titles"] == ["Technology", "Scenarios"]

    def test_cost_comparison_exports_all_outside_legends(self, tmp_path, monkeypatch):
        """Cost plots should save technology, cost-type, and scenario legends."""
        captured = {}

        def fake_save(fig, output_path, *, extra_artists=None):
            import matplotlib.pyplot as plt

            captured["legend_titles"] = [artist.get_title().get_text() for artist in extra_artists]
            plt.close(fig)

        monkeypatch.setattr("sdom.analytic_tools._parametric._save_parametric_figure", fake_save)
        tech_order = ["Thermal", "Solar PV", "Wind", "PHS", "H2"]
        color_map = {tech: f"C{i}" for i, tech in enumerate(tech_order)}

        _plot_cost_comparison_bars(
            cost_df=_make_parametric_cost_df(hues=["scenario_a", "scenario_b"]),
            groups=["GenMix_Target=0.0", "GenMix_Target=1.0"],
            hues=["scenario_a", "scenario_b"],
            tech_order=tech_order,
            color_map=color_map,
            title="CAPEX and OPEX by Technology — Sensitivity Analysis",
            ylabel="Cost ($M USD)",
            unit_divisor=1e6,
            output_path=str(tmp_path / "cost_comparison.png"),
        )

        assert captured["legend_titles"] == ["Technology", "Cost type", "Scenarios"]


class TestParametricHelpers:
    # --- _split_into_chunks ---

    def test_split_no_split_needed(self):
        groups = ["g1", "g2", "g3"]
        chunks = _split_into_chunks(groups, max_cases_per_figure=24, n_hues=4)
        assert chunks == [["g1", "g2", "g3"]]

    def test_split_exact_boundary(self):
        groups = [f"g{i}" for i in range(6)]
        # 6 groups × 4 hues = 24 = max → no split
        chunks = _split_into_chunks(groups, max_cases_per_figure=24, n_hues=4)
        assert len(chunks) == 1

    def test_split_triggers_when_exceeded(self):
        groups = [f"g{i}" for i in range(7)]
        # 7 × 4 = 28 > 24 → split needed; max_per_chunk = 24//4 = 6
        chunks = _split_into_chunks(groups, max_cases_per_figure=24, n_hues=4)
        assert len(chunks) == 2
        assert len(chunks[0]) == 6
        assert len(chunks[1]) == 1

    def test_split_all_groups_preserved(self):
        groups = [f"g{i}" for i in range(10)]
        chunks = _split_into_chunks(groups, max_cases_per_figure=6, n_hues=3)
        # max_per_chunk = 6 // 3 = 2
        flat = [g for chunk in chunks for g in chunk]
        assert flat == groups

    def test_split_zero_hues_treated_as_one(self):
        groups = ["a", "b"]
        chunks = _split_into_chunks(groups, max_cases_per_figure=1, n_hues=0)
        # Each chunk should have 1 group
        assert all(len(c) == 1 for c in chunks)

    # --- _available_dims ---

    def test_available_dims_extracts_keys(self):
        meta = [
            {"case_name": "c1", "case_index": 0, "GenMix_Target": 0.9, "P_Capex": 1.0},
            {"case_name": "c2", "case_index": 1, "GenMix_Target": 0.7, "P_Capex": 1.3},
        ]
        dims = _available_dims(meta)
        assert "GenMix_Target" in dims
        assert "P_Capex" in dims
        assert "case_name" not in dims
        assert "case_index" not in dims

    def test_available_dims_empty_meta(self):
        assert _available_dims([]) == set()


# ---------------------------------------------------------------------------
# ParametricStudy.case_metadata tests
# ---------------------------------------------------------------------------
from sdom.parametric import ParametricStudy


class TestParametricStudyCaseMetadata:
    def test_case_metadata_empty_before_run(self):
        """case_metadata should be an empty list before run() is called."""
        # We cannot easily instantiate ParametricStudy without real data,
        # so we test via the internal structure instead.
        study = _make_stub_study()
        assert study.case_metadata == []

    def test_case_metadata_populated_after_build(self):
        """After _build_case_dicts the internal list should be non-empty."""
        study = _make_stub_study()
        # Register sweeps and call _build_case_dicts directly (avoids running solver)
        study.add_scalar_sweep("scalars", "GenMix_Target", [0.8, 0.9])
        study.add_storage_factor_sweep("P_Capex", [1.0, 1.3])
        case_dicts = study._build_case_dicts()
        # Simulate what run() does
        study._case_metadata = [
            {
                "case_name": cd["case_name"],
                "case_index": cd["case_index"],
                **{param: val for _, param, val in cd.get("scalar_mutations", [])},
                **{param: factor for param, factor in cd.get("storage_factor_mutations", [])},
                **{ts_key: factor for ts_key, factor in cd.get("ts_mutations", [])},
            }
            for cd in case_dicts
        ]
        meta = study.case_metadata
        assert len(meta) == 4  # 2 × 2
        for entry in meta:
            assert "case_name" in entry
            assert "case_index" in entry
            assert "GenMix_Target" in entry
            assert "P_Capex" in entry

    def test_output_dir_property(self):
        study = _make_stub_study(output_dir="/tmp/out")
        assert study.output_dir == "/tmp/out"

    def test_output_dir_none_by_default(self):
        study = _make_stub_study()
        assert study.output_dir is None

    @pytest.mark.parametrize("plot_per_case, expected_calls", [(True, 1), (False, 0)])
    def test_plot_per_case_controls_single_result_plot_dispatch(
        self, tmp_path, monkeypatch, plot_per_case, expected_calls
    ):
        """Parametric plotting delegates per-case artifacts only when enabled."""
        from sdom.analytic_tools._parametric import plot_parametric_results

        study = _make_stub_study(output_dir=str(tmp_path))
        study._case_metadata = [
            {"case_name": "case_1", "case_index": 0, "GenMix_Target": 0.8}
        ]
        calls = []

        def fake_plot_results(result, output_dir=None, plots_dir=None, **kwargs):
            calls.append((result, output_dir, plots_dir, kwargs))

        monkeypatch.setattr(
            "sdom.analytic_tools._parametric.plot_results", fake_plot_results
        )
        monkeypatch.setattr(
            "sdom.analytic_tools._parametric._plot_grouped_stacked_bars",
            lambda **kwargs: None,
        )
        monkeypatch.setattr(
            "sdom.analytic_tools._parametric._plot_curtailment_bars",
            lambda **kwargs: None,
        )
        monkeypatch.setattr(
            "sdom.analytic_tools._parametric._plot_cost_comparison_bars",
            lambda **kwargs: None,
        )
        monkeypatch.setattr(
            "sdom.analytic_tools._parametric._extract_capacity_series",
            lambda summary_df: {"Thermal": 1.0},
        )
        monkeypatch.setattr(
            "sdom.analytic_tools._parametric._extract_generation_series",
            lambda summary_df: {"Thermal": 1.0},
        )
        monkeypatch.setattr(
            "sdom.analytic_tools._parametric._extract_curtailment",
            lambda summary_df: (0.0, 0.0),
        )
        monkeypatch.setattr(
            "sdom.analytic_tools._parametric._extract_cost_series",
            lambda summary_df: ({"Thermal": 1.0}, {"Thermal": 1.0}),
        )

        plot_parametric_results(
            study,
            [_FakeResult()],
            group_by="GenMix_Target",
            plot_per_case=plot_per_case,
            page_size="slide_4_3",
            max_panels_per_page=2,
            areas=["A1"],
        )

        assert len(calls) == expected_calls
        if calls:
            assert calls[0][2] == os.path.join(str(tmp_path), "case_1", "plots")
            assert calls[0][3]["areas"] == ["A1"]
            assert calls[0][3]["page_size"] == "slide_4_3"
            assert calls[0][3]["max_panels_per_page"] == 2


# ---------------------------------------------------------------------------
# Helpers for ParametricStudy stub
# ---------------------------------------------------------------------------

def _make_stub_study(output_dir=None):
    """Create a ParametricStudy with minimal (empty) base data for unit tests."""
    import pandas as pd

    base_data = {
        "scalars": pd.DataFrame({"Value": {"GenMix_Target": 0.8, "P_Capex": 1.0}}),
        "storage_data": pd.DataFrame({"P_Capex": {"BatteryA": 100.0}}),
    }
    solver_config = {}
    return ParametricStudy(
        base_data=base_data,
        solver_config=solver_config,
        output_dir=output_dir,
    )
