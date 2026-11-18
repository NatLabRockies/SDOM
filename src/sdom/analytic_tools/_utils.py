"""Shared I/O utilities for SDOM analytic_tools."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
from matplotlib.transforms import Bbox

from ._colors import get_heatmap_cmap  # re-exported for convenience

__all__ = ["ensure_dir", "get_heatmap_cmap", "save_figure"]


def ensure_dir(path: str) -> None:
    """Create *path* (and any missing parents) if it does not already exist."""
    os.makedirs(path, exist_ok=True)


def save_figure(fig: plt.Figure, path: str, dpi: int = 300, *, tight: bool = True) -> None:
    """Save *fig* to *path* at *dpi*, creating parent directories as needed.

    Closes *fig* after saving to prevent matplotlib memory leaks.  Does **not**
    call ``plt.show()``; display is left to the caller.

    Parameters
    ----------
    fig:
        Matplotlib Figure object to save.
    path:
        Absolute or relative file path (including filename and extension).
    dpi:
        Resolution in dots per inch.  Default is 300.
    tight : bool, optional
        Crop to artist bounds by default. False preserves a bounded page canvas.
    """
    try:
        ensure_dir(os.path.dirname(os.path.abspath(path)))
        bounds = "tight" if tight else Bbox.from_bounds(0, 0, *fig.get_size_inches())
        fig.savefig(path, dpi=dpi, bbox_inches=bounds)
    finally:
        plt.close(fig)


def resolve_areas(available: Sequence[str], *, areas: Sequence[str] | None = None) -> list[str]:
    """Validate an explicit ordered subset without silently dropping or merging areas."""
    if areas is None:
        return list(available)
    if isinstance(areas, (str, bytes)) or not isinstance(areas, Sequence) or not areas:
        raise ValueError(
            "areas must be a nonempty sequence of area IDs, such as ['A1'], or None for all areas."
        )
    if any(not isinstance(area, str) for area in areas):
        raise ValueError("areas must contain string area IDs.")
    if len(set(areas)) != len(areas):
        raise ValueError("areas contains duplicate IDs; provide each area only once.")
    unknown = [area for area in areas if area not in available]
    if unknown:
        raise ValueError(f"Unknown area(s) {unknown!r}; available: {list(available)!r}")
    return list(areas)


def save_figure_pages(
    figures: Iterable[plt.Figure],
    path: str,
    *,
    page_count: int,
) -> None:
    """Stage bounded pages and publish a manifest-owned figure family.

    Parameters
    ----------
    figures : iterable of matplotlib.figure.Figure
        Lazily rendered figures, saved and closed one at a time.
    path : str
        Unpaginated output path. Multiple pages append ``_part1``, etc.
    page_count : int
        Expected number of pages, required to select predictable filenames.

    Raises
    ------
    ValueError
        If the page inventory or an existing ownership manifest is invalid.
    FileExistsError
        If an unowned old family would leave ambiguous or stale outputs.
    """
    destination = Path(path).absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = destination.with_suffix(".pages.json")
    filenames = (
        [destination.name]
        if page_count == 1
        else [f"{destination.stem}_part{index + 1}{destination.suffix}" for index in range(page_count)]
    )
    previous: list[str] = []
    if manifest.exists():
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        if (
            not isinstance(metadata, dict)
            or metadata.get("version") != 1
            or not isinstance(metadata.get("files"), list)
        ):
            raise ValueError(f"Invalid plotting ownership manifest: {manifest}")
        previous = metadata["files"]
        for name in previous:
            if (
                not isinstance(name, str)
                or Path(name).name != name
                or not (
                    name == destination.name
                    or (
                        name.startswith(destination.stem + "_part")
                        and name.endswith(destination.suffix)
                        and name[len(destination.stem) + 5 : -len(destination.suffix)].isdigit()
                    )
                )
            ):
                raise ValueError(f"Invalid owned filename in {manifest}: {name!r}")
    existing = {
        file.name for file in destination.parent.glob(f"{destination.stem}_part*{destination.suffix}")
    }
    if destination.exists():
        existing.add(destination.name)
    conflicts = existing - set(previous)
    if conflicts and not (page_count == 1 and conflicts == {destination.name}):
        raise FileExistsError(
            f"Unowned duration-curve outputs {sorted(conflicts)!r} conflict with {destination.name}. "
            "Move those files or choose a fresh plots_dir; they will not be deleted automatically."
        )
    with TemporaryDirectory(prefix=".sdom-pages-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        produced = 0
        for fig in figures:
            try:
                if produced >= page_count:
                    raise ValueError(f"Expected {page_count} pages for {destination.name}, received more.")
                save_figure(fig, str(staging / filenames[produced]), tight=False)
                produced += 1
            finally:
                plt.close(fig)
        if produced != page_count:
            raise ValueError(f"Expected {page_count} pages for {destination.name}, received {produced}.")
        (staging / manifest.name).write_text(
            json.dumps({"version": 1, "files": filenames}, indent=2), encoding="utf-8"
        )
        backup = staging / "previous"
        backup.mkdir()
        published: list[str] = []
        backed_up: list[str] = []
        committed = False
        try:
            for name in dict.fromkeys([*previous, *filenames, manifest.name]):
                current = destination.parent / name
                if current.exists():
                    os.replace(current, backup / name)
                    backed_up.append(name)
            for name in [*filenames, manifest.name]:
                os.replace(staging / name, destination.parent / name)
                published.append(name)
            committed = True
        finally:
            if not committed:
                for name in published:
                    (destination.parent / name).unlink()
                for name in backed_up:
                    os.replace(backup / name, destination.parent / name)
