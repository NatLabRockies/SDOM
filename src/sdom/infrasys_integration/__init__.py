"""Opt-in infrasys integration namespace for SDOM.

This package contains typed infrasys models and adapter APIs used to
incrementally add System/Component workflows without changing existing SDOM
CSV/dict entry points.
"""

from __future__ import annotations

from .make_system import drop_system_source_data
from .parametric import (
    SystemParametricStudy,
    add_parametric_results_to_system,
    apply_scalar_sweep_to_system,
    apply_time_series_sweep_to_system,
)
from .plotting import plot_system_results
from .results import (
    add_results_to_system,
    optimization_results_from_system,
    query_result_attributes,
)

__all__ = [
    "SystemParametricStudy",
    "add_parametric_results_to_system",
    "add_results_to_system",
    "apply_scalar_sweep_to_system",
    "apply_time_series_sweep_to_system",
    "drop_system_source_data",
    "optimization_results_from_system",
    "plot_system_results",
    "query_result_attributes",
]
