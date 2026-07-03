"""Base data models for SDOM infrasys integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from infrasys import Component
from pydantic import Field


class SDOMTechnologyType(StrEnum):
    """Technology categories represented by SDOM components."""

    THERMAL = "thermal"
    SOLAR = "solar"
    WIND = "wind"
    HYDRO = "hydro"
    NUCLEAR = "nuclear"
    OTHER_RENEWABLE = "other_renewable"
    STORAGE = "storage"
    LOAD = "load"
    IMPORT = "import"
    EXPORT = "export"
    TRANSMISSION = "transmission"


class SDOMComponent(Component):
    """Base class for SDOM infrasys components.

    Parameters
    ----------
    name : str
        Unique component name managed by :class:`infrasys.Component`.
    category : str, optional
        SDOM component category used for grouping and display.
    ext : dict, optional
        Additional JSON-serializable metadata that does not belong in the
        typed component schema.
    """

    category: Annotated[str | None, Field(description="SDOM component category")] = None
    ext: Annotated[
        dict[str, Any],
        Field(default_factory=dict, description="Additional serializable component metadata."),
    ]


__all__ = ["SDOMComponent", "SDOMTechnologyType"]
