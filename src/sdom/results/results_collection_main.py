"""Route solved models to the appropriate results collector."""


from .collect_copperplate_resuts import _collect_results_copperplate
from .collect_zonal_resuts import _collect_results_zonal
from .containers import OptimizationResults


def collect_results_from_model(model, solver_result, case_name: str = "run") -> OptimizationResults:
    """Collect all optimization results from a solved Pyomo model.

    Dispatches to the legacy single-area collector or the zonal collector
    based on whether ``model`` exposes a top-level area set ``model.A`` and
    a per-area ``Block`` ``model.area`` (the convention established by
    :func:`sdom.optimization_main._initialize_model_zonal`).

    On the **legacy** path the returned :class:`OptimizationResults` preserves
    existing metrics and adds two system-wide hydro-curtailment summary rows.
    Legacy objectives remain locked by ``tests/test_zonal_legacy_regression.py``.
    On the **zonal** path the
    same top-level DataFrames (``generation_df``, ``storage_df``,
    ``thermal_generation_df``, ``installed_plants_df``) are populated as the
    concatenation of per-area frames with a leading ``Area`` column, and
    a battery of new per-area dict fields plus
    :attr:`OptimizationResults.interregional_exchanges_df` are filled in.
    See PRD §2.4 / §6.1.

    Parameters
    ----------
    model : pyomo.core.base.PyomoModel.ConcreteModel
        The solved Pyomo model instance.
    solver_result : pyomo.opt.SolverResults
        The solver results object from ``solver.solve()``.
    case_name : str, optional
        Case identifier for the scenario column. Defaults to ``"run"``.

    Returns
    -------
    OptimizationResults
        A dataclass containing all optimization results.

    Raises
    ------
    ValueError
        If a hydro budget period materially violates its equality or
        upper-bound constraint, or required budget dispatch is nonfinite.

    Notes
    -----
    Under the zonal path, ``summary_df`` contains system-level aggregates and
    :attr:`OptimizationResults.area_summary_df` contains per-area summaries.
    ``interregional_exchanges_df`` is available for zonal CSV export.
    Hydro curtailment means unused period budget energy, not physical water
    spill. Budgets and unused energy are summed before calculating the
    system percentage. See :func:`_collect_hydro_budget_energy` for numerical
    tolerance handling; run-of-river reports zero.
    """
    is_zonal = hasattr(model, "A") and hasattr(model, "area")
    if is_zonal:
        return _collect_results_zonal(model, solver_result, case_name=case_name)
    return _collect_results_copperplate(model, solver_result, case_name=case_name)
