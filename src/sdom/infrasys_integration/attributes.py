"""Supplemental attribute models for SDOM infrasys integration."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from infrasys import SupplementalAttribute
from infrasys.models import InfraSysBaseModel
from pydantic import Field, field_validator


class GeoLocation(InfraSysBaseModel):
    """Geographic location using GeoJSON point coordinates.

    Parameters
    ----------
    coordinates : list[float]
        Point coordinates in GeoJSON order: ``[longitude, latitude]``.
    type : str, default="Point"
        GeoJSON geometry type. Only ``"Point"`` is supported.

    Raises
    ------
    ValueError
        If coordinates are not finite longitude/latitude values.

    Examples
    --------
    >>> GeoLocation(coordinates=[-100.0, 10.5]).coordinates
    [-100.0, 10.5]
    """

    coordinates: Annotated[
        list[float],
        Field(min_length=2, max_length=2, description="GeoJSON [longitude, latitude] point."),
    ]
    type: Annotated[Literal["Point"], Field(description="GeoJSON geometry type.")] = "Point"

    @field_validator("coordinates")
    @classmethod
    def _validate_point_coordinates(cls, coordinates: list[float]) -> list[float]:
        """Validate GeoJSON point coordinate bounds.

        Parameters
        ----------
        coordinates : list[float]
            Candidate ``[longitude, latitude]`` point.

        Returns
        -------
        list[float]
            Validated coordinates.

        Raises
        ------
        ValueError
            If longitude or latitude is non-finite or out of bounds.

        Examples
        --------
        >>> GeoLocation(coordinates=[-105.0, 40.0]).coordinates
        [-105.0, 40.0]
        """
        longitude, latitude = coordinates
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError("longitude must be finite and within [-180, 180].")
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise ValueError("latitude must be finite and within [-90, 90].")
        return coordinates


class GeographicInfo(SupplementalAttribute):
    """Supplemental attribute that captures component location.

    Parameters
    ----------
    geo_json : GeoLocation
        GeoJSON point location.
    source : str, optional
        Source of the geographic information, such as a CSV table or derived
        area centroid.

    Examples
    --------
    >>> GeographicInfo.example().geo_json.type
    'Point'
    """

    geo_json: Annotated[GeoLocation, Field(description="GeoJSON point location.")]
    source: Annotated[str | None, Field(default=None, description="Location data source.")]

    @classmethod
    def example(cls) -> GeographicInfo:
        """Create an example geographic supplemental attribute.

        Returns
        -------
        GeographicInfo
            Example attribute with a GeoJSON point.

        Examples
        --------
        >>> GeographicInfo.example().geo_json.coordinates
        [-100.0, 10.5]
        """
        return GeographicInfo(geo_json=GeoLocation(coordinates=[-100.0, 10.5], type="Point"))


__all__ = ["GeoLocation", "GeographicInfo"]
