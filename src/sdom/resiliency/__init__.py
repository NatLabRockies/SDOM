"""Public API for the SDOM resiliency-evaluation module.

Phases 1-3 expose the data loader, demand-charge imports formulation, the
baseline dispatch builder/runner and the supporting dataclasses.
"""

from __future__ import annotations

from sdom.resiliency.data_loader import load_designed_system
from sdom.resiliency.dispatch_model import (
    build_baseline_dispatch,
    run_baseline_dispatch,
)
from sdom.resiliency.formulations_imports_demand_charges import (
    add_imports_with_demand_charges,
)
from sdom.resiliency.system_state import (
    BaselineDispatchResults,
    BaselineState,
    DesignedSystem,
)

__all__ = [
    "BaselineDispatchResults",
    "BaselineState",
    "DesignedSystem",
    "add_imports_with_demand_charges",
    "build_baseline_dispatch",
    "load_designed_system",
    "run_baseline_dispatch",
]
