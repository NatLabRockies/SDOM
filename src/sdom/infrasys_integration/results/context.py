"""Shared context and filtering utilities for SDOM result attributes."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import Any

import pandas as pd
from infrasys import System

from ..models import SDOMComponent, SDOMResultAttribute, SDOMScenarioMetadata
from .helpers import _RESULT_ATTRIBUTE_TYPES


class _ResultContext:
    """Store common result-attachment metadata.

    Parameters
    ----------
    run_id : str
        Stable optimization run identifier.
    scenario_name : str, optional
        User-facing scenario name.
    case_name : str, optional
        SDOM case name.

    Examples
    --------
    >>> _ResultContext("run-1", None, None).kwargs["run_id"]
    'run-1'
    """

    def __init__(self, run_id: str, scenario_name: str | None, case_name: str | None) -> None:
        self.kwargs = {
            "run_id": run_id,
            "scenario_name": scenario_name,
            "case_name": case_name,
        }


class _ResultFilters:
    """Store optional result-query filters.

    Parameters
    ----------
    run_id : str, optional
        Run identifier filter.
    scenario_name : str, optional
        Scenario name filter.
    case_name : str, optional
        Case name filter.

    Examples
    --------
    >>> _ResultFilters(run_id="run-1").matches(SDOMScenarioMetadata(run_id="run-1"))
    True
    """

    def __init__(
        self,
        *,
        run_id: str | None = None,
        scenario_name: str | None = None,
        case_name: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.scenario_name = scenario_name
        self.case_name = case_name

    def matches(self, attribute: SDOMResultAttribute) -> bool:
        """Return whether an attribute matches this filter set.

        Parameters
        ----------
        attribute : SDOMResultAttribute
            Attribute to test.

        Returns
        -------
        bool
            ``True`` when all non-``None`` filters match.

        Examples
        --------
        >>> _ResultFilters(run_id="run-1").matches(SDOMScenarioMetadata(run_id="run-1"))
        True
        """
        if self.run_id is not None and attribute.run_id != self.run_id:
            return False
        if self.scenario_name is not None and attribute.scenario_name != self.scenario_name:
            return False
        return self.case_name is None or attribute.case_name == self.case_name


def _iter_result_attributes(
    system: System,
    attribute_type: type[SDOMResultAttribute],
    *,
    filters: _ResultFilters,
) -> Iterator[tuple[SDOMComponent, SDOMResultAttribute]]:
    """Yield result attributes with their owning component.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    attribute_type : type[SDOMResultAttribute]
        Attribute type to query.
    filters : _ResultFilters
        Run, scenario, and case filters.

    Yields
    ------
    tuple[SDOMComponent, SDOMResultAttribute]
        Owning component and matching attribute.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> list(_iter_result_attributes(load_system("Data/no_exchange_run_of_river"), SDOMScenarioMetadata, filters=_ResultFilters()))
    []
    """
    concrete_types = _RESULT_ATTRIBUTE_TYPES if attribute_type is SDOMResultAttribute else (attribute_type,)
    for component in system.get_components(SDOMComponent):
        for concrete_type in concrete_types:
            for attribute in system.get_supplemental_attributes_with_component(component, concrete_type):
                if filters.matches(attribute):
                    yield component, attribute


def _line_records(lines: Iterable[Any]) -> list[dict[str, str]]:
    """Convert result line metadata to typed topology records.

    Parameters
    ----------
    lines : iterable of Any
        Line metadata from :class:`OptimizationResults`.

    Returns
    -------
    list[dict[str, str]]
        JSON-serializable line metadata records.

    Examples
    --------
    >>> _line_records([{"line_id": "L", "from_area": "A", "to_area": "B"}])
    [{'line_id': 'L', 'from_area': 'A', 'to_area': 'B'}]
    """
    records: list[dict[str, str]] = []
    for line in lines:
        if isinstance(line, Mapping):
            records.append({str(key): str(value) for key, value in line.items()})
        else:
            records.append({"line_id": str(line)})
    return records


def _unique_string(series: pd.Series) -> str | None:
    """Return the unique non-null string value from a Series.

    Parameters
    ----------
    series : pandas.Series
        Series to inspect.

    Returns
    -------
    str | None
        The only non-null string value, or ``None`` when no value exists.

    Raises
    ------
    ValueError
        If multiple distinct values are present.

    Examples
    --------
    >>> _unique_string(pd.Series(["case", "case"]))
    'case'
    """
    values = [str(value) for value in series.dropna().unique()]
    if not values:
        return None
    if len(values) > 1:
        raise ValueError("dispatch Scenario column must contain at most one value per result attribute.")
    return values[0]


def _single_attribute(
    system: System,
    attribute_type: type[SDOMResultAttribute],
    *,
    filters: _ResultFilters,
) -> SDOMResultAttribute:
    """Return exactly one matching attribute.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    attribute_type : type[SDOMResultAttribute]
        Attribute type to query.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    SDOMResultAttribute
        Single matching attribute.

    Raises
    ------
    ValueError
        If zero or multiple attributes match.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> _single_attribute(load_system("Data/no_exchange_run_of_river"), SDOMOptimizationResult, filters=_ResultFilters(run_id="missing")) # doctest: +ELLIPSIS
    Traceback (most recent call last):
    ...
    ValueError: No SDOMOptimizationResult found...
    """
    matches = [attribute for _, attribute in _iter_result_attributes(system, attribute_type, filters=filters)]
    if not matches:
        raise ValueError(f"No {attribute_type.__name__} found for run_id={filters.run_id!r}.")
    if len(matches) > 1:
        raise ValueError(f"Multiple {attribute_type.__name__} attributes found for run_id={filters.run_id!r}.")
    return matches[0]


def _optional_single_attribute(
    system: System,
    attribute_type: type[SDOMResultAttribute],
    *,
    filters: _ResultFilters,
) -> SDOMResultAttribute | None:
    """Return zero or one matching attribute.

    Parameters
    ----------
    system : infrasys.System
        System to inspect.
    attribute_type : type[SDOMResultAttribute]
        Attribute type to query.
    filters : _ResultFilters
        Result filters.

    Returns
    -------
    SDOMResultAttribute | None
        Matching attribute or ``None``.

    Raises
    ------
    ValueError
        If multiple attributes match.

    Examples
    --------
    >>> from sdom.infrasys_integration.make_system import load_system
    >>> _optional_single_attribute(load_system("Data/no_exchange_run_of_river"), SDOMOptimizationResult, filters=_ResultFilters()) is None
    True
    """
    matches = [attribute for _, attribute in _iter_result_attributes(system, attribute_type, filters=filters)]
    if len(matches) > 1:
        raise ValueError(f"Multiple {attribute_type.__name__} attributes found for run_id={filters.run_id!r}.")
    return matches[0] if matches else None
