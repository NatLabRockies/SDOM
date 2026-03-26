"""Central color palette for SDOM analytic_tools.

This is the single source of truth for all colors used in plots.
No other module in analytic_tools should define its own color dicts.
"""

from __future__ import annotations

from typing import List, Optional

from matplotlib.colors import LinearSegmentedColormap

# ---------------------------------------------------------------------------
# Base generation / capacity colors
# ---------------------------------------------------------------------------

TECH_COLORS: dict = {
    "Thermal":          "#5E1688",   # purple
    "Solar PV":         "#FFC903",   # yellow
    "Wind":             "#00B6EF",   # cyan-blue
    "Nuclear":          "#FF6B35",   # orange-red
    "Hydro":            "#004E89",   # deep blue
    "Other renewables": "#76B947",   # green
}

# Assigned in order to storage technologies (dynamic, named at runtime)
STORAGE_COLORS: List[str] = [
    "#FF4A88",
    "#FF4741",
    "#CC0079",
    "#FF7FBB",
    "#7F7FFF",
    "#FFCE89",
    "#47FFB3",
]

# Colors for hue grouping in curtailment / simple grouped bar charts
HUE_COLORS: List[str] = [
    "#3498db",  # blue
    "#2ecc71",  # green
    "#e74c3c",  # red
    "#f39c12",  # orange
    "#9b59b6",  # purple
    "#1abc9c",  # teal
    "#e67e22",  # dark orange
]

# ---------------------------------------------------------------------------
# Heatmap colormap
# ---------------------------------------------------------------------------

HEATMAP_COLORS: List[str] = [
    "#00296b",
    "#047cd2",
    "#19B7C2",
    "#e1ff00",
    "#fdec00",
    "#F9391C",
]

# All known non-storage technologies (used to infer storage from a tech list)
_KNOWN_GEN_TECHS = frozenset(TECH_COLORS.keys())


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_heatmap_cmap() -> LinearSegmentedColormap:
    """Return the custom SDOM heatmap colormap."""
    return LinearSegmentedColormap.from_list("sdom_heatmap", HEATMAP_COLORS)


def infer_storage_technologies(technologies: List[str]) -> List[str]:
    """Return sorted list of storage technology names from *technologies*.

    Any technology name that is not in the known generation set and not ``"All"``
    is considered a storage technology.
    """
    return sorted(
        [t for t in technologies if t not in _KNOWN_GEN_TECHS and t != "All"]
    )


def get_technology_color_map(
    storage_techs: Optional[List[str]] = None,
) -> dict:
    """Return a complete technology → hex-color mapping.

    Parameters
    ----------
    storage_techs:
        List of storage technology names to include.  Colors are assigned in
        order from :data:`STORAGE_COLORS`, cycling if there are more techs than
        colors.  Pass ``None`` or an empty list to omit storage colors.

    Returns
    -------
    dict
        Mapping of technology name to hex color string.
    """
    color_map = dict(TECH_COLORS)
    for i, tech in enumerate(storage_techs or []):
        color_map[tech] = STORAGE_COLORS[i % len(STORAGE_COLORS)]
    return color_map


def get_technology_order(storage_techs: Optional[List[str]] = None) -> List[str]:
    """Return the canonical technology stacking order (bottom → top).

    Order: Thermal → Nuclear → Hydro → Other renewables → Solar PV → Wind
    → storage technologies (alphabetically).

    Parameters
    ----------
    storage_techs:
        List of storage technology names to append.
    """
    order = ["Thermal", "Nuclear", "Hydro", "Other renewables", "Solar PV", "Wind"]
    order.extend(sorted(storage_techs or []))
    return order
