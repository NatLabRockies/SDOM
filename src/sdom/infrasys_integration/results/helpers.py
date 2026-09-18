"""Internal constants and value-conversion helpers for result persistence."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from typing import Any

import pandas as pd

from ..models import (
    SDOMAreaDispatchMetric,
    SDOMAreaDispatchResult,
    SDOMCapacityResult,
    SDOMCostResult,
    SDOMCurtailmentResult,
    SDOMDualResult,
    SDOMGenerationResult,
    SDOMInstalledCapacityResult,
    SDOMInterregionalExchangeResult,
    SDOMOptimizationResult,
    SDOMProblemInfoResult,
    SDOMResultTopologyMetadata,
    SDOMScenarioMetadata,
    SDOMStorageDispatchResult,
    SDOMSummaryMetricResult,
    SDOMThermalGenerationResult,
)

LOGGER = logging.getLogger("sdom.infrasys_integration.results")

DEFAULT_COPPERPLATE_AREA_NAME = "Copperplate"

_GENERATOR_PREFIX_BY_TECHNOLOGY = {
    "Solar PV": "solar",
    "Wind": "wind",
    "Thermal": "thermal",
}

_RESULT_ATTRIBUTE_TYPES = (
    SDOMAreaDispatchResult,
    SDOMCapacityResult,
    SDOMCostResult,
    SDOMCurtailmentResult,
    SDOMDualResult,
    SDOMGenerationResult,
    SDOMInstalledCapacityResult,
    SDOMInterregionalExchangeResult,
    SDOMOptimizationResult,
    SDOMProblemInfoResult,
    SDOMResultTopologyMetadata,
    SDOMScenarioMetadata,
    SDOMStorageDispatchResult,
    SDOMSummaryMetricResult,
    SDOMThermalGenerationResult,
)
_DISPATCH_COLUMNS = tuple(metric.value for metric in SDOMAreaDispatchMetric)
_SUMMARY_COLUMNS = ("Metric", "Technology", "Run", "Optimal Value", "Unit")
_EXCHANGE_COLUMNS = (
    "line_id",
    "from_area",
    "to_area",
    "hour",
    "flow_signed_MW",
    "flow_FT_MW",
    "flow_TF_MW",
    "cap_FT_MW",
    "cap_TF_MW",
    "utilization_FT",
    "utilization_TF",
)


def _iter_numeric_leaves(mapping: Mapping[str, Any]) -> Iterator[tuple[str, float]]:
    """Yield string keys and numeric leaf values from a mapping.

    Parameters
    ----------
    mapping : mapping of str to Any
        Mapping to traverse.

    Yields
    ------
    tuple[str, float]
        Leaf key and numeric value pairs.

    Examples
    --------
    >>> list(_iter_numeric_leaves({"a": 1.0}))
    [('a', 1.0)]
    """
    for key, value in mapping.items():
        if isinstance(value, Mapping):
            yield from _iter_numeric_leaves(value)
        elif _is_number(value):
            yield str(key), float(value)


def _iter_numeric_paths(mapping: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], float]]:
    """Yield key paths and numeric leaf values from a nested mapping.

    Parameters
    ----------
    mapping : mapping of str to Any
        Mapping to traverse.
    prefix : tuple of str, default=()
        Current path prefix used during recursion.

    Yields
    ------
    tuple[tuple[str, ...], float]
        Path and numeric value pairs.

    Examples
    --------
    >>> list(_iter_numeric_paths({"a": {"b": 1.0}}))
    [(('a', 'b'), 1.0)]
    """
    for key, value in mapping.items():
        path = (*prefix, str(key))
        if isinstance(value, Mapping):
            yield from _iter_numeric_paths(value, path)
        elif _is_number(value):
            yield path, float(value)


def _is_number(value: Any) -> bool:
    """Return whether a value should be stored as a numeric metric.

    Parameters
    ----------
    value : Any
        Candidate value.

    Returns
    -------
    bool
        ``True`` when the value is an int or float but not a bool.

    Examples
    --------
    >>> _is_number(1.0)
    True
    >>> _is_number(True)
    False
    """
    return isinstance(value, int | float) and not isinstance(value, bool)


def _float_list(series: pd.Series) -> list[float]:
    """Convert a numeric pandas Series to a compact Python float list.

    Parameters
    ----------
    series : pandas.Series
        Series containing numeric values.

    Returns
    -------
    list[float]
        Values converted to Python floats.

    Examples
    --------
    >>> _float_list(pd.Series([1, 2]))
    [1.0, 2.0]
    """
    return [float(value) for value in series.to_numpy(copy=False)]


def _optional_float_list(series: pd.Series) -> list[float | None]:
    """Convert a pandas Series to optional Python floats.

    Parameters
    ----------
    series : pandas.Series
        Series containing numeric or missing values.

    Returns
    -------
    list[float | None]
        Values converted to floats, with missing values as ``None``.

    Examples
    --------
    >>> _optional_float_list(pd.Series([1, None]))
    [1.0, None]
    """
    return [_optional_float(value) for value in series.to_numpy(copy=False)]


def _int_list(series: pd.Series) -> list[int]:
    """Convert a numeric pandas Series to Python ints.

    Parameters
    ----------
    series : pandas.Series
        Series containing integer-like values.

    Returns
    -------
    list[int]
        Values converted to Python ints.

    Examples
    --------
    >>> _int_list(pd.Series([1, 2]))
    [1, 2]
    """
    return [int(value) for value in series.to_numpy(copy=False)]


def _optional_float(value: Any) -> float | None:
    """Convert a scalar value to an optional float.

    Parameters
    ----------
    value : Any
        Scalar value.

    Returns
    -------
    float | None
        Float value or ``None`` for missing inputs.

    Examples
    --------
    >>> _optional_float(None) is None
    True
    """
    if value is None or pd.isna(value):
        return None
    return float(value)


def _optional_str(value: Any) -> str | None:
    """Convert a scalar value to an optional string.

    Parameters
    ----------
    value : Any
        Scalar value.

    Returns
    -------
    str | None
        String value or ``None`` for missing inputs.

    Examples
    --------
    >>> _optional_str(None) is None
    True
    """
    if value is None or pd.isna(value):
        return None
    return str(value)


def _json_scalar(value: Any) -> str | int | float | bool | None:
    """Convert scalar values to JSON-compatible scalars.

    Parameters
    ----------
    value : Any
        Scalar value to convert.

    Returns
    -------
    str | int | float | bool | None
        JSON-compatible scalar value.

    Examples
    --------
    >>> _json_scalar(float("nan")) is None
    True
    """
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, str | int | float | bool):
        return value
    return str(value)


__all__ = [
    "DEFAULT_COPPERPLATE_AREA_NAME",
    "LOGGER",
    "_DISPATCH_COLUMNS",
    "_EXCHANGE_COLUMNS",
    "_GENERATOR_PREFIX_BY_TECHNOLOGY",
    "_RESULT_ATTRIBUTE_TYPES",
    "_SUMMARY_COLUMNS",
    "_float_list",
    "_int_list",
    "_iter_numeric_leaves",
    "_iter_numeric_paths",
    "_json_scalar",
    "_optional_float",
    "_optional_float_list",
    "_optional_str",
]
