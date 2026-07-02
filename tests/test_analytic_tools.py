"""Tests for sdom.analytic_tools.

Covers:
- _colors.py: color-map completeness and dynamic storage assignment
- _single.py: plot_results() creates expected files in the correct directory
- _parametric.py: _split_into_chunks() and _available_dims() / case_metadata
"""

from __future__ import annotations

import os
import tempfile

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


# ---------------------------------------------------------------------------
# _parametric.py tests
# ---------------------------------------------------------------------------
from sdom.analytic_tools._parametric import (
    _available_dims,
    _plot_cost_comparison_bars,
    _plot_grouped_stacked_bars,
    _save_parametric_figure,
    _split_into_chunks,
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
            captured["output_path"] = output_path
            captured["legend_titles"] = [artist.get_title().get_text() for artist in extra_artists]

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
            captured["legend_titles"] = [artist.get_title().get_text() for artist in extra_artists]

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
            captured["legend_titles"] = [artist.get_title().get_text() for artist in extra_artists]

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
