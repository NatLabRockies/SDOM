"""Tests for unit metadata attached to public optimization result attributes."""

from __future__ import annotations

import matplotlib
import pandas as pd

matplotlib.use("Agg")

from sdom.analytic_tools._single import _plot_capacity_donut
from sdom.analytic_tools._zonal import plot_area_capacity_stacks
from sdom.results import OptimizationResults


def test_single_capacity_plot_title_uses_result_attribute_unit(monkeypatch, tmp_path):
    """Single-result plot labels should prefer result metadata over legacy units."""
    result = OptimizationResults(
        summary_df=pd.DataFrame(
            [{"Metric": "Capacity", "Technology": "Wind", "Optimal Value": 50.0}]
        ),
        attribute_units={"capacity": "MW"},
    )
    captured = {}

    def capture_figure(fig, _path):
        captured["title"] = fig.axes[0].get_title()

    monkeypatch.setattr("sdom.analytic_tools._single.save_figure", capture_figure)

    _plot_capacity_donut(result, str(tmp_path))

    assert captured["title"] == "Capacity per technology (MW)"


def test_single_capacity_plot_title_falls_back_without_metadata(monkeypatch, tmp_path):
    """Single-result plots should retain their legacy labels without metadata."""
    result = OptimizationResults(
        summary_df=pd.DataFrame(
            [{"Metric": "Capacity", "Technology": "Wind", "Optimal Value": 50.0}]
        )
    )
    captured = {}

    def capture_figure(fig, _path):
        captured["title"] = fig.axes[0].get_title()

    monkeypatch.setattr("sdom.analytic_tools._single.save_figure", capture_figure)

    _plot_capacity_donut(result, str(tmp_path))

    assert captured["title"] == "Capacity per technology (MW)"


def test_zonal_capacity_plot_label_uses_result_attribute_unit():
    """Zonal capacity labels should prefer metadata while retaining MW values."""
    result = OptimizationResults(
        is_zonal=True,
        areas=["A1"],
        area_capacity={"A1": {"Solar PV": 20.0}},
        attribute_units={"capacity": "MW"},
    )

    fig = plot_area_capacity_stacks(result, include_storage=False)

    assert fig.axes[0].get_ylabel() == "Installed capacity (MW)"
