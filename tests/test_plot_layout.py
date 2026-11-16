"""Solver-free checks for bounded plotting layouts."""

import os
import struct
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from sdom.analytic_tools._duration_curves import _plot_grouped_duration_curves
from sdom.analytic_tools._layout import LayoutOptions, plan_layout
from sdom.analytic_tools._utils import save_figure_pages


@pytest.mark.parametrize("count", [1, 2, 3, 7, 14, 18, 30, 100])
def test_layout_preserves_group_inventory_with_bounded_readable_panels(count):
    plan = plan_layout(count)

    assert plan.width == pytest.approx(40 / 3)
    assert plan.height == pytest.approx(7.5)
    assert plan.panel_width >= 2.9
    assert plan.panel_height >= 1.2
    assert [index for page in plan.pages for index in page] == list(range(count))
    assert len(plan.pages) == (count + plan.capacity - 1) // plan.capacity


def test_layout_cap_limits_panels_without_forcing_an_unreadable_grid():
    automatic = plan_layout(14)
    capped = plan_layout(14, max_panels_per_page=3)

    assert automatic.columns == 3
    assert automatic.rows == 2
    assert len(automatic.pages) == 3
    assert all(len(page) <= 3 for page in capped.pages)
    assert plan_layout(14, max_panels_per_page=100) == automatic


@pytest.mark.parametrize("page_size", ["slide_4_3", "a4_landscape", "letter_landscape", (12, 8)])
def test_layout_accepts_standard_and_custom_page_sizes(page_size):
    plan = plan_layout(14, page_size=page_size)

    assert len(plan.pages) >= 1
    assert plan.panel_width >= 2.9
    assert plan.panel_height >= 1.2


@pytest.mark.parametrize(
    "options",
    [
        {"page_size": "unknown"},
        {"page_size": (0, 8)},
        {"page_size": (12, float("inf"))},
        {"page_size": (True, 8)},
        {"page_size": (2, 2)},
        {"max_panels_per_page": 0},
        {"max_panels_per_page": True},
        {"max_panels_per_page": 1.5},
        {"ncols": 0},
        {"ncols": 20},
        {"panel_aspect": -1},
    ],
)
def test_layout_rejects_invalid_or_impossible_options(options):
    with pytest.raises(ValueError):
        plan_layout(14, **options)


def test_paginated_output_removes_only_owned_stale_pages(tmp_path):
    output = str(tmp_path / "curves.png")
    unrelated = tmp_path / "other.png"
    unrelated.write_bytes(b"keep")

    def pages(count):
        for _ in range(count):
            yield plt.figure(figsize=(2, 2))

    save_figure_pages(pages(3), output, page_count=3)
    assert (tmp_path / "curves_part3.png").exists()
    save_figure_pages(pages(1), output, page_count=1)
    assert (tmp_path / "curves.png").exists()
    assert not list(tmp_path.glob("curves_part*.png"))
    assert unrelated.read_bytes() == b"keep"


def test_paginated_output_failure_preserves_previous_family_and_closes_figures(tmp_path, monkeypatch):
    output = tmp_path / "curves.png"
    save_figure_pages(iter([plt.figure(figsize=(2, 2))]), str(output), page_count=1)
    previous = output.read_bytes()
    before = plt.get_fignums()

    def failing_pages():
        yield plt.figure(figsize=(2, 2))
        raise RuntimeError("render failed")

    with pytest.raises(RuntimeError, match="render failed"):
        save_figure_pages(failing_pages(), str(output), page_count=2)
    assert output.read_bytes() == previous
    assert plt.get_fignums() == before
    assert not list(tmp_path.glob("curves_part*.png"))


@pytest.mark.parametrize("count", [1, 2, 3, 7, 14, 18, 30, 100])
def test_grouped_rendering_keeps_every_group_once_and_closes_each_page(count, tmp_path, monkeypatch):
    seen = []
    existing_figures = plt.get_fignums()

    def capture(fig, path, **kwargs):
        assert plt.get_fignums() == existing_figures
        seen.extend(ax.get_gid() for ax in fig.axes[:-1])
        assert fig.get_size_inches() == pytest.approx((40 / 3, 7.5))
        assert fig.axes[-1].get_xlim() == (0, 23)
        for ax in fig.axes[:-1]:
            assert ax.collections[0].get_clim() == (0, 23)
        with open(path, "wb") as stream:
            stream.write(b"preview")

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", capture)
    names = [f"A{index:03d}" for index in range(count)]
    frame = pd.DataFrame({"area_id": names[::-1], "hour": [1] * count, "price": range(count)})
    _plot_grouped_duration_curves(
        frame,
        group_column="area_id",
        value_column="price",
        title="Prices",
        y_label="USD/MWh",
        output_path=str(tmp_path / "curves.png"),
    )
    assert seen == names
    assert plt.get_fignums() == existing_figures


@pytest.mark.parametrize("page_size", ["slide_4_3", "a4_landscape", "letter_landscape", (12, 8)])
def test_grouped_rendering_fits_each_standard_page_size(page_size, tmp_path, monkeypatch):
    seen = []

    def capture(fig, path, **kwargs):
        seen.extend(ax.get_gid() for ax in fig.axes[:-1])
        with open(path, "wb") as stream:
            stream.write(b"preview")

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", capture)
    names = [f"A{index:02d}" for index in range(14)]
    frame = pd.DataFrame({"area_id": names, "hour": [1] * 14, "price": range(14)})
    _plot_grouped_duration_curves(
        frame,
        group_column="area_id",
        value_column="price",
        title="Prices",
        y_label="USD/MWh",
        output_path=str(tmp_path / "curves.png"),
        options=LayoutOptions(page_size=page_size),
    )
    assert seen == names


def test_bounded_export_keeps_physical_dimensions_with_global_tight_bbox(tmp_path):
    path = tmp_path / "curves.png"
    with plt.rc_context({"savefig.bbox": "tight"}):
        save_figure_pages(iter([plt.figure(figsize=(2, 2))]), str(path), page_count=1)
    assert struct.unpack("!II", path.read_bytes()[16:24]) == (600, 600)


def test_publish_failure_rolls_back_previous_pages_and_manifest(tmp_path, monkeypatch):
    path = str(tmp_path / "curves.png")
    save_figure_pages(iter([plt.figure(figsize=(2, 2)), plt.figure(figsize=(2, 2))]), path, page_count=2)
    previous = {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    replace = os.replace
    failed = False

    def fail_second_publish(source, destination):
        nonlocal failed
        if not failed and Path(source).name == "curves_part2.png" and Path(destination).parent == tmp_path:
            failed = True
            raise OSError("publish failed")
        return replace(source, destination)

    monkeypatch.setattr("sdom.analytic_tools._utils.os.replace", fail_second_publish)
    with pytest.raises(OSError, match="publish failed"):
        save_figure_pages(
            iter([plt.figure(figsize=(2, 2)), plt.figure(figsize=(2, 2)), plt.figure(figsize=(2, 2))]),
            path,
            page_count=3,
        )
    assert {file.name: file.read_bytes() for file in tmp_path.iterdir()} == previous
