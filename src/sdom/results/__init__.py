"""Expose the backward-compatible results API over focused implementation modules."""

from .collect_individual_host_results import (
    _collect_thermal_generation_dataframe as _collect_thermal_generation_dataframe,
)
from .containers import OptimizationResults
from .pricing import collect_marginal_prices_from_model
from .results_collection_main import collect_results_from_model

__all__ = [
    "OptimizationResults",
    "collect_marginal_prices_from_model",
    "collect_results_from_model",
]
