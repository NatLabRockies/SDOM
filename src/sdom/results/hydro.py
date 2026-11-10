"""Calculate hydro-budget energy and validate per-period residuals."""


import numpy as np
from pyomo.environ import value as pyo_value

_HYDRO_BUDGET_ABSOLUTE_TOLERANCE_MWH = 1e-3


_HYDRO_BUDGET_RELATIVE_TOLERANCE = 5e-8


def _validate_hydro_budget_residuals(
    host,
    unused: np.ndarray,
    *,
    budget: np.ndarray,
    dispatched: np.ndarray,
    equality: np.ndarray,
) -> None:
    """Validate each hydro period before residual normalization or aggregation.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area exposing ``hydro.budget_constraint``.
    unused : numpy.ndarray
        Budget minus dispatch for each period, in MWh.
    budget : numpy.ndarray
        Unscaled budget energy for each period, in MWh.
    dispatched : numpy.ndarray
        Actual dispatch energy for each period, in MWh.
    equality : numpy.ndarray
        Boolean mask identifying equality budget constraints.

    Raises
    ------
    ValueError
        If a period violates its budget relation beyond numerical tolerance.

    Notes
    -----
    The tolerance is ``1e-3 + 5e-8 * max(abs(budget), abs(dispatch))`` MWh
    per period. The relative term accommodates eight-significant-digit
    solver output.
    """
    tolerance = _HYDRO_BUDGET_ABSOLUTE_TOLERANCE_MWH + (
        _HYDRO_BUDGET_RELATIVE_TOLERANCE * np.maximum(np.abs(budget), np.abs(dispatched))
    )
    violations = (unused < -tolerance) | (equality & (np.abs(unused) > tolerance))
    if violations.any():
        periods = list(host.hydro.budget_constraint)
        details = "; ".join(
            f"period {periods[index]}: budget={budget[index]:.9g} MWh, "
            f"dispatch={dispatched[index]:.9g} MWh, unused={unused[index]:.9g} MWh, "
            f"tolerance={tolerance[index]:.9g} MWh"
            for index in np.flatnonzero(violations)
        )
        raise ValueError(f"Hydro budget violation in {host.name}, {details}")


def _collect_hydro_budget_energy(host, generation: np.ndarray) -> tuple[float, float]:
    """Collect available and unused hydro budget energy over modeled periods.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area exposing ``h`` and ``hydro``.
    generation : numpy.ndarray
        Existing hourly hydro dispatch values in modeled-hour order, in MW.

    Returns
    -------
    tuple of float
        Total unscaled budget and unused budget energy, in MWh.
        Run-of-river returns two zeros.

    Raises
    ------
    ValueError
        If hydro dispatch is incomplete or nonfinite, or a period violates
        its budget relation beyond numerical tolerance.

    Notes
    -----
    One-hour dispatch values sum to MWh. Budgets come from the unscaled
    reference profile, not hourly profile-minus-dispatch differences.
    :func:`_validate_hydro_budget_residuals` rejects material excess dispatch
    and either material equality residual before aggregation, using its
    documented tolerance. Accepted equality residuals and tiny negative
    upper-bound residuals report zero; positive upper-bound unused energy
    is preserved, even below tolerance.
    """
    hydro = host.hydro
    if not hasattr(hydro, "budget_constraint"):
        return 0.0, 0.0
    if generation.shape != (len(host.h),):
        raise ValueError(f"Incomplete hydro dispatch for {host.name}; expected {len(host.h)} hourly values.")
    interval = int(pyo_value(hydro.budget_scalar))
    profile = np.fromiter(
        (pyo_value(hydro.ts_parameter[hour]) for hour in host.h),
        dtype=float,
        count=len(host.h),
    )
    if not np.isfinite(profile).all() or not np.isfinite(generation).all():
        raise ValueError(f"Nonfinite hydro budget or dispatch for {host.name}.")
    budget = profile.reshape(-1, interval).sum(axis=1)
    dispatched = generation.reshape(-1, interval).sum(axis=1)
    unused = budget - dispatched
    periods = list(hydro.budget_constraint)
    equality = np.fromiter(
        (hydro.budget_constraint[period].equality for period in periods), dtype=bool, count=len(periods)
    )
    _validate_hydro_budget_residuals(host, unused, budget=budget, dispatched=dispatched, equality=equality)
    unused = np.where(equality | (unused < 0), 0.0, unused)
    return float(budget.sum()), float(unused.sum())
