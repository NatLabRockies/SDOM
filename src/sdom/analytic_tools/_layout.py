"""Bounded, deterministic page planning and measured typography for plot grids."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Integral, Real
from typing import TypeAlias

from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.text import Text

PAGE_SIZES = {
    "slide_16_9": (40 / 3, 7.5),
    "slide_4_3": (10.0, 7.5),
    "a4_landscape": (297 / 25.4, 210 / 25.4),
    "letter_landscape": (11.0, 8.5),
}
FONT_SIZE = 16
LEFT, RIGHT, TOP, BOTTOM = 0.40, 0.16, 0.80, 1.40
COLUMN_GAP, ROW_GAP = 0.30, 0.25
PANEL_LEFT, PANEL_RIGHT, PANEL_TOP, PANEL_BOTTOM = 0.66, 0.07, 0.60, 0.67
PageSize: TypeAlias = str | tuple[float, float]


class LayoutError(ValueError):
    """Indicate that measured decorations cannot fit a readable page."""


@dataclass(frozen=True)
class LayoutOptions:
    """Carry explicit per-call layout choices without global plotting state."""

    page_size: PageSize = "slide_16_9"
    max_panels_per_page: int | None = None
    ncols: int | None = None
    panel_aspect: float = 2.2

    def plan(self, count: int, *, capacity: int | None = None) -> PageLayout:
        """Resolve a page plan, optionally tightening the panel ceiling after measurement."""
        limit = self.max_panels_per_page
        if capacity is not None:
            limit = min(limit, capacity) if limit is not None else capacity
        return plan_layout(
            count,
            page_size=self.page_size,
            max_panels_per_page=limit,
            ncols=self.ncols,
            panel_aspect=self.panel_aspect,
        )


@dataclass(frozen=True)
class PageLayout:
    """Store physical page geometry and ordered group indices for each page."""

    width: float
    height: float
    rows: int
    columns: int
    panel_width: float
    panel_height: float
    capacity: int
    pages: tuple[tuple[int, ...], ...]

    def bounds(self, index: int) -> tuple[float, float, float, float]:
        """Return one data-axis rectangle in normalized figure coordinates."""
        row, column = divmod(index, self.columns)
        slot_width = (self.width - LEFT - RIGHT - (self.columns - 1) * COLUMN_GAP) / self.columns
        slot_height = (self.height - TOP - BOTTOM - (self.rows - 1) * ROW_GAP) / self.rows
        left = LEFT + column * (slot_width + COLUMN_GAP) + PANEL_LEFT
        bottom = self.height - TOP - (row + 1) * slot_height - row * ROW_GAP + PANEL_BOTTOM
        return (
            left / self.width,
            bottom / self.height,
            self.panel_width / self.width,
            self.panel_height / self.height,
        )


def page_dimensions(page_size: PageSize) -> tuple[float, float]:
    """Resolve a preset or validate positive finite physical dimensions in inches."""
    if isinstance(page_size, str):
        if page_size not in PAGE_SIZES:
            raise ValueError(
                f"Unknown page_size {page_size!r}; choose from {tuple(PAGE_SIZES)} or (width, height)."
            )
        return PAGE_SIZES[page_size]
    if (
        not isinstance(page_size, tuple)
        or len(page_size) != 2
        or any(
            isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value <= 0
            for value in page_size
        )
    ):
        raise ValueError("page_size must be a named preset or two positive finite dimensions in inches.")
    return float(page_size[0]), float(page_size[1])


def plan_layout(
    n_groups: int,
    *,
    page_size: PageSize = "slide_16_9",
    max_panels_per_page: int | None = None,
    ncols: int | None = None,
    panel_aspect: float = 2.2,
) -> PageLayout:
    """Choose feasible grids by page count, panel aspect, then unused cells.

    Parameters
    ----------
    n_groups : int
        Positive number of groups, including missing-data placeholders.
    page_size : str or tuple of float, optional
        Complete maximum canvas in inches, including annotations.
    max_panels_per_page : int or None, optional
        Optional positive ceiling, never a request to shrink panels.
    ncols : int or None, optional
        Exact column count, or automatic columns.
    panel_aspect : float, optional
        Preferred data-axis width divided by height, after readability bounds.

    Returns
    -------
    PageLayout
        Stable grid geometry with data axes at least 2.9 by 1.2 inches.

    Raises
    ------
    ValueError
        If options are invalid or cannot fit one readable panel.
    """
    for name, value in (
        ("n_groups", n_groups),
        ("max_panels_per_page", max_panels_per_page),
        ("ncols", ncols),
    ):
        if value is not None and (isinstance(value, bool) or not isinstance(value, Integral) or value <= 0):
            raise ValueError(
                f"{name} must be a positive integer" + (" or None." if name != "n_groups" else ".")
            )
    if (
        isinstance(panel_aspect, bool)
        or not isinstance(panel_aspect, Real)
        or not math.isfinite(panel_aspect)
        or panel_aspect <= 0
    ):
        raise ValueError("panel_aspect must be a positive finite width/height ratio.")
    width, height = page_dimensions(page_size)
    limit = min(n_groups, max_panels_per_page or n_groups)
    options = []
    for rows in range(1, limit + 1):
        panel_height = (height - TOP - BOTTOM - (rows - 1) * ROW_GAP) / rows - PANEL_TOP - PANEL_BOTTOM
        if panel_height < 1.2:
            break
        columns_to_try = (ncols,) if ncols is not None else range(1, limit + 1)
        for columns in columns_to_try:
            panel_width = (
                (width - LEFT - RIGHT - (columns - 1) * COLUMN_GAP) / columns - PANEL_LEFT - PANEL_RIGHT
            )
            if panel_width < 2.9:
                break
            capacity = min(rows * columns, limit)
            page_count = math.ceil(n_groups / capacity)
            score = (
                page_count,
                abs(math.log((panel_width / panel_height) / panel_aspect)),
                page_count * rows * columns - n_groups,
                -panel_width * panel_height,
            )
            options.append((score, rows, columns, panel_width, panel_height, capacity))
    if not options:
        raise ValueError(
            f"page_size={page_size!r} and ncols={ncols!r} cannot fit 2.9 x 1.2 inch panels. "
            "Choose a larger page_size or fewer columns."
        )
    _, rows, columns, panel_width, panel_height, capacity = min(options)
    return PageLayout(
        width,
        height,
        rows,
        columns,
        panel_width,
        panel_height,
        capacity,
        tuple(tuple(range(start, min(start + capacity, n_groups))) for start in range(0, n_groups, capacity)),
    )


def wrap_text(text: str, *, figure: Figure, width: float, fontsize: float = FONT_SIZE) -> str:
    """Wrap complete text using rendered font widths, including unbroken identifiers."""
    font = FontProperties(size=fontsize)
    measurement = Text(0, 0, fontproperties=font)
    measurement.set_figure(figure)

    def measured_width(value: str) -> float:
        measurement.set_text(value)
        return measurement.get_window_extent().width

    lines: list[str] = []
    current = ""
    for word in text.split():
        proposal = f"{current} {word}".strip()
        if measured_width(proposal) <= width * figure.dpi:
            current = proposal
            continue
        if current:
            lines.append(current)
        current = ""
        for character in word:
            if measured_width(current + character) > width * figure.dpi:
                lines.append(current)
                current = character
            else:
                current += character
    if current:
        lines.append(current)
    return "\n".join(lines)


def validate_page(figure: Figure) -> None:
    """Raise an actionable layout error for clipped, overlapping or undersized text."""
    figure.canvas.draw()
    undrawn = set()
    for ax in figure.axes:
        for axis in (ax.xaxis, ax.yaxis):
            low, high = sorted(axis.get_view_interval())
            for tick in [*axis.get_major_ticks(), *axis.get_minor_ticks()]:
                if not low <= tick.get_loc() <= high:
                    undrawn.update((tick.label1, tick.label2))
    texts = [
        text
        for text in figure.findobj(Text)
        if text.get_visible() and text.get_text().strip() and text not in undrawn
    ]
    boxes = []
    for text in texts:
        box = text.get_window_extent()
        if (
            text.get_fontproperties().get_size_in_points() < FONT_SIZE
            or box.x0 < -0.5
            or box.y0 < -0.5
            or box.x1 > figure.bbox.width + 0.5
            or box.y1 > figure.bbox.height + 0.5
        ):
            raise LayoutError(
                f"Text {text.get_text()!r} cannot fit readably; use a larger page_size or fewer panels."
            )
        for other, other_box in boxes:
            overlap = box.intersection(box, other_box)
            if overlap is not None and overlap.width > 1 and overlap.height > 1:
                raise LayoutError(
                    f"Labels {text.get_text()!r} and {other.get_text()!r} overlap; "
                    "use a larger page_size or fewer panels."
                )
        boxes.append((text, box))
