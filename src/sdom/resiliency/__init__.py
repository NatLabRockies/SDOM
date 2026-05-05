"""Public API for the SDOM resiliency-evaluation module.

Phases 1-5 expose the data loader, demand-charge imports formulation, the
baseline dispatch builder/runner, the outage scenario specification and
per-hour outage builder, the parallel resiliency runner, and the supporting
dataclasses.
"""

from __future__ import annotations

from sdom.resiliency.data_loader import load_designed_system
from sdom.resiliency.dispatch_model import (
    build_baseline_dispatch,
    run_baseline_dispatch,
)
from sdom.resiliency.evaluate import evaluate_resiliency
from sdom.resiliency.formulations_imports_demand_charges import (
    add_imports_with_demand_charges,
)
from sdom.resiliency.outage_dispatch import build_outage_dispatch
from sdom.resiliency.outage_scenarios import (
    MUST_RUN_COMPONENTS,
    OutageSpec,
    VALID_COMPONENTS,
)
from sdom.resiliency.plotting import plot_metric_distribution
from sdom.resiliency.runner import run_resiliency_evaluation
from sdom.resiliency.system_state import (
    BaselineDispatchResults,
    BaselineState,
    DesignedSystem,
    ResiliencyResults,
)

__all__ = [
    "BaselineDispatchResults",
    "BaselineState",
    "DesignedSystem",
    "MUST_RUN_COMPONENTS",
    "OutageSpec",
    "ResiliencyResults",
    "VALID_COMPONENTS",
    "add_imports_with_demand_charges",
    "build_baseline_dispatch",
    "build_outage_dispatch",
    "evaluate_resiliency",
    "load_designed_system",
    "plot_metric_distribution",
    "run_baseline_dispatch",
    "run_resiliency_evaluation",
]
