"""Supplemental attribute models for SDOM infrasys integration."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from infrasys import SupplementalAttribute
from infrasys.models import InfraSysBaseModel
from pydantic import Field, field_validator, model_validator


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


class SDOMProblemInfoResult(SDOMResultAttribute):
    """Supplemental attribute for one solver problem-info entry.

    Parameters
    ----------
    key : str
        Problem information key.
    value : str | int | float | bool | None
        JSON scalar value for the problem information entry.

    Examples
    --------
    >>> SDOMProblemInfoResult(run_id="run-1", key="Number of variables", value=10).value
    10
    """

    key: Annotated[str, Field(min_length=1, description="Problem information key.")]
    value: Annotated[
        str | int | float | bool | None,
        Field(default=None, description="Problem information value."),
    ]


class SDOMResultTopologyMetadata(SDOMResultAttribute):
    """Supplemental attribute describing the topology represented by results.

    Parameters
    ----------
    is_zonal : bool, default=False
        Whether the result came from a zonal SDOM model.
    areas : list[str], optional
        Ordered area names included in the result.
    lines : list[dict[str, str]], optional
        Ordered transmission interface records included in the result.

    Examples
    --------
    >>> SDOMResultTopologyMetadata(run_id="run-1", is_zonal=True, areas=["A"]).areas
    ['A']
    """

    is_zonal: Annotated[bool, Field(description="Whether the result is zonal.")] = False
    areas: Annotated[list[str], Field(default_factory=list, description="Ordered result area names.")]
    lines: Annotated[
        list[dict[str, str]],
        Field(default_factory=list, description="Ordered result transmission line records."),
    ]


class SDOMCapacityResult(SDOMResultAttribute):
    """Supplemental attribute for aggregate capacity results.

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


class SDOMInstalledCapacityResult(SDOMResultAttribute):
    """Supplemental attribute for one installed plant capacity row.

    Parameters
    ----------
    plant_id : str
        SDOM plant identifier.
    technology : str
        Plant technology label.
    row_order : int, default=0
        Original row order in the installed plants table.
    installed_capacity_mw : float
        Installed capacity in MW.
    max_capacity_mw : float, optional
        Candidate maximum capacity in MW.
    capacity_fraction : float, optional
        Installed fraction of maximum capacity.

    Examples
    --------
    >>> SDOMInstalledCapacityResult(run_id="run-1", plant_id="p1", technology="Solar PV", installed_capacity_mw=2).plant_id
    'p1'
    """

    plant_id: Annotated[str, Field(min_length=1, description="SDOM plant identifier.")]
    technology: Annotated[str, Field(min_length=1, description="Plant technology label.")]
    row_order: Annotated[int, Field(ge=0, description="Original output row order.")] = 0
    installed_capacity_mw: Annotated[float, Field(description="Installed capacity in MW.")]
    max_capacity_mw: Annotated[float | None, Field(default=None, description="Maximum candidate capacity in MW.")]
    capacity_fraction: Annotated[float | None, Field(default=None, description="Installed capacity fraction.")]


class SDOMGenerationResult(SDOMResultAttribute):
    """Supplemental attribute for aggregate generation totals.

    Parameters
    ----------
    technology : str
        Technology or aggregate generation label.
    total_mwh : float
        Total generation across the result horizon.
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
    area: Annotated[str | None, Field(default=None, description="Area associated with the result.")]


class SDOMAreaDispatchMetric(StrEnum):
    """Canonical hourly area dispatch metrics stored by SDOM.

    Examples
    --------
    >>> SDOMAreaDispatchMetric.LOAD.value
    'Load (MW)'
    """

    SOLAR_PV_GENERATION = "Solar PV Generation (MW)"
    SOLAR_PV_CURTAILMENT = "Solar PV Curtailment (MW)"
    WIND_GENERATION = "Wind Generation (MW)"
    WIND_CURTAILMENT = "Wind Curtailment (MW)"
    ALL_THERMAL_GENERATION = "All Thermal Generation (MW)"
    HYDRO_GENERATION = "Hydro Generation (MW)"
    NUCLEAR_GENERATION = "Nuclear Generation (MW)"
    OTHER_RENEWABLES_GENERATION = "Other Renewables Generation (MW)"
    IMPORTS = "Imports (MW)"
    STORAGE_CHARGE_DISCHARGE = "Storage Charge/Discharge (MW)"
    EXPORTS = "Exports (MW)"
    LOAD = "Load (MW)"
    NET_LOAD = "Net Load (MW)"


class SDOMAreaDispatchSeries(InfraSysBaseModel):
    """One hourly metric series in an area dispatch result.

    Parameters
    ----------
    metric : SDOMAreaDispatchMetric
        Dispatch metric represented by the series.
    values : list[float]
        Hourly metric values.

    Examples
    --------
    >>> SDOMAreaDispatchSeries(metric=SDOMAreaDispatchMetric.LOAD, values=[1.0]).values
    [1.0]
    """

    metric: Annotated[SDOMAreaDispatchMetric, Field(description="Dispatch metric represented by the series.")]
    values: Annotated[list[float], Field(default_factory=list, description="Hourly metric values.")]


class SDOMAreaDispatchResult(SDOMResultAttribute):
    """Supplemental attribute for hourly area dispatch results.

    Parameters
    ----------
    hours : list[int]
        Ordered dispatch hours.
    scenario : str, optional
        Original scenario value from the dispatch table.
    series : list[SDOMAreaDispatchSeries]
        Metric series aligned with ``hours``. The owner must be an
        :class:`SDOMArea`.

    Raises
    ------
    ValueError
        If any series length differs from ``hours`` or a metric is duplicated.

    Examples
    --------
    >>> attr = SDOMAreaDispatchResult(run_id="run-1", hours=[1], series=[SDOMAreaDispatchSeries(metric=SDOMAreaDispatchMetric.LOAD, values=[2.0])])
    >>> attr.series[0].metric.value
    'Load (MW)'
    """

    hours: Annotated[list[int], Field(default_factory=list, description="Ordered dispatch hours.")]
    scenario: Annotated[str | None, Field(default=None, description="Original dispatch table scenario label.")]
    series: Annotated[
        list[SDOMAreaDispatchSeries],
        Field(default_factory=list, description="Dispatch metric series aligned with hours."),
    ]

    @model_validator(mode="after")
    def _validate_series(self) -> Self:
        """Validate metric uniqueness and aligned series lengths.

        Returns
        -------
        Self
            Validated dispatch result.

        Raises
        ------
        ValueError
            If a metric is duplicated or has the wrong number of values.

        Examples
        --------
        >>> SDOMAreaDispatchResult(run_id="run-1", hours=[1], series=[]).hours
        [1]
        """
        expected = len(self.hours)
        seen: set[SDOMAreaDispatchMetric] = set()
        for item in self.series:
            if item.metric in seen:
                raise ValueError(f"duplicate dispatch metric: {item.metric}")
            seen.add(item.metric)
            if len(item.values) != expected:
                raise ValueError(f"{item.metric} has {len(item.values)} values but hours has {expected}.")
        return self


class SDOMThermalGenerationResult(SDOMResultAttribute):
    """Supplemental attribute for one thermal generator dispatch series.

    Parameters
    ----------
    hours : list[int]
        Ordered dispatch hours.
    generation_mw : list[float]
        Hourly thermal generation in MW.

    Examples
    --------
    >>> SDOMThermalGenerationResult(run_id="run-1", hours=[1], generation_mw=[3.0]).generation_mw
    [3.0]
    """

    hours: Annotated[list[int], Field(default_factory=list, description="Ordered dispatch hours.")]
    generation_mw: Annotated[list[float], Field(default_factory=list, description="Hourly generation in MW.")]

    @model_validator(mode="after")
    def _validate_lengths(self) -> Self:
        """Validate that generation values align with hours.

        Returns
        -------
        Self
            Validated thermal generation result.

        Raises
        ------
        ValueError
            If ``generation_mw`` length differs from ``hours`` length.

        Examples
        --------
        >>> SDOMThermalGenerationResult(run_id="run-1", hours=[1], generation_mw=[2.0]).hours
        [1]
        """
        if len(self.generation_mw) != len(self.hours):
            raise ValueError("generation_mw length must match hours length.")
        return self


class SDOMStorageDispatchResult(SDOMResultAttribute):
    """Supplemental attribute for storage dispatch time series.

    Parameters
    ----------
    hours : list[int]
        Ordered dispatch hours.
    row_order : int, default=0
        Ordering key for this storage technology in SDOM output tables.
    charge_mw : list[float]
        Hourly storage charge power.
    discharge_mw : list[float]
        Hourly storage discharge power.
    state_of_charge_mwh : list[float]
        Hourly state of charge.

    Examples
    --------
    >>> result = SDOMStorageDispatchResult(run_id="run-1", hours=[1], charge_mw=[1.0], discharge_mw=[0.0], state_of_charge_mwh=[2.0])
    >>> result.charge_mw
    [1.0]
    """

    hours: Annotated[list[int], Field(default_factory=list, description="Ordered dispatch hours.")]
    row_order: Annotated[int, Field(ge=0, description="Ordering key for output table reconstruction.")] = 0
    charge_mw: Annotated[list[float], Field(default_factory=list, description="Hourly charge power in MW.")]
    discharge_mw: Annotated[list[float], Field(default_factory=list, description="Hourly discharge power in MW.")]
    state_of_charge_mwh: Annotated[list[float], Field(default_factory=list, description="Hourly state of charge in MWh.")]

    @model_validator(mode="after")
    def _validate_lengths(self) -> Self:
        """Validate that all storage vectors align with hours.

        Returns
        -------
        Self
            Validated storage dispatch result.

        Raises
        ------
        ValueError
            If any vector length differs from ``hours`` length.

        Examples
        --------
        >>> SDOMStorageDispatchResult(run_id="run-1", hours=[1], charge_mw=[1], discharge_mw=[0], state_of_charge_mwh=[1]).hours
        [1]
        """
        expected = len(self.hours)
        lengths = (len(self.charge_mw), len(self.discharge_mw), len(self.state_of_charge_mwh))
        if any(length != expected for length in lengths):
            raise ValueError("storage dispatch vector lengths must match hours length.")
        return self


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


class SDOMSummaryMetricResult(SDOMResultAttribute):
    """Supplemental attribute for one summary table row.

    Parameters
    ----------
    row_order : int
        Original row order in the summary table.
    metric : str
        Summary metric label.
    technology : str, optional
        Technology label for the row.
    run : int | str | None
        Run value stored in the summary row.
    optimal_value : str | int | float | bool | None
        Optimal value stored in the summary row.
    unit : str, optional
        Unit label for the row.

    Examples
    --------
    >>> SDOMSummaryMetricResult(run_id="run-1", row_order=0, metric="Total cost", optimal_value=1.0).metric
    'Total cost'
    """

    row_order: Annotated[int, Field(ge=0, description="Original row order.")]
    metric: Annotated[str, Field(description="Summary metric label.")]
    technology: Annotated[str | None, Field(default=None, description="Technology label.")]
    run: Annotated[int | str | None, Field(default=None, description="Run value.")]
    optimal_value: Annotated[
        str | int | float | bool | None,
        Field(default=None, description="Summary optimal value."),
    ]
    unit: Annotated[str | None, Field(default=None, description="Unit label.")]


class SDOMCurtailmentResult(SDOMResultAttribute):
    """Supplemental attribute for curtailment results.

    Parameters
    ----------
    technology : str
        Technology label for the curtailed generation.
    total_mwh : float
        Total curtailed energy over the horizon.
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
    area: Annotated[str | None, Field(default=None, description="Area associated with the result.")]


class SDOMInterregionalExchangeResult(SDOMResultAttribute):
    """Supplemental attribute for one transmission interface flow series.

    Parameters
    ----------
    hours : list[int]
        Ordered dispatch hours.
    flow_signed_mw : list[float]
        Signed hourly flow values.
    flow_ft_mw : list[float]
        Forward hourly flow values.
    flow_tf_mw : list[float]
        Reverse hourly flow values.
    cap_ft_mw : list[float]
        Forward hourly capacity values.
    cap_tf_mw : list[float]
        Reverse hourly capacity values.
    utilization_ft : list[float | None]
        Forward utilization values.
    utilization_tf : list[float | None]
        Reverse utilization values.

    Examples
    --------
    >>> SDOMInterregionalExchangeResult(run_id="run-1", hours=[1], flow_signed_mw=[0], flow_ft_mw=[0], flow_tf_mw=[0], cap_ft_mw=[1], cap_tf_mw=[1], utilization_ft=[0], utilization_tf=[0]).hours
    [1]
    """

    hours: Annotated[list[int], Field(default_factory=list, description="Ordered dispatch hours.")]
    flow_signed_mw: Annotated[list[float], Field(default_factory=list, description="Signed hourly flow values.")]
    flow_ft_mw: Annotated[list[float], Field(default_factory=list, description="Forward hourly flow values.")]
    flow_tf_mw: Annotated[list[float], Field(default_factory=list, description="Reverse hourly flow values.")]
    cap_ft_mw: Annotated[list[float], Field(default_factory=list, description="Forward hourly capacity values.")]
    cap_tf_mw: Annotated[list[float], Field(default_factory=list, description="Reverse hourly capacity values.")]
    utilization_ft: Annotated[list[float | None], Field(default_factory=list, description="Forward utilization values.")]
    utilization_tf: Annotated[list[float | None], Field(default_factory=list, description="Reverse utilization values.")]

    @model_validator(mode="after")
    def _validate_lengths(self) -> Self:
        """Validate that all exchange vectors align with hours.

        Returns
        -------
        Self
            Validated exchange result.

        Raises
        ------
        ValueError
            If any vector length differs from ``hours`` length.

        Examples
        --------
        >>> SDOMInterregionalExchangeResult(run_id="run-1", hours=[], flow_signed_mw=[], flow_ft_mw=[], flow_tf_mw=[], cap_ft_mw=[], cap_tf_mw=[], utilization_ft=[], utilization_tf=[]).hours
        []
        """
        expected = len(self.hours)
        lengths = (
            len(self.flow_signed_mw),
            len(self.flow_ft_mw),
            len(self.flow_tf_mw),
            len(self.cap_ft_mw),
            len(self.cap_tf_mw),
            len(self.utilization_ft),
            len(self.utilization_tf),
        )
        if any(length != expected for length in lengths):
            raise ValueError("interregional exchange vector lengths must match hours length.")
        return self


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
    "SDOMAreaDispatchMetric",
    "SDOMAreaDispatchResult",
    "SDOMAreaDispatchSeries",
    "SDOMCapacityResult",
    "SDOMCostResult",
    "SDOMCurtailmentResult",
    "SDOMDualResult",
    "SDOMGenerationResult",
    "SDOMInstalledCapacityResult",
    "SDOMInterregionalExchangeResult",
    "SDOMOptimizationResult",
    "SDOMProblemInfoResult",
    "SDOMResultAttribute",
    "SDOMResultTopologyMetadata",
    "SDOMScenarioMetadata",
    "SDOMStorageDispatchResult",
    "SDOMSummaryMetricResult",
    "SDOMThermalGenerationResult",
]
