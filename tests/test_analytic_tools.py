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
    _DURATION_CURVE_FONT_SIZE_INCREASE,
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
            pd.Series([5.0, 3.0], index=[1, 2]),
            title="Duration curve",
            y_label="MW",
            output_path=str(tmp_path / "duration_curve.png"),
        )

        ax = captured["fig"].axes[0]
        expected_size = plt.rcParams["font.size"] + _DURATION_CURVE_FONT_SIZE_INCREASE
        assert ax.xaxis.label.get_size() == expected_size
        assert ax.yaxis.label.get_size() == expected_size
        assert ax.get_xticklabels()[0].get_size() == expected_size
        assert ax.get_yticklabels()[0].get_size() == expected_size
        plt.close(captured["fig"])

    def test_prepare_duration_series_sorts_values_and_creates_one_based_ranks(self):
        series = _prepare_duration_series(pd.Series([2, "bad", 5, 3]))

        assert series is not None
        assert series.tolist() == [5.0, 3.0, 2.0]
        assert series.index.tolist() == [1, 2, 3]
        assert series.index.name == "Duration-curve position"

    def test_prepare_duration_series_returns_none_for_empty_or_non_numeric_data(self):
        assert _prepare_duration_series(pd.Series([], dtype=object)) is None
        assert _prepare_duration_series(pd.Series(["bad", None])) is None

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

    def test_grouped_duration_curves_use_independent_color_and_linestyle_cycles(
        self, tmp_path, monkeypatch
    ):
        import matplotlib.pyplot as plt

        captured = {}

        def fake_save(fig, output_path):
            captured["fig"] = fig

        monkeypatch.setattr("sdom.analytic_tools._duration_curves.save_figure", fake_save)
        data = pd.DataFrame(
            {
                "area_id": [f"A{index}" for index in range(5)],
                "price": [float(index) for index in range(5)],
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
        lines = captured["fig"].axes[0].get_lines()
        assert len(lines) == 5
        assert captured["fig"].axes[0].get_legend() is not None
        assert len({line.get_color() for line in lines}) > 1
        assert len({line.get_linestyle() for line in lines}) > 1
        plt.close(captured["fig"])


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

        def fake_plot_results(result, output_dir=None, plots_dir=None):
            calls.append((result, output_dir, plots_dir))

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
        )

        assert len(calls) == expected_calls
        if calls:
            assert calls[0][2] == os.path.join(str(tmp_path), "case_1", "plots")


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
