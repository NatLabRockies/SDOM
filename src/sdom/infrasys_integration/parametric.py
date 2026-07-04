"""Parametric-study helpers for SDOM infrasys systems."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from infrasys import System

from sdom.parametric import ParametricStudy
from sdom.parametric.mutations import _apply_scalar_mutation, _apply_ts_mutation
from sdom.results import OptimizationResults

from .make_system import load_system_from_data, system_to_data_dict
from .results import add_results_to_system


class SystemParametricStudy:
    """Run parametric SDOM studies from an infrasys System.

    Parameters
    ----------
    system : infrasys.System
        Base SDOM system created by :func:`sdom.infrasys_integration.load_system`.
    solver_config : dict
        Solver configuration accepted by :class:`sdom.parametric.ParametricStudy`.
    n_hours : int, default=8760
        Number of hours to solve for every case.
    output_dir : str, optional
        Directory for legacy per-case CSV output. Use ``None`` to skip disk
        output.
    n_cores : int, optional
        Number of worker processes. Delegated to :class:`ParametricStudy`.

    Examples
    --------
    >>> from sdom import load_data
    >>> from sdom.infrasys_integration.make_system import load_system_from_data
    >>> system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
    >>> study = SystemParametricStudy(system, solver_config={}, n_hours=1, n_cores=1)
    >>> study.add_genmix_sweep([0.8, 1.0])
    >>> len(study._study._build_case_dicts())
    2
    """

    def __init__(
        self,
        system: System,
        solver_config: dict,
        n_hours: int = 8760,
        output_dir: str | None = None,
        n_cores: int | None = None,
    ) -> None:
        self._system = system
        self._study = ParametricStudy(
            base_data=system_to_data_dict(system),
            solver_config=solver_config,
            n_hours=n_hours,
            output_dir=output_dir,
            n_cores=n_cores,
        )

    @property
    def case_metadata(self) -> list[dict[str, Any]]:
        """Return per-case metadata from the most recent run.

        Returns
        -------
        list[dict[str, Any]]
            Case metadata produced by the underlying legacy parametric study.

        Examples
        --------
        >>> from sdom import load_data
        >>> from sdom.infrasys_integration.make_system import load_system_from_data
        >>> system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
        >>> SystemParametricStudy(system, solver_config={}).case_metadata
        []
        """
        return self._study.case_metadata

    @property
    def output_dir(self) -> str | None:
        """Return the configured output directory.

        Returns
        -------
        str | None
            Output directory delegated to the legacy study.

        Examples
        --------
        >>> from sdom import load_data
        >>> from sdom.infrasys_integration.make_system import load_system_from_data
        >>> system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
        >>> SystemParametricStudy(system, solver_config={}).output_dir is None
        True
        """
        return self._study.output_dir

    def add_scalar_sweep(self, data_key: str, parameter_name: str, values: Sequence[int | float]) -> None:
        """Register a scalar sweep on the system's backing SDOM data.

        Parameters
        ----------
        data_key : str
            Data dictionary key containing the scalar table.
        parameter_name : str
            Scalar row label to mutate.
        values : sequence of int or float
            Values to evaluate.

        Returns
        -------
        None
            Sweep registration mutates the study in place.

        Examples
        --------
        >>> from sdom import load_data
        >>> from sdom.infrasys_integration.make_system import load_system_from_data
        >>> system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
        >>> study = SystemParametricStudy(system, solver_config={})
        >>> study.add_scalar_sweep("scalars", "GenMix_Target", [0.8])
        """
        self._study.add_scalar_sweep(data_key, parameter_name, list(values))

    def add_genmix_sweep(self, values: Sequence[int | float]) -> None:
        """Register a GenMix target sweep.

        Parameters
        ----------
        values : sequence of int or float
            GenMix target values to evaluate.

        Returns
        -------
        None
            Sweep registration mutates the study in place.

        Examples
        --------
        >>> from sdom import load_data
        >>> from sdom.infrasys_integration.make_system import load_system_from_data
        >>> system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
        >>> study = SystemParametricStudy(system, solver_config={})
        >>> study.add_genmix_sweep([0.8, 1.0])
        """
        self.add_scalar_sweep("scalars", "GenMix_Target", values)

    def add_storage_factor_sweep(self, parameter_name: str, factors: Sequence[int | float]) -> None:
        """Register a storage-parameter factor sweep.

        Parameters
        ----------
        parameter_name : str
            Storage parameter row label to scale.
        factors : sequence of int or float
            Multiplicative factors to evaluate.

        Returns
        -------
        None
            Sweep registration mutates the study in place.

        Examples
        --------
        >>> from sdom import load_data
        >>> from sdom.infrasys_integration.make_system import load_system_from_data
        >>> system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
        >>> study = SystemParametricStudy(system, solver_config={})
        >>> study.add_storage_factor_sweep("P_Capex", [1.0])
        """
        self._study.add_storage_factor_sweep(parameter_name, list(factors))

    def add_ts_sweep(self, ts_key: str, factors: Sequence[int | float]) -> None:
        """Register a time-series factor sweep.

        Parameters
        ----------
        ts_key : str
            Time-series data key to scale.
        factors : sequence of int or float
            Multiplicative factors to evaluate.

        Returns
        -------
        None
            Sweep registration mutates the study in place.

        Examples
        --------
        >>> from sdom import load_data
        >>> from sdom.infrasys_integration.make_system import load_system_from_data
        >>> system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
        >>> study = SystemParametricStudy(system, solver_config={})
        >>> study.add_ts_sweep("load_data", [1.0])
        """
        self._study.add_ts_sweep(ts_key, list(factors))

    def run(self) -> list[OptimizationResults]:
        """Execute all registered system parametric cases.

        Returns
        -------
        list[sdom.results.OptimizationResults]
            One optimization result per case.

        Examples
        --------
        >>> from sdom import load_data
        >>> from sdom.infrasys_integration.make_system import load_system_from_data
        >>> system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
        >>> isinstance(SystemParametricStudy(system, solver_config={}).run(), list)
        True
        """
        return self._study.run()


def apply_scalar_sweep_to_system(
    system: System,
    parameter_name: str,
    value: int | float,
    *,
    data_key: str = "scalars",
) -> System:
    """Create a new System with one scalar value changed.

    Parameters
    ----------
    system : infrasys.System
        Base SDOM system with compatibility source data.
    parameter_name : str
        Scalar row label to mutate.
    value : int or float
        Replacement scalar value.
    data_key : str, default="scalars"
        Data dictionary key containing the scalar table.

    Returns
    -------
    infrasys.System
        New system built from copied and mutated source data.

    Examples
    --------
    >>> from sdom import load_data
    >>> from sdom.infrasys_integration.make_system import load_system_from_data, system_to_data_dict
    >>> system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
    >>> mutated = apply_scalar_sweep_to_system(system, "GenMix_Target", 0.9)
    >>> float(system_to_data_dict(mutated)["scalars"].loc["GenMix_Target", "Value"])
    0.9
    """
    data = copy.deepcopy(system_to_data_dict(system))
    _apply_scalar_mutation(data, data_key, parameter_name, value)
    return load_system_from_data(data, name=system.name)


def apply_time_series_sweep_to_system(system: System, ts_key: str, factor: int | float) -> System:
    """Create a new System with one time-series table scaled.

    Parameters
    ----------
    system : infrasys.System
        Base SDOM system with compatibility source data.
    ts_key : str
        Time-series data key to scale.
    factor : int or float
        Multiplicative scaling factor.

    Returns
    -------
    infrasys.System
        New system built from copied and mutated source data.

    Examples
    --------
    >>> from sdom import load_data
    >>> from sdom.infrasys_integration.make_system import load_system_from_data, system_to_data_dict
    >>> system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
    >>> mutated = apply_time_series_sweep_to_system(system, "load_data", 1.0)
    >>> len(system_to_data_dict(mutated)["load_data"])
    8760
    """
    data = copy.deepcopy(system_to_data_dict(system))
    _apply_ts_mutation(data, ts_key, float(factor))
    return load_system_from_data(data, name=system.name)


def add_parametric_results_to_system(
    system: System,
    study: ParametricStudy | SystemParametricStudy,
    results: Sequence[OptimizationResults],
    *,
    run_id: str,
) -> System:
    """Attach all parametric case results to one System.

    Parameters
    ----------
    system : infrasys.System
        System to mutate with result supplemental attributes.
    study : ParametricStudy or SystemParametricStudy
        Completed study whose ``case_metadata`` corresponds to ``results``.
    results : sequence of OptimizationResults
        Per-case optimization results.
    run_id : str
        Identifier for this parametric run. Use a distinct value for each
        independent parametric run.

    Returns
    -------
    infrasys.System
        The same ``system`` instance with every case result attached.

    Raises
    ------
    ValueError
        If ``run_id`` is empty or metadata/result lengths differ.

    Examples
    --------
    >>> from sdom import load_data
    >>> from sdom.results import OptimizationResults
    >>> from sdom.infrasys_integration.make_system import load_system_from_data
    >>> system = load_system_from_data(load_data("Data/no_exchange_run_of_river"))
    >>> study = SystemParametricStudy(system, solver_config={})
    >>> study._study._case_metadata = [{"case_name": "case-a", "case_index": 0, "GenMix_Target": 0.8}]
    >>> add_parametric_results_to_system(system, study, [OptimizationResults(total_cost=1.0)], run_id="run-1") is system
    True
    """
    if not run_id:
        raise ValueError("run_id must be a non-empty string.")

    case_metadata = _case_metadata(study)
    if len(case_metadata) != len(results):
        raise ValueError(
            "case metadata length must match results length "
            f"({len(case_metadata)} metadata rows, {len(results)} results)."
        )

    for metadata, result in zip(case_metadata, results, strict=True):
        case_index = int(metadata.get("case_index", 0))
        case_name = str(metadata.get("case_name", f"case-{case_index}"))
        scenario_id = f"{run_id}:{case_index}"
        add_results_to_system(
            system,
            result,
            run_id=run_id,
            scenario_name=scenario_id,
            case_name=case_name,
            metadata=_parametric_case_metadata(metadata, run_id=run_id, scenario_id=scenario_id),
        )
    return system


def _case_metadata(study: ParametricStudy | SystemParametricStudy) -> list[dict[str, Any]]:
    """Return study case metadata as plain dictionaries.

    Parameters
    ----------
    study : ParametricStudy or SystemParametricStudy
        Study with a ``case_metadata`` property.

    Returns
    -------
    list[dict[str, Any]]
        Copied case metadata rows.

    Examples
    --------
    >>> class Study:
    ...     case_metadata = [{"case_name": "a"}]
    >>> _case_metadata(Study())
    [{'case_name': 'a'}]
    """
    return [dict(row) for row in study.case_metadata]


def _parametric_case_metadata(
    metadata: Mapping[str, Any],
    *,
    run_id: str,
    scenario_id: str,
) -> dict[str, Any]:
    """Build JSON-compatible metadata for one parametric case.

    Parameters
    ----------
    metadata : mapping of str to Any
        Case metadata from a parametric study.
    run_id : str
        Parametric run identifier.
    scenario_id : str
        Stable scenario identifier for the case within ``run_id``.

    Returns
    -------
    dict[str, Any]
        Metadata including case identity and sweep values.

    Examples
    --------
    >>> _parametric_case_metadata({"case_name": "case-a", "case_index": 0, "GenMix_Target": 0.8}, run_id="run", scenario_id="run:0")["sweep_values"]
    {'GenMix_Target': 0.8}
    """
    case_name = str(metadata.get("case_name", ""))
    case_index = int(metadata.get("case_index", 0))
    sweep_values = {
        str(key): value
        for key, value in metadata.items()
        if key not in {"case_name", "case_index", "scenario_id"}
    }
    return {
        "parametric_run_id": run_id,
        "scenario_id": scenario_id,
        "case_name": case_name,
        "case_index": case_index,
        "sweep_values": sweep_values,
    }


__all__ = [
    "SystemParametricStudy",
    "add_parametric_results_to_system",
    "apply_scalar_sweep_to_system",
    "apply_time_series_sweep_to_system",
]
