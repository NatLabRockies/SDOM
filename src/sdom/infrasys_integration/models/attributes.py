"""Supplemental attribute models for SDOM infrasys integration."""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

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


class SDOMResultAttribute(SupplementalAttribute):
    """Base metadata shared by SDOM result supplemental attributes.

    Parameters
    ----------
    run_id : str
        Stable identifier for one optimization run.
    scenario_name : str, optional
        User-facing scenario name associated with the run.
    case_name : str, optional
        SDOM case name used while collecting results.

    Examples
    --------
    >>> SDOMResultAttribute(run_id="run-1").run_id
    'run-1'
    """

    run_id: Annotated[str, Field(min_length=1, description="Optimization run identifier.")]
    scenario_name: Annotated[str | None, Field(default=None, description="Scenario name for the run.")]
    case_name: Annotated[str | None, Field(default=None, description="Case name for the run.")]


class SDOMScenarioMetadata(SDOMResultAttribute):
    """Supplemental attribute describing an SDOM optimization scenario.

    Parameters
    ----------
    metadata : dict, optional
        JSON-serializable scenario metadata supplied by the caller.

    Examples
    --------
    >>> attr = SDOMScenarioMetadata(run_id="run-1", metadata={"solver": "highs"})
    >>> attr.metadata["solver"]
    'highs'
    """

    metadata: Annotated[
        dict[str, Any],
        Field(default_factory=dict, description="Caller-provided scenario metadata."),
    ]


class SDOMOptimizationResult(SDOMResultAttribute):
    """Supplemental attribute for run-level optimization outcome metrics.

    Parameters
    ----------
    total_cost : float
        Objective value for the solved optimization run.
    gen_mix_target : float
        Generation mix target used for the run.
    termination_condition : str
        Solver termination condition.
    solver_status : str
        Solver status string.

    Examples
    --------
    >>> result = SDOMOptimizationResult(run_id="run-1", total_cost=1.5)
    >>> result.total_cost
    1.5
    """

    total_cost: Annotated[float, Field(description="Optimization objective value.")] = 0.0
    gen_mix_target: Annotated[float, Field(description="Generation mix target.")] = 0.0
    termination_condition: Annotated[str, Field(description="Solver termination condition.")] = ""
    solver_status: Annotated[str, Field(description="Solver status.")] = ""


class SDOMCapacityResult(SDOMResultAttribute):
    """Supplemental attribute for capacity results.

    Parameters
    ----------
    technology : str
        Technology or aggregate label for the capacity value.
    capacity_type : str
        Capacity category such as ``"installed"``, ``"charge"``,
        ``"discharge"``, or ``"energy"``.
    value : float
        Capacity value.
    unit : str
        Unit for ``value``.
    area : str, optional
        Area associated with the result when applicable.

    Examples
    --------
    >>> result = SDOMCapacityResult(run_id="run-1", technology="Solar PV", value=10.0)
    >>> result.unit
    'MW'
    """

    technology: Annotated[str, Field(description="Technology or aggregate label.")]
    capacity_type: Annotated[str, Field(description="Capacity result category.")] = "installed"
    value: Annotated[float, Field(description="Capacity value.")] = 0.0
    unit: Annotated[str, Field(description="Capacity unit.")] = "MW"
    area: Annotated[str | None, Field(default=None, description="Area associated with the result.")]


class SDOMGenerationResult(SDOMResultAttribute):
    """Supplemental attribute for generation results.

    Parameters
    ----------
    technology : str
        Technology or aggregate generation label.
    total_mwh : float
        Total generation across the result horizon.
    hourly_mw : list of float, optional
        Hourly generation values when available.
    area : str, optional
        Area associated with the result when applicable.

    Examples
    --------
    >>> result = SDOMGenerationResult(run_id="run-1", technology="Thermal", total_mwh=5.0)
    >>> result.total_mwh
    5.0
    """

    technology: Annotated[str, Field(description="Technology or aggregate generation label.")]
    total_mwh: Annotated[float, Field(description="Total generation over the horizon.")] = 0.0
    hourly_mw: Annotated[
        list[float] | None,
        Field(default=None, description="Hourly generation values in MW."),
    ]
    area: Annotated[str | None, Field(default=None, description="Area associated with the result.")]


class SDOMStorageDispatchResult(SDOMResultAttribute):
    """Supplemental attribute for storage dispatch time series.

    Parameters
    ----------
    technology : str
        Storage technology label.
    charge_mw : list of float
        Hourly storage charge power.
    discharge_mw : list of float
        Hourly storage discharge power.
    state_of_charge_mwh : list of float
        Hourly state of charge.
    area : str, optional
        Area associated with the storage resource when applicable.

    Examples
    --------
    >>> result = SDOMStorageDispatchResult(run_id="run-1", technology="Battery", charge_mw=[1.0])
    >>> result.charge_mw
    [1.0]
    """

    technology: Annotated[str, Field(description="Storage technology label.")]
    charge_mw: Annotated[list[float], Field(default_factory=list, description="Hourly charge power in MW.")]
    discharge_mw: Annotated[list[float], Field(default_factory=list, description="Hourly discharge power in MW.")]
    state_of_charge_mwh: Annotated[list[float], Field(default_factory=list, description="Hourly state of charge in MWh.")]
    area: Annotated[str | None, Field(default=None, description="Area associated with the result.")]


class SDOMCostResult(SDOMResultAttribute):
    """Supplemental attribute for cost results.

    Parameters
    ----------
    cost_type : str
        Cost category such as ``"capex"`` or ``"fuel_cost"``.
    technology : str, optional
        Technology or aggregate label associated with the cost.
    value : float
        Cost value.
    unit : str
        Cost unit.
    area : str, optional
        Area associated with the result when applicable.

    Examples
    --------
    >>> result = SDOMCostResult(run_id="run-1", cost_type="capex", technology="Solar PV", value=2.0)
    >>> result.value
    2.0
    """

    cost_type: Annotated[str, Field(description="Cost result category.")]
    technology: Annotated[str | None, Field(default=None, description="Technology or aggregate label.")]
    value: Annotated[float, Field(description="Cost value.")] = 0.0
    unit: Annotated[str, Field(description="Cost unit.")] = "$"
    area: Annotated[str | None, Field(default=None, description="Area associated with the result.")]


class SDOMCurtailmentResult(SDOMResultAttribute):
    """Supplemental attribute for curtailment results.

    Parameters
    ----------
    technology : str
        Technology label for the curtailed generation.
    total_mwh : float
        Total curtailed energy over the horizon.
    hourly_mw : list of float, optional
        Hourly curtailment values when available.
    area : str, optional
        Area associated with the result when applicable.

    Examples
    --------
    >>> result = SDOMCurtailmentResult(run_id="run-1", technology="Solar PV", total_mwh=0.5)
    >>> result.total_mwh
    0.5
    """

    technology: Annotated[str, Field(description="Curtailment technology label.")]
    total_mwh: Annotated[float, Field(description="Total curtailment over the horizon.")] = 0.0
    hourly_mw: Annotated[
        list[float] | None,
        Field(default=None, description="Hourly curtailment values in MW."),
    ]
    area: Annotated[str | None, Field(default=None, description="Area associated with the result.")]


class SDOMDualResult(SDOMResultAttribute):
    """Supplemental attribute for optimization dual values.

    Parameters
    ----------
    constraint_name : str
        Name of the constraint associated with the dual value.
    value : float
        Dual value.
    hour : int, optional
        Hour associated with the dual value when applicable.
    area : str, optional
        Area associated with the result when applicable.

    Examples
    --------
    >>> result = SDOMDualResult(run_id="run-1", constraint_name="balance", value=1.0)
    >>> result.constraint_name
    'balance'
    """

    constraint_name: Annotated[str, Field(description="Constraint name associated with the dual value.")]
    value: Annotated[float, Field(description="Dual value.")] = 0.0
    hour: Annotated[int | None, Field(default=None, description="Hour associated with the dual value.")]
    area: Annotated[str | None, Field(default=None, description="Area associated with the result.")]


__all__ = [
    "GeoLocation",
    "GeographicInfo",
    "SDOMCapacityResult",
    "SDOMCostResult",
    "SDOMCurtailmentResult",
    "SDOMDualResult",
    "SDOMGenerationResult",
    "SDOMOptimizationResult",
    "SDOMResultAttribute",
    "SDOMScenarioMetadata",
    "SDOMStorageDispatchResult",
]
