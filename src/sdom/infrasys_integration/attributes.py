"""Backward-compatible supplemental attribute imports for SDOM infrasys integration."""

from __future__ import annotations

from .models.attributes import GeographicInfo, GeoLocation

__all__ = ["GeoLocation", "GeographicInfo"]
