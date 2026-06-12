"""Fixed-capacity baseline annual dispatch builder for the resiliency module.

Reuses the CEM planning-model formulations in :mod:`sdom.models` so that the
dispatch run inside the resiliency module is guaranteed to be the same model
the CEM solves — only the capacity decision variables are fixed to the
``DesignedSystem`` snapshot and (optionally) monthly demand charges are
layered on top.

Math reference: see ``dev_guidelines/resiliency evaluation/math_model.md``,
sections 4.1, 5.1, 5.2, 5.3, 5.4.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pyomo.environ as pyo

from sdom.constants import IMPORTS_EXPORTS_NOT_MODEL
from sdom.io_manager import get_formulation
from sdom.models.formulations_storage import add_storage_variable_costs
from sdom.models.formulations_thermal import (
    add_thermal_variable_costs,
)
from sdom.optimization_main import _initialize_model_copperplate
from sdom.resiliency.formulations_imports_demand_charges import (
    add_demand_charges_to_existing_imports,
)
from sdom.resiliency.system_state import BaselineDispatchResults, DesignedSystem
from sdom.utils_performance_meassure import ModelInitProfiler


logger = logging.getLogger(__name__)


__all__ = ["build_baseline_dispatch", "run_baseline_dispatch"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run_step(profiler, name, func, *args, **kwargs):
    """Run ``func(*args, **kwargs)``, optionally measuring it via ``profiler``."""
    if profiler is None:
        return func(*args, **kwargs)
    return profiler.measure_step(name, func, *args, **kwargs)


def _resolve_solver(solver: str):
    """Return a Pyomo solver factory. Tries ``appsi_<name>`` first."""
    candidates = (f"appsi_{solver}", solver) if solver else ("appsi_highs", "highs")
    for name in candidates:
        try:
            s = pyo.SolverFactory(name)
            if s is not None and s.available(exception_flag=False):
                return s
        except Exception:
            continue
    raise RuntimeError(f"Solver '{solver}' is not available.")


def _fix_var(var, value: float) -> None:
    """Fix a Pyomo Var to ``value`` and widen bounds if needed."""
    v = float(value)
    if var.has_lb() and v < var.lb:
        var.setlb(v)
    if var.has_ub() and v > var.ub:
        var.setub(v)
    var.fix(v)


def _safe_value(expr) -> float:
    """Return ``float(pyo.value(expr))`` or ``float(expr)`` for plain numbers."""
    if isinstance(expr, (int, float)):
        return float(expr)
    return float(pyo.value(expr))


def _extract_cost_breakdown(model) -> dict[str, float]:
    """Return per-component USD totals for the solved baseline dispatch.

    Reads the component Pyomo expressions stashed on the model by
    :func:`_replace_objective_with_dispatch_objective`. The sum reconciles
    to :attr:`model.dispatch_objective` (within floating-point tolerance):

    ``thermal_var + storage_var + imports - exports + demand_charges + curtailment + fom == total``.

    Returns
    -------
    dict
        Keys: ``thermal_var_USD``, ``storage_var_USD``, ``imports_USD``,
        ``exports_USD`` (positive; objective contribution is
        ``-exports_USD``), ``demand_charges_USD``, ``curtailment_USD``,
        ``fom_USD``, ``total_USD``. Empty dict when the model has no
        component metadata (i.e. not produced by
        :func:`build_baseline_dispatch`).
    """
    components = getattr(model, "_sdom_cost_components", None)
    if not components:
        return {}
    return {
        "thermal_var_USD": _safe_value(components.get("thermal_var", 0.0)),
        "storage_var_USD": _safe_value(components.get("storage_var", 0.0)),
        "imports_USD": _safe_value(components.get("imports", 0.0)),
        "exports_USD": _safe_value(components.get("exports", 0.0)),
        "demand_charges_USD": _safe_value(components.get("demand_charges", 0.0)),
        "curtailment_USD": _safe_value(components.get("curtailment", 0.0)),
        "fom_USD": _safe_value(components.get("fom", 0.0)),
        "total_USD": float(pyo.value(model.dispatch_objective)),
    }


def _fix_designed_capacities(
    model: pyo.ConcreteModel, designed_system: DesignedSystem
) -> None:
    """Pin capacity decision variables on ``model`` to ``designed_system`` values."""
    # Thermal: plant_installed_capacity[bu]
    if hasattr(model, "thermal") and hasattr(model.thermal, "plant_installed_capacity"):
        for bu in model.thermal.plants_set:
            spec = designed_system.thermal_caps.get(bu)
            cap = 0.0 if spec is None else float(spec.get("capacity_MW", 0.0))
            _fix_var(model.thermal.plant_installed_capacity[bu], cap)

    # Storage: Pcha[j], Pdis[j], Ecap[j]; capacity_fraction is binary and stays free.
    if hasattr(model, "storage") and hasattr(model.storage, "Pcha"):
        for j in model.storage.j:
            spec = designed_system.storage_caps.get(j, {})
            _fix_var(model.storage.Pcha[j], float(spec.get("Cap_Pch", 0.0)))
            _fix_var(model.storage.Pdis[j], float(spec.get("Cap_Pdis", 0.0)))
            _fix_var(model.storage.Ecap[j], float(spec.get("Cap_E", 0.0)))

    # VRE: capacity_fraction[k] so that max_capacity[k] * frac[k] == designed cap.
    for block_name, caps in (("pv", designed_system.solar_caps), ("wind", designed_system.wind_caps)):
        if not hasattr(model, block_name):
            continue
        block = getattr(model, block_name)
        for k in block.plants_set:
            max_cap = float(pyo.value(block.max_capacity[k]))
            designed = float(caps.get(k, 0.0))
            frac = 0.0 if max_cap <= 0.0 else min(max(designed / max_cap, 0.0), 1.0)
            _fix_var(block.capacity_fraction[k], frac)


def _apply_soc_floor(
    model: pyo.ConcreteModel,
    designed_system: DesignedSystem,
    overrides: dict[str, float] | None,
) -> None:
    """Apply an operational SOC floor ``frac * Ecap`` per storage tech."""
    if not hasattr(model, "storage") or not hasattr(model.storage, "SOC"):
        return
    floors: dict[str, float] = {
        s: float(spec.get("soc_min_frac", 0.0))
        for s, spec in designed_system.storage_caps.items()
    }
    if overrides:
        for s, frac in overrides.items():
            floors[s] = float(frac)

    for j in model.storage.j:
        frac = floors.get(j, 0.0)
        if frac <= 0.0:
            continue
        ecap = float(pyo.value(model.storage.Ecap[j]))
        lb = frac * ecap
        if lb <= 0.0:
            continue
        for h in model.h:
            model.storage.SOC[h, j].setlb(lb)


def _imports_var(model) -> Any:
    if hasattr(model, "imports") and hasattr(model.imports, "variable"):
        return model.imports.variable
    return None


def _exports_var(model) -> Any:
    if hasattr(model, "exports") and hasattr(model.exports, "variable"):
        return model.exports.variable
    return None


def _replace_objective_with_dispatch_objective(
    model: pyo.ConcreteModel,
    data: dict,
    *,
    dc_block_name: str | None,
    curtailment_penalty: float,
) -> None:
    """Drop the CEM planning objective and install an operational-only one.

    The CEM ``model.Obj`` mixes capacity-investment costs (CAPEX, FOM) with
    operational costs. With capacities pinned those investment terms become
    constants, but we rebuild the objective explicitly so the optimal value
    reported by the dispatch is the operational cost of running the designed
    system — plus the optional demand-charge and curtailment terms.
    """
    if hasattr(model, "Obj"):
        model.Obj.deactivate()

    thermal_var_cost = (
        add_thermal_variable_costs(model)
        if hasattr(model, "thermal") and hasattr(model.thermal, "total_fuel_cost_expr")
        else 0.0
    )
    storage_var_cost = (
        add_storage_variable_costs(model)
        if hasattr(model, "storage") and hasattr(model.storage, "PD")
        else 0.0
    )

    imports_cost = 0.0
    if get_formulation(data, component="Imports") != IMPORTS_EXPORTS_NOT_MODEL and hasattr(
        model.imports, "total_cost_expr"
    ):
        imports_cost = model.imports.total_cost_expr

    exports_cost = 0.0
    if get_formulation(data, component="Exports") != IMPORTS_EXPORTS_NOT_MODEL and hasattr(
        model.exports, "total_cost_expr"
    ):
        exports_cost = model.exports.total_cost_expr

    dc_cost = 0.0
    if dc_block_name is not None and hasattr(model, dc_block_name):
        dc_cost = getattr(model, dc_block_name).total_cost_expr

    curt_cost = 0.0
    if curtailment_penalty:
        cp = float(curtailment_penalty)
        curt = 0.0
        if hasattr(model, "pv") and hasattr(model.pv, "total_curtailment"):
            curt = curt + model.pv.total_curtailment
        if hasattr(model, "wind") and hasattr(model.wind, "total_curtailment"):
            curt = curt + model.wind.total_curtailment
        curt_cost = cp * curt

    # FOM is reused from the CEM block expressions so the resiliency baseline's
    # FOM accounting is guaranteed to match the CEM (problem (B) capacities are
    # fixed, so this is a constant w.r.t. the dispatch decisions).
    fom_cost = 0.0
    if hasattr(model, "thermal") and hasattr(model.thermal, "fixed_om_cost_expr"):
        fom_cost = fom_cost + model.thermal.fixed_om_cost_expr
    if hasattr(model, "pv") and hasattr(model.pv, "fixed_om_cost_expr"):
        fom_cost = fom_cost + model.pv.fixed_om_cost_expr
    if hasattr(model, "wind") and hasattr(model.wind, "fixed_om_cost_expr"):
        fom_cost = fom_cost + model.wind.fixed_om_cost_expr
    if hasattr(model, "storage") and hasattr(model.storage, "total_fixed_om_cost"):
        fom_cost = fom_cost + model.storage.total_fixed_om_cost

    model.dispatch_objective = pyo.Objective(
        expr=thermal_var_cost
        + storage_var_cost
        + imports_cost
        - exports_cost
        + dc_cost
        + curt_cost
        + fom_cost,
        sense=pyo.minimize,
    )

    model._sdom_cost_components = {  # noqa: SLF001 (intentional internal stash)
        "thermal_var": thermal_var_cost,
        "storage_var": storage_var_cost,
        "imports": imports_cost,
        "exports": exports_cost,
        "demand_charges": dc_cost,
        "curtailment": curt_cost,
        "fom": fom_cost,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_baseline_dispatch(
    designed_system,
    *,
    n_hours=8760,
    min_soc_per_tech=None,
    curtailment_penalty=0.0,
    add_demand_charges=True,
    model_name="SDOM_BaselineDispatch",
    profile=False,
):
    """Build the fixed-capacity annual baseline dispatch model.

    The model is built by calling the planning-model constructor
    :func:`sdom.optimization_main._initialize_model_copperplate` on
    ``designed_system.cem_data`` and then:

    1. Fixing every capacity decision variable
       (``model.thermal.plant_installed_capacity``,
       ``model.storage.{Pcha,Pdis,Ecap}``,
       ``model.{pv,wind}.capacity_fraction``) to the values stored in
       ``designed_system``.
    2. Applying an optional operational SOC floor.
    3. Layering monthly fixed and variable demand charges on top of the
       existing ``model.imports.variable`` via
       :func:`~sdom.resiliency.formulations_imports_demand_charges.add_demand_charges_to_existing_imports`.
    4. Replacing the CEM planning objective with an operational-only
       objective (variable thermal + variable storage + imports/exports +
       demand charges + optional curtailment penalty).

    Parameters
    ----------
    designed_system : DesignedSystem
        Output of :func:`sdom.resiliency.load_designed_system`. Must
        carry a populated ``cem_data`` attribute.
    n_hours : int, optional
        Number of hours to simulate. Default ``8760``.
    min_soc_per_tech : dict, optional
        ``{tech: fraction in [0, 1]}`` enforcing a SOC floor as a fraction
        of energy capacity. Missing techs default to whatever is stored on
        ``designed_system.storage_caps[s]['soc_min_frac']`` (or 0).
    curtailment_penalty : float, optional
        Per-MWh penalty applied to total VRE curtailment. Default ``0.0``.
    add_demand_charges : bool, optional
        When ``True`` (default) and ``designed_system`` carries
        ``phi_fix_t``, ``phi_var_t`` and ``month_of_hour``, monthly demand
        charges are added to the objective.
    model_name : str, optional
        Pyomo model name. Default ``"SDOM_BaselineDispatch"``.
    profile : bool, optional
        Instrument every build step with a
        :class:`~sdom.utils_performance_meassure.ModelInitProfiler` and
        print a summary. Default ``False``.

    Returns
    -------
    pyomo.environ.ConcreteModel

    Raises
    ------
    TypeError
        If ``designed_system`` is not a :class:`DesignedSystem`.
    ValueError
        If ``n_hours`` is not positive or if ``designed_system.cem_data``
        is missing.
    """
    if not isinstance(designed_system, DesignedSystem):
        raise TypeError("designed_system must be a DesignedSystem instance.")

    n_hours = int(n_hours)
    if n_hours <= 0:
        raise ValueError("n_hours must be a positive integer.")

    if designed_system.cem_data is None:
        raise ValueError(
            "designed_system.cem_data is required. Reload the design with "
            "load_designed_system(..., attach_cem_data=True) so the baseline "
            "dispatch can reuse the CEM formulations in sdom.models."
        )

    logger.info(
        "Building baseline dispatch by reusing CEM formulations: "
        "n_hours=%d, model_name=%r.",
        n_hours,
        model_name,
    )

    profiler = None
    if profile:
        profiler = ModelInitProfiler(track_memory=True, enabled=True)
        profiler.start()

    cem_data = designed_system.cem_data

    model = _run_step(
        profiler,
        "Build CEM model (copper-plate)",
        _initialize_model_copperplate,
        cem_data,
        n_hours=n_hours,
        with_resilience_constraints=False,
        model_name=model_name,
    )

    _run_step(
        profiler,
        "Fix designed capacities",
        _fix_designed_capacities,
        model,
        designed_system,
    )

    _run_step(
        profiler,
        "Apply SOC floor",
        _apply_soc_floor,
        model,
        designed_system,
        min_soc_per_tech,
    )

    dc_block_name: str | None = None
    if (
        add_demand_charges
        and designed_system.phi_fix_t is not None
        and designed_system.phi_var_t is not None
        and designed_system.month_of_hour is not None
        and _imports_var(model) is not None
    ):
        dc_block_name = "demand_charges"
        _run_step(
            profiler,
            "Attach demand-charges block",
            add_demand_charges_to_existing_imports,
            model,
            phi_fix_t=designed_system.phi_fix_t.iloc[:n_hours],
            phi_var_t=designed_system.phi_var_t.iloc[:n_hours],
            month_of_hour=designed_system.month_of_hour.iloc[:n_hours],
            block_name=dc_block_name,
        )

    _run_step(
        profiler,
        "Replace CEM objective with dispatch objective",
        _replace_objective_with_dispatch_objective,
        model,
        cem_data,
        dc_block_name=dc_block_name,
        curtailment_penalty=curtailment_penalty,
    )

    storage_techs = list(model.storage.j) if hasattr(model, "storage") else []
    thermal_plants = (
        list(model.thermal.plants_set) if hasattr(model, "thermal") else []
    )
    solar_plants = list(model.pv.plants_set) if hasattr(model, "pv") else []
    wind_plants = list(model.wind.plants_set) if hasattr(model, "wind") else []

    model._sdom_meta = {  # noqa: SLF001 (intentional internal stash)
        "n_hours": n_hours,
        "storage_techs": storage_techs,
        "thermal_plants": thermal_plants,
        "solar_plants": solar_plants,
        "wind_plants": wind_plants,
        "designed_system": designed_system,
        "dc_block_name": dc_block_name,
    }
    model._sdom_designed_system = designed_system  # noqa: SLF001

    if profiler is not None:
        profiler.stop()
        profiler.print_summary_table(
            logger,
            title="BASELINE DISPATCH BUILD PROFILING SUMMARY",
        )
        model.profiler = profiler

    logger.info(
        "Baseline dispatch built: %d hours, %d storage techs, %d thermal plants, "
        "%d solar plants, %d wind plants (demand charges: %s).",
        n_hours,
        len(storage_techs),
        len(thermal_plants),
        len(solar_plants),
        len(wind_plants),
        "on" if dc_block_name else "off",
    )
    return model


def run_baseline_dispatch(
    model,
    *,
    solver="highs",
    solver_options=None,
    tee=False,
    profile=False,
):
    """Solve the baseline dispatch and collect per-hour trajectories.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Model returned by :func:`build_baseline_dispatch`.
    solver : str, optional
        Pyomo solver name. ``"highs"`` first tries ``appsi_highs`` then
        falls back to ``highs``. Default ``"highs"``.
    solver_options : dict, optional
        Extra options passed to ``solver.solve(..., options=...)``.
    tee : bool, optional
        Stream solver output to the console. Default ``False``.
    profile : bool, optional
        Instrument solve + extraction with a profiler. Default ``False``.

    Returns
    -------
    BaselineDispatchResults
        Hourly dispatch trajectories plus solver metadata.

    Raises
    ------
    AttributeError
        If ``model`` was not produced by :func:`build_baseline_dispatch`.
    """
    if not hasattr(model, "_sdom_meta"):
        raise AttributeError(
            "model must be produced by build_baseline_dispatch (missing _sdom_meta)."
        )

    profiler = None
    if profile:
        profiler = ModelInitProfiler(track_memory=True, enabled=True)
        profiler.start()

    s = _run_step(profiler, "Resolve solver", _resolve_solver, solver)
    logger.info("Solving baseline dispatch with solver=%r (tee=%s).", solver, tee)
    res = _run_step(
        profiler,
        "Solve baseline LP/MIP",
        s.solve,
        model,
        tee=tee,
        options=solver_options or {},
    )
    status = str(res.solver.termination_condition)
    logger.info("Baseline dispatch solver termination: %s.", status)

    meta: dict[str, Any] = model._sdom_meta  # noqa: SLF001
    n_hours = meta["n_hours"]
    storage_techs = meta["storage_techs"]
    thermal_plants = meta["thermal_plants"]
    solar_plants = meta["solar_plants"]
    wind_plants = meta["wind_plants"]
    designed_system: DesignedSystem = meta["designed_system"]

    hour_idx = pd.RangeIndex(start=1, stop=n_hours + 1, name="Hour")
    hours = list(range(1, n_hours + 1))

    def _df_hxk(plants, var_getter):
        """Build hour x plant DataFrame from var_getter(h, k)."""
        if not plants:
            return pd.DataFrame(index=hour_idx)
        cols = {p: [pyo.value(var_getter(h, p)) for h in hours] for p in plants}
        return pd.DataFrame(cols, index=hour_idx)

    def _extract_trajectories():
        soc = _df_hxk(storage_techs, lambda h, j: model.storage.SOC[h, j])
        pcha = _df_hxk(storage_techs, lambda h, j: model.storage.PC[h, j])
        pdis = _df_hxk(storage_techs, lambda h, j: model.storage.PD[h, j])
        pthermal = _df_hxk(
            thermal_plants, lambda h, bu: model.thermal.generation[h, bu]
        )

        # Per-plant VRE generation = capacity_factor[h,k] * max_capacity[k] *
        # capacity_fraction[k] (capacity_fraction is now fixed by design).
        def _vre_per_plant(block, plants):
            if not plants:
                return pd.DataFrame(index=hour_idx)
            frac = {k: float(pyo.value(block.capacity_fraction[k])) for k in plants}
            mc = {k: float(pyo.value(block.max_capacity[k])) for k in plants}
            out = {}
            for k in plants:
                out[k] = [
                    float(pyo.value(block.capacity_factor[h, k])) * mc[k] * frac[k]
                    for h in hours
                ]
            return pd.DataFrame(out, index=hour_idx)

        psolar = _vre_per_plant(model.pv, solar_plants) if hasattr(model, "pv") else pd.DataFrame(index=hour_idx)
        pwind = _vre_per_plant(model.wind, wind_plants) if hasattr(model, "wind") else pd.DataFrame(index=hour_idx)

        imp_var = _imports_var(model)
        if imp_var is not None:
            pimp = pd.Series(
                [pyo.value(imp_var[h]) for h in hours], index=hour_idx, name="Pimp"
            )
        else:
            pimp = pd.Series([0.0] * n_hours, index=hour_idx, name="Pimp")

        exp_var = _exports_var(model)
        if exp_var is not None:
            pexp = pd.Series(
                [pyo.value(exp_var[h]) for h in hours], index=hour_idx, name="Pexp"
            )
        else:
            pexp = pd.Series([0.0] * n_hours, index=hour_idx, name="Pexp")

        return soc, pcha, pdis, pthermal, psolar, pwind, pimp, pexp

    soc_df, pcha_df, pdis_df, pthermal_df, psolar_df, pwind_df, pimp, pexp = _run_step(
        profiler, "Extract trajectories", _extract_trajectories
    )

    cost_breakdown = _extract_cost_breakdown(model)

    if profiler is not None:
        profiler.stop()
        profiler.print_summary_table(
            logger,
            title="BASELINE DISPATCH SOLVE PROFILING SUMMARY",
        )

    def _slice(series: pd.Series | None, name: str) -> pd.Series:
        if series is None:
            return pd.Series([0.0] * n_hours, index=hour_idx, name=name)
        s = series.iloc[:n_hours].copy()
        s.index = hour_idx
        s.name = name
        return s

    return BaselineDispatchResults(
        soc_trajectory=soc_df,
        pcha_trajectory=pcha_df,
        pdis_trajectory=pdis_df,
        pthermal_trajectory=pthermal_df,
        psolar_trajectory=psolar_df,
        pwind_trajectory=pwind_df,
        pimp=pimp,
        pexp=pexp,
        nuclear=_slice(designed_system.nuclear, "Nuclear"),
        hydro=_slice(designed_system.hydro, "Hydro"),
        other_renewables=_slice(designed_system.other_renewables, "OtherRen"),
        load=_slice(designed_system.load, "Load"),
        month_of_hour=_slice(designed_system.month_of_hour, "month"),
        objective_value=float(pyo.value(model.dispatch_objective)),
        solver_status=status,
        metadata={
            "solver": solver,
            "designed_system": getattr(model, "_sdom_designed_system", None),
            "profiler": profiler,
        },
        cost_breakdown=cost_breakdown,
    )
