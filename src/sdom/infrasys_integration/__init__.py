"""Opt-in infrasys integration namespace for SDOM.

This package contains typed infrasys models and adapter APIs used to
incrementally add System/Component workflows without changing existing SDOM
CSV/dict entry points.
"""

from __future__ import annotations

from .results import (
    add_results_to_system,
    optimization_results_from_system,
    query_result_attributes,
)

__all__ = [
    "add_results_to_system",
    "optimization_results_from_system",
    "query_result_attributes",
]
