"""Parallel orchestrator for the SDOM Resiliency Evaluation module (Phase 5).

This module exposes :func:`run_resiliency_evaluation`, which fans out one
short-horizon outage LP per anchor hour, solves each independently with HiGHS,
and aggregates the per-hour outcomes into a :class:`ResiliencyResults`
container.

Each per-hour problem is built by :func:`sdom.resiliency.build_outage_dispatch`
(Phase 4) and solved in its own (possibly remote) Python process. Workers do
not exchange Pyomo objects: the orchestrator pickles the lightweight
``DesignedSystem`` / ``BaselineDispatchResults`` / ``OutageSpec`` payload and
each worker rebuilds, solves and discards its model independently.

Math reference: ``dev_guidelines/resiliency evaluation/math_model.md``
section 7 (per-hour metrics: EUE, USE_hours, max unserved MW).
"""

from __future__ import annotations

import logging
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Iterable

import pandas as pd
import pyomo.environ as pyo

from sdom.resiliency.outage_dispatch import build_outage_dispatch
from sdom.resiliency.outage_scenarios import OutageSpec
from sdom.resiliency.system_state import (
    BaselineDispatchResults,
    DesignedSystem,
    ResiliencyResults,
)


logger = logging.getLogger(__name__)


__all__ = ["run_resiliency_evaluation"]


# Module-level handle so tests can monkeypatch the underlying builder to
# simulate a worker failure on a specific hour. Workers reach this through
# ``_solve_one_hour`` which dereferences the symbol at call time.
_build_outage_dispatch = build_outage_dispatch

# Slack tolerance used when counting hours with unserved energy.
_USE_EPS = 1e-6

# Per-hour record schema (kept in one place for column ordering).
_PER_HOUR_COLUMNS = [
    "EUE",
    "USE_hours",
    "max_unserved_MW",
    "objective_value",
    "solver_status",
    "solve_time_s",
    "truncated",
    "error_message",
]


def _resolve_solver(solver: str):
    """Return a Pyomo solver factory, preferring ``appsi_highs`` for ``highs``.

    Parameters
    ----------
    solver : str
        Solver name. ``"highs"`` first tries ``appsi_highs`` and falls back
        to ``highs``; any other value is forwarded as-is to
        :func:`pyomo.environ.SolverFactory`.

    Returns
    -------
    pyomo.opt.solver.SolverBase
    """
    if solver == "highs":
        for name in ("appsi_highs", "highs"):
            try:
                s = pyo.SolverFactory(name)
                if s is not None and s.available(exception_flag=False):
                    return s
            except Exception:  # pragma: no cover - solver discovery
                continue
        return pyo.SolverFactory("highs")
    return pyo.SolverFactory(solver)


def _compute_truncation(
    *,
    start_hour: int,
    duration_hours: int,
    max_recovery: int,
    n_hours: int,
) -> bool:
    intended_end = start_hour + duration_hours + max_recovery - 1
    clipped_end = min(intended_end, n_hours)
    return clipped_end < intended_end


def _solve_one_hour(payload: dict[str, Any]) -> dict[str, Any]:
    """Build, solve and summarise a single-hour outage LP.

    Module-level (picklable) so it can be dispatched by a
    :class:`concurrent.futures.ProcessPoolExecutor` on Windows ``spawn``
    start method.

    Parameters
    ----------
    payload : dict
        Flat dictionary with keys
        ``baseline_results``, ``outage_spec``, ``designed_system``,
        ``start_hour``, ``slack_penalty``, ``curtailment_penalty``,
        ``min_soc_per_tech``, ``n_hours``, ``solver``, ``solver_options``.

    Returns
    -------
    dict
        Per-hour record with keys matching :data:`_PER_HOUR_COLUMNS` plus
        ``"start_hour"``. On a worker failure all numeric metrics are set
        to 0/NaN, ``solver_status`` is ``"error"`` and ``error_message``
        carries the formatted exception.
    """
    start_hour = int(payload["start_hour"])
    n_hours = int(payload["n_hours"])
    outage_spec: OutageSpec = payload["outage_spec"]
    designed_system: DesignedSystem = payload["designed_system"]

    duration_hours = int(outage_spec.duration_hours)
    recovery_per_tech = outage_spec.resolve_recovery_hours(designed_system)
    max_recovery = max(recovery_per_tech.values()) if recovery_per_tech else 0
    truncated = _compute_truncation(
        start_hour=start_hour,
        duration_hours=duration_hours,
        max_recovery=max_recovery,
        n_hours=n_hours,
    )

    record: dict[str, Any] = {
        "start_hour": start_hour,
        "EUE": 0.0,
        "USE_hours": 0,
        "max_unserved_MW": 0.0,
        "objective_value": float("nan"),
        "solver_status": "error",
        "solve_time_s": 0.0,
        "truncated": bool(truncated),
        "error_message": "",
    }

    t0 = time.perf_counter()
    try:
        model = _build_outage_dispatch(
            payload["baseline_results"],
            start_hour=start_hour,
            outage_spec=outage_spec,
            designed_system=designed_system,
            slack_penalty=float(payload["slack_penalty"]),
            curtailment_penalty=float(payload["curtailment_penalty"]),
            min_soc_per_tech=payload.get("min_soc_per_tech"),
            n_hours=n_hours,
        )
        solver = _resolve_solver(str(payload["solver"]))
        solver_options = payload.get("solver_options") or {}
        res = solver.solve(model, options=solver_options)
        status = str(res.solver.termination_condition)

        u_values = [float(pyo.value(model.u[t])) for t in model.h]
        eue = float(sum(u_values))
        use_hours = int(sum(1 for v in u_values if v > _USE_EPS))
        max_unserved = float(max(u_values)) if u_values else 0.0
        obj = float(pyo.value(model.objective))

        record.update(
            EUE=eue,
            USE_hours=use_hours,
            max_unserved_MW=max_unserved,
            objective_value=obj,
            solver_status=status,
            error_message="",
        )
    except Exception as exc:  # noqa: BLE001 - failure isolation by design
        record["solver_status"] = "error"
        record["error_message"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        record["solve_time_s"] = float(time.perf_counter() - t0)

    return record


def _resolve_designed_system(
    baseline_results: BaselineDispatchResults,
    designed_system: DesignedSystem | None,
) -> DesignedSystem:
    if designed_system is not None:
        if not isinstance(designed_system, DesignedSystem):
            raise TypeError("designed_system must be a DesignedSystem instance.")
        return designed_system
    md = baseline_results.metadata or {}
    ds = md.get("designed_system")
    if ds is None:
        raise ValueError(
            "designed_system was not provided and baseline_results.metadata "
            "does not contain a 'designed_system' entry. Pass the "
            "DesignedSystem explicitly via the designed_system kwarg."
        )
    if not isinstance(ds, DesignedSystem):
        raise TypeError(
            "baseline_results.metadata['designed_system'] must be a "
            "DesignedSystem instance."
        )
    return ds


def _resolve_n_workers(
    n_workers: int | None,
    n_payloads: int,
) -> int:
    if n_workers is None:
        cpu = os.cpu_count() or 1
        resolved = max(1, cpu - 1)
    else:
        resolved = int(n_workers)
        if resolved < 1:
            raise ValueError("n_workers must be >= 1.")
    # Never spawn more workers than we have hours to evaluate.
    return max(1, min(resolved, max(1, n_payloads)))


def run_resiliency_evaluation(
    baseline_results,
    *,
    outage_spec,
    designed_system=None,
    hours=None,
    slack_penalty=10_000.0,
    curtailment_penalty=0.0,
    min_soc_per_tech=None,
    n_hours=8760,
    n_workers=None,
    solver="highs",
    solver_options=None,
):
    """Run the per-hour outage evaluation in parallel and aggregate metrics.

    For every anchor hour ``h`` in ``hours`` the runner builds the
    short-horizon outage LP via :func:`build_outage_dispatch`, solves it
    with HiGHS, and records ``EUE``, ``USE_hours``, ``max_unserved_MW``
    and the objective value. Per-hour problems are independent and are
    solved in parallel via :class:`concurrent.futures.ProcessPoolExecutor`
    when ``n_workers > 1``; ``n_workers == 1`` (or a single-hour run)
    falls back to an in-process serial loop.

    Parameters
    ----------
    baseline_results : BaselineDispatchResults
        Output of :func:`run_baseline_dispatch`. Must carry an SOC
        trajectory; if its ``metadata`` does not contain a
        ``"designed_system"`` entry, ``designed_system`` must be supplied.
    outage_spec : OutageSpec
        Outage / de-rating specification, broadcast to every anchor hour.
    designed_system : DesignedSystem, optional
        Source of truth for capacities and time series. Takes precedence
        over ``baseline_results.metadata['designed_system']`` when both
        are provided.
    hours : iterable of int, optional
        Anchor hours to evaluate. ``None`` (default) evaluates every hour
        ``1..n_hours``. Duplicates are removed; the result is sorted.
    slack_penalty : float, optional
        Penalty (USD/MWh) applied to slack ``u[t]``. Default ``10_000``.
    curtailment_penalty : float, optional
        Penalty applied to curtailed VRE energy (USD/MWh). Default ``0``.
    min_soc_per_tech : dict, optional
        Operational SOC floor per storage tech (fraction of ``Cap_E``);
        forwarded to the outage builder.
    n_hours : int, optional
        Length of the baseline horizon used for end-of-year clipping.
        Default ``8760``.
    n_workers : int, optional
        Worker pool size. ``None`` -> ``max(1, os.cpu_count() - 1)``;
        ``1`` forces serial mode. Always clamped to ``len(hours)``.
    solver : str, optional
        Pyomo solver name. ``"highs"`` first tries ``appsi_highs``.
        Default ``"highs"``.
    solver_options : dict, optional
        Solver options forwarded to ``solver.solve(..., options=...)``.

    Returns
    -------
    ResiliencyResults
        Per-hour records (sorted by ``start_hour``) plus run metadata
        including ``n_workers_used`` and a reference to ``outage_spec``.

    Raises
    ------
    ValueError
        If ``designed_system`` cannot be resolved from arguments or
        metadata, or if ``n_workers < 1``.
    TypeError
        If ``baseline_results`` is not a :class:`BaselineDispatchResults`
        instance, or ``outage_spec`` is not an :class:`OutageSpec`.

    Notes
    -----
    Failure isolation: if any worker raises an exception, that hour's
    record is marked ``solver_status="error"`` and its ``error_message``
    field carries the formatted traceback. Other hours continue normally.
    """
    if not isinstance(baseline_results, BaselineDispatchResults):
        raise TypeError(
            "baseline_results must be a BaselineDispatchResults instance."
        )
    if not isinstance(outage_spec, OutageSpec):
        raise TypeError("outage_spec must be an OutageSpec instance.")

    ds = _resolve_designed_system(baseline_results, designed_system)
    n_hours = int(n_hours)
    if n_hours <= 0:
        raise ValueError("n_hours must be a positive integer.")

    if hours is None:
        hour_list = list(range(1, n_hours + 1))
    else:
        hour_list = sorted({int(h) for h in hours})
    for h in hour_list:
        if not (1 <= h <= n_hours):
            raise ValueError(
                f"hours contains {h}, which is outside [1, {n_hours}]."
            )

    n_workers_used = _resolve_n_workers(n_workers, len(hour_list))
    logger.info(
        "Running resiliency evaluation: %d anchor hour(s), n_workers=%d, solver=%r, "
        "slack_penalty=%g.",
        len(hour_list),
        n_workers_used,
        solver,
        slack_penalty,
    )

    payloads = [
        {
            "baseline_results": baseline_results,
            "outage_spec": outage_spec,
            "designed_system": ds,
            "start_hour": h,
            "slack_penalty": float(slack_penalty),
            "curtailment_penalty": float(curtailment_penalty),
            "min_soc_per_tech": min_soc_per_tech,
            "n_hours": n_hours,
            "solver": solver,
            "solver_options": dict(solver_options) if solver_options else {},
        }
        for h in hour_list
    ]

    if not payloads:
        records: list[dict[str, Any]] = []
    elif n_workers_used == 1:
        logger.debug("Solving %d outage problem(s) serially.", len(payloads))
        records = [_solve_one_hour(p) for p in payloads]
    else:
        logger.debug(
            "Dispatching %d outage problem(s) to ProcessPoolExecutor with %d worker(s).",
            len(payloads),
            n_workers_used,
        )
        with ProcessPoolExecutor(max_workers=n_workers_used) as pool:
            # ``map`` preserves the order of ``payloads`` regardless of
            # worker completion order.
            records = list(pool.map(_solve_one_hour, payloads))

    records.sort(key=lambda r: int(r["start_hour"]))

    if records:
        df = pd.DataFrame(records)
        df = df.set_index("start_hour")
        df.index.name = "hour"
        # Ensure consistent column ordering even if a column is missing.
        for col in _PER_HOUR_COLUMNS:
            if col not in df.columns:
                df[col] = pd.NA
        df = df[_PER_HOUR_COLUMNS]
    else:
        df = pd.DataFrame(columns=_PER_HOUR_COLUMNS)
        df.index.name = "hour"

    metadata = {
        "n_workers_used": int(n_workers_used),
        "outage_spec": outage_spec,
        "n_hours": n_hours,
        "solver": solver,
        "n_hours_evaluated": len(hour_list),
    }
    n_errors = (
        int((df["solver_status"] == "error").sum())
        if "solver_status" in df.columns and not df.empty
        else 0
    )
    logger.info(
        "Resiliency evaluation complete: %d hour(s) processed, %d worker error(s).",
        len(hour_list),
        n_errors,
    )
    return ResiliencyResults(per_hour=df, metadata=metadata)
