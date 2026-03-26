"""Shared I/O utilities for SDOM analytic_tools."""

from __future__ import annotations

import os

import matplotlib.pyplot as plt

from ._colors import get_heatmap_cmap  # re-exported for convenience

__all__ = ["ensure_dir", "save_figure", "get_heatmap_cmap"]


def ensure_dir(path: str) -> None:
    """Create *path* (and any missing parents) if it does not already exist."""
    os.makedirs(path, exist_ok=True)


def save_figure(fig: plt.Figure, path: str, dpi: int = 300) -> None:
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
    """
    ensure_dir(os.path.dirname(os.path.abspath(path)))
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
