"""Multiprocessing worker function for SDOM parametric analysis.

This module contains the top-level worker function ``_run_single_case``.
It **must** be defined at module level (not nested or as a lambda) so that
``pickle`` can serialise it for ``ProcessPoolExecutor``.
"""

import copy
import logging

from ..optimization_main import initialize_model, run_solver
from .mutations import (
    _apply_scalar_mutation,
    _apply_storage_factor_mutation,
    _apply_ts_mutation,
)

logger = logging.getLogger(__name__)


def _run_single_case(case_dict: dict):
    """Evaluate one parameter combination by building and solving a fresh model.

    This is the worker function submitted to :class:`ProcessPoolExecutor`.
    Each invocation receives a fully self-contained description of the case;
    no shared state is required between processes.

    Parameters
    ----------
    case_dict : dict
        Serialisable description of the case with the following keys:

        ``"data"``
            The shared SDOM base data dict.  A deep copy is made inside
            the worker so that mutations are isolated to this case and
            the original is not modified.  This avoids creating all
            copies up-front in the parent process.
        ``"solver_config"``
            Solver configuration dict from
            :func:`sdom.optimization_main.get_default_solver_config_dict`.
        ``"n_hours"``
            Number of simulation hours.
        ``"case_name"``
            Human-readable identifier for this combination, used as the
            ``case_name`` argument to :func:`sdom.optimization_main.run_solver`.
        ``"scalar_mutations"``
            List of ``(data_key, param_name, value)`` triples to apply.
        ``"storage_factor_mutations"``
            List of ``(param_name, factor)`` pairs to apply.
        ``"ts_mutations"``
            List of ``(ts_key, factor)`` pairs to apply.

    Returns
    -------
    sdom.results.OptimizationResults
        Results dataclass.  ``is_optimal`` is ``False`` when the solver did
        not find a feasible solution or an exception was raised.
    """
    from ..results import OptimizationResults

    case_name: str = case_dict["case_name"]
    data: dict = copy.deepcopy(case_dict["data"])
    solver_config: dict = case_dict["solver_config"]
    n_hours: int = case_dict["n_hours"]

    # Apply mutations on the deep-copied data dict
    try:
        for data_key, param_name, value in case_dict.get("scalar_mutations", []):
            _apply_scalar_mutation(data, data_key, param_name, value)

        for param_name, factor in case_dict.get("storage_factor_mutations", []):
            _apply_storage_factor_mutation(data, param_name, factor)

        for ts_key, factor in case_dict.get("ts_mutations", []):
            _apply_ts_mutation(data, ts_key, factor)

        logger.info("Worker: initialising model for case '%s'", case_name)
        model = initialize_model(data, n_hours=n_hours, model_name=f"SDOM_{case_name}")

        logger.info("Worker: solving model for case '%s'", case_name)
        results = run_solver(model, solver_config, case_name=case_name)

    except Exception as exc:  # noqa: BLE001
        logger.error("Worker: case '%s' raised an exception: %s", case_name, exc, exc_info=True)
        results = OptimizationResults(
            termination_condition="exception",
            solver_status="error",
            gen_mix_target=float("nan"),
            total_cost=float("nan"),
        )

    return results
