"""Golden-file regression test for the legacy fast-path of ``initialize_model``.

The ``initialize_model`` dispatcher (see
``dev_guidelines/zonal_model/PRD.md`` \u00a75.7) routes single-area
``CopperPlateNetwork`` data through
:func:`sdom.optimization_main._initialize_model_copperplate`, which is the
historical model body preserved verbatim. This test locks the behaviour by
asserting that every legacy data folder produces the same objective value
as the existing test suite expects.

If this test starts failing, the most likely cause is that the legacy code
path was modified \u2014 revert the change and instead extend the per-area
Block path without touching ``_initialize_model_copperplate``.
"""

from __future__ import annotations

import os

import pytest

from sdom import (
    get_default_solver_config_dict,
    initialize_model,
    load_data,
    run_solver,
)
from sdom.constants import COPPER_PLATE_NETWORK
from sdom.io_manager import get_network_formulation
from sdom.optimization_main import _initialize_model_copperplate

from constants_test import (
    REL_PATH_DATA_DAILY_HYDRO_BUDGET_IMP_EXP_TEST,
    REL_PATH_DATA_DAILY_HYDRO_BUDGET_TEST,
    REL_PATH_DATA_HYDRO_BUDGET_TEST,
    REL_PATH_DATA_RUN_OF_RIVER_TEST,
)
from utils_tests import get_optimization_problem_solution_info


# (rel_data_path, n_hours, golden_total_cost, abs_tol)
LEGACY_REGRESSION_CASES = [
    pytest.param(
        REL_PATH_DATA_RUN_OF_RIVER_TEST,
        24,
        3285154847.471892,
        10.0,
        id="run_of_river_24h",
    ),
    pytest.param(
        REL_PATH_DATA_HYDRO_BUDGET_TEST,
        730,
        441627.4738187364,
        10.0,
        id="monthly_budget_730h",
    ),
    pytest.param(
        REL_PATH_DATA_DAILY_HYDRO_BUDGET_TEST,
        168,
        578101.3,
        10.0,
        id="daily_budget_168h",
    ),
    pytest.param(
        REL_PATH_DATA_DAILY_HYDRO_BUDGET_IMP_EXP_TEST,
        168,
        -77686751.88,
        10.0,
        id="daily_budget_imp_exp_168h",
    ),
]


def _abs_data_path(rel: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", rel))


@pytest.mark.parametrize("rel_path,n_hours,golden_cost,abs_tol", LEGACY_REGRESSION_CASES)
def test_legacy_fast_path_objective_is_bit_compatible(
    rel_path, n_hours, golden_cost, abs_tol
):
    """Every legacy folder must keep its historical objective under the dispatcher."""
    data = load_data(_abs_data_path(rel_path))

    # Sanity: the dispatcher should classify this as the legacy fast path.
    assert get_network_formulation(data) == COPPER_PLATE_NETWORK
    assert len(data["areas"]) == 1

    model = initialize_model(
        data, n_hours=n_hours, with_resilience_constraints=False
    )

    solver_dict = get_default_solver_config_dict(
        solver_name="highs", executable_path=""
    )
    results = run_solver(model, solver_dict)
    sol = get_optimization_problem_solution_info(results)

    assert sol["Termination condition"] == "optimal"
    assert abs(sol["Total_Cost"] - golden_cost) <= abs_tol


def test_dispatcher_delegates_to_legacy_helper(monkeypatch):
    """The CopperPlate + single-area path must call ``_initialize_model_copperplate``."""
    data = load_data(_abs_data_path(REL_PATH_DATA_RUN_OF_RIVER_TEST))

    calls = {"n": 0}

    def _spy(data_arg, *, n_hours, with_resilience_constraints, model_name):
        calls["n"] += 1
        # Delegate to the real function so the rest of the test stays valid.
        return _initialize_model_copperplate(
            data_arg,
            n_hours=n_hours,
            with_resilience_constraints=with_resilience_constraints,
            model_name=model_name,
        )

    monkeypatch.setattr(
        "sdom.optimization_main._initialize_model_copperplate", _spy
    )

    model = initialize_model(data, n_hours=24)
    assert model is not None
    assert calls["n"] == 1
