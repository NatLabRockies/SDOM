"""Top-level convenience helper for the SDOM Resiliency Evaluation module.

Phase 7 / Deliverable A.

Chains the four building blocks of the module into a single call:

1. :func:`sdom.resiliency.load_designed_system` -- read snapshot + previous
   stage CSVs into a :class:`DesignedSystem`.
2. :func:`sdom.resiliency.build_baseline_dispatch` -- assemble the
   fixed-capacity annual-dispatch Pyomo LP.
3. :func:`sdom.resiliency.run_baseline_dispatch` -- solve the baseline and
   collect per-hour trajectories.
4. :func:`sdom.resiliency.run_resiliency_evaluation` -- fan out the per-hour
   outage problems and aggregate the metrics.

The function intentionally introduces *no* new defaults beyond those of the
underlying APIs so that it preserves their behaviour exactly.
"""

from __future__ import annotations

import logging

from sdom.resiliency.data_loader import load_designed_system
from sdom.resiliency.dispatch_model import (
    build_baseline_dispatch,
    run_baseline_dispatch,
)
from sdom.resiliency.runner import run_resiliency_evaluation


logger = logging.getLogger(__name__)


__all__ = ["evaluate_resiliency"]


def evaluate_resiliency(
    snapshot_dir,
    *,
    inputs_dir,
    outage_spec,
    year=2030,
    scenario_id=1,
    n_hours=8760,
    hours=None,
    min_soc_per_tech=None,
    slack_penalty=10_000.0,
    curtailment_penalty=0.0,
    formulation_overrides=None,
    n_workers=None,
    solver="highs",
    solver_options=None,
):
    """End-to-end helper: load -> baseline dispatch -> outage evaluation.

    Parameters
    ----------
    snapshot_dir : str or pathlib.Path
        Snapshot directory passed to :func:`load_designed_system`.
    inputs_dir : str or pathlib.Path
        Previous-stage inputs directory.
    outage_spec : OutageSpec
        Outage scenario specification.
    year : int, optional
        Calendar year of the snapshot. Default ``2030``.
    scenario_id : int, optional
        Scenario / Run id resolved from the snapshot CSVs. Default ``1``.
    n_hours : int, optional
        Baseline-dispatch horizon length. Default ``8760``.
    hours : iterable of int, optional
        Anchor hours to evaluate. ``None`` (default) evaluates every hour
        ``1..n_hours``.
    min_soc_per_tech : dict, optional
        Operational SOC floor per storage tech (fraction of ``Cap_E``);
        forwarded to both the baseline builder and the per-hour outage
        runner. Default ``None``.
    slack_penalty : float, optional
        Penalty (USD/MWh) applied to slack ``u[t]`` in the outage LP.
        Default ``10_000``.
    curtailment_penalty : float, optional
        Penalty applied to curtailed VRE energy (USD/MWh). Default ``0``.
    formulation_overrides : dict, optional
        Component formulation overrides forwarded to
        :func:`load_designed_system`.
    n_workers : int, optional
        Worker pool size for the per-hour evaluation. ``None`` (default)
        resolves to ``max(1, os.cpu_count() - 1)`` inside
        :func:`run_resiliency_evaluation`.
    solver : str, optional
        Pyomo solver name. ``"highs"`` first tries ``appsi_highs``.
        Default ``"highs"``.
    solver_options : dict, optional
        Solver options forwarded to both the baseline solve and every
        per-hour outage solve.

    Returns
    -------
    ResiliencyResults
        Per-hour records (sorted by anchor hour) plus run metadata
        including ``n_workers_used``, ``n_hours``, ``solver`` and the
        ``outage_spec`` reference.

    See Also
    --------
    sdom.resiliency.load_designed_system
    sdom.resiliency.build_baseline_dispatch
    sdom.resiliency.run_baseline_dispatch
    sdom.resiliency.run_resiliency_evaluation

    Examples
    --------
    >>> from sdom.resiliency import OutageSpec, evaluate_resiliency
    >>> spec = OutageSpec(
    ...     duration_hours=4,
    ...     recovery_hours=4,
    ...     outaged_assets={"imports": "all"},
    ... )
    >>> results = evaluate_resiliency(
    ...     "snapshot/",
    ...     inputs_dir="inputs/",
    ...     outage_spec=spec,
    ...     n_hours=24,
    ...     hours=[1, 5, 10],
    ...     n_workers=1,
    ... )  # doctest: +SKIP
    """
    logger.info(
        "evaluate_resiliency: starting end-to-end pipeline (year=%s, scenario_id=%s, "
        "n_hours=%s).",
        year,
        scenario_id,
        n_hours,
    )
    logger.info("Step 1/4: loading designed system from %s.", snapshot_dir)
    designed_system = load_designed_system(
        snapshot_dir,
        inputs_dir=inputs_dir,
        year=year,
        scenario_id=scenario_id,
        formulation_overrides=formulation_overrides,
    )
    logger.info("Step 2/4: building baseline dispatch model.")
    model = build_baseline_dispatch(
        designed_system,
        n_hours=n_hours,
        min_soc_per_tech=min_soc_per_tech,
        curtailment_penalty=curtailment_penalty,
    )
    logger.info("Step 3/4: solving baseline dispatch with solver=%r.", solver)
    baseline_results = run_baseline_dispatch(
        model,
        solver=solver,
        solver_options=solver_options,
    )
    logger.info("Step 4/4: running per-hour resiliency evaluation.")
    results = run_resiliency_evaluation(
        baseline_results,
        outage_spec=outage_spec,
        hours=hours,
        slack_penalty=slack_penalty,
        curtailment_penalty=curtailment_penalty,
        min_soc_per_tech=min_soc_per_tech,
        n_hours=n_hours,
        n_workers=n_workers,
        solver=solver,
        solver_options=solver_options,
    )
    logger.info("evaluate_resiliency: pipeline complete.")
    return results
