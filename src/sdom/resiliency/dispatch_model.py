"""Fixed-capacity baseline annual economic-dispatch builder for the resiliency module.

Composes storage, thermal (per Plant_id), VRE (per plant), nuclear, hydro,
other-renewables, load, imports (with monthly demand charges) and exports
(without net-load constraints) into a single linear program. Capacities and
must-run injections are pinned from a :class:`DesignedSystem` snapshot.

Math reference: see ``dev_guidelines/resiliency evaluation/math_model.md``,
sections 4.1, 5.1, 5.2, 5.3, 5.4.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pyomo.environ as pyo

from sdom.resiliency.formulations_imports_demand_charges import (
    add_imports_with_demand_charges,
)
from sdom.resiliency.system_state import BaselineDispatchResults, DesignedSystem


__all__ = ["build_baseline_dispatch", "run_baseline_dispatch"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _to_hour_dict(series: pd.Series, n_hours: int) -> dict[int, float]:
    """Return a ``{hour: value}`` dict for hours 1..n_hours."""
    s = series.iloc[:n_hours]
    return {t: float(s.iloc[t - 1]) for t in range(1, n_hours + 1)}


def _to_hour_plant_dict(df: pd.DataFrame, n_hours: int, plant_ids):
    """Return ``{(plant_id, t): value}`` for the given column subset."""
    out: dict[tuple[str, int], float] = {}
    sub = df.iloc[:n_hours]
    for k in plant_ids:
        col = sub[k]
        for t in range(1, n_hours + 1):
            out[(k, t)] = float(col.iloc[t - 1])
    return out


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


# ---------------------------------------------------------------------------
# Builders for sub-blocks
# ---------------------------------------------------------------------------
def _add_exports_block(model: pyo.ConcreteModel, designed_system: DesignedSystem, n_hours: int):
    block = pyo.Block()
    model.add_component("exports", block)
    cap = _to_hour_dict(designed_system.export_cap, n_hours)
    price = _to_hour_dict(designed_system.export_price, n_hours)

    block.cap_param = pyo.Param(model.h, initialize=cap, mutable=False)
    block.price_param = pyo.Param(model.h, initialize=price, mutable=False)
    block.Pexp = pyo.Var(model.h, domain=pyo.NonNegativeReals, initialize=0.0)

    block.capacity_constraint = pyo.Constraint(
        model.h, rule=lambda b, t: b.Pexp[t] <= b.cap_param[t]
    )
    block.revenue_expr = pyo.Expression(
        expr=sum(block.price_param[t] * block.Pexp[t] for t in model.h)
    )
    return block


def _add_storage_block(
    model: pyo.ConcreteModel,
    designed_system: DesignedSystem,
    n_hours: int,
    soc_min_frac_map: dict[str, float],
):
    block = pyo.Block()
    model.add_component("storage", block)

    techs = list(designed_system.storage_caps.keys())
    block.S = pyo.Set(initialize=techs, ordered=True)

    cap_pch = {s: float(designed_system.storage_caps[s]["Cap_Pch"]) for s in techs}
    cap_pdis = {s: float(designed_system.storage_caps[s]["Cap_Pdis"]) for s in techs}
    cap_e = {s: float(designed_system.storage_caps[s]["Cap_E"]) for s in techs}
    eta_ch = {s: float(designed_system.storage_caps[s].get("eta_ch", 1.0)) for s in techs}
    eta_dis = {s: float(designed_system.storage_caps[s].get("eta_dis", 1.0)) for s in techs}
    vom = {s: float(designed_system.storage_caps[s].get("vom", 0.0)) for s in techs}

    block.Cap_Pch = pyo.Param(block.S, initialize=cap_pch)
    block.Cap_Pdis = pyo.Param(block.S, initialize=cap_pdis)
    block.Cap_E = pyo.Param(block.S, initialize=cap_e)
    block.eta_ch = pyo.Param(block.S, initialize=eta_ch)
    block.eta_dis = pyo.Param(block.S, initialize=eta_dis)
    block.vom = pyo.Param(block.S, initialize=vom)

    def _pcha_bounds(b, s, t):
        return (0.0, cap_pch[s])

    def _pdis_bounds(b, s, t):
        return (0.0, cap_pdis[s])

    def _soc_bounds(b, s, t):
        lb = soc_min_frac_map.get(s, 0.0) * cap_e[s]
        return (lb, cap_e[s])

    block.Pcha = pyo.Var(block.S, model.h, domain=pyo.NonNegativeReals, bounds=_pcha_bounds, initialize=0.0)
    block.Pdis = pyo.Var(block.S, model.h, domain=pyo.NonNegativeReals, bounds=_pdis_bounds, initialize=0.0)
    block.SOC = pyo.Var(block.S, model.h, domain=pyo.NonNegativeReals, bounds=_soc_bounds, initialize=0.0)

    # SOC dynamics
    def _soc_dynamics(b, s, t):
        if t == 1:
            return pyo.Constraint.Skip
        return b.SOC[s, t] == b.SOC[s, t - 1] + b.eta_ch[s] * b.Pcha[s, t] - b.Pdis[s, t] / b.eta_dis[s]

    block.soc_dynamics = pyo.Constraint(block.S, model.h, rule=_soc_dynamics)

    # Initial SOC: floor or 50% of Cap_E if no floor specified.
    def _soc_initial(b, s):
        floor = soc_min_frac_map.get(s, 0.0) * cap_e[s]
        init = floor if floor > 0.0 else 0.5 * cap_e[s]
        return b.SOC[s, 1] == init

    block.soc_initial = pyo.Constraint(block.S, rule=_soc_initial)

    block.cost_expr = pyo.Expression(
        expr=sum(
            vom[s] * (block.Pcha[s, t] + block.Pdis[s, t])
            for s in techs
            for t in model.h
        )
    )
    return block


def _add_thermal_block(model: pyo.ConcreteModel, designed_system: DesignedSystem, n_hours: int):
    block = pyo.Block()
    model.add_component("thermal", block)

    # The current DesignedSystem stores thermal as ``{tech: {capacity_MW, var_cost, ...}}``.
    # Phase 3 spec calls for per-Plant_id variables, but the data loader's only field is
    # the aggregate-tech entry (tech name acts as plant id here). If the snapshot reports
    # zero-capacity techs, the loader has already filtered them out, so the block becomes
    # empty and contributes nothing to the objective / power balance.
    plants = list(designed_system.thermal_caps.keys())
    block.B = pyo.Set(initialize=plants, ordered=True)

    cap = {b: float(designed_system.thermal_caps[b].get("capacity_MW", 0.0)) for b in plants}
    var_cost = {b: float(designed_system.thermal_caps[b].get("var_cost", 0.0)) for b in plants}
    block.cap = pyo.Param(block.B, initialize=cap)
    block.var_cost = pyo.Param(block.B, initialize=var_cost)

    def _bounds(b, plant, t):
        return (0.0, cap[plant])

    block.Pthermal = pyo.Var(block.B, model.h, domain=pyo.NonNegativeReals, bounds=_bounds, initialize=0.0)

    block.cost_expr = pyo.Expression(
        expr=sum(var_cost[p] * block.Pthermal[p, t] for p in plants for t in model.h)
        if plants
        else 0.0
    )
    return block


def _add_vre_block(
    model: pyo.ConcreteModel,
    *,
    block_name: str,
    var_name: str,
    plants: list[str],
    caps: dict[str, float],
    cf: pd.DataFrame,
    n_hours: int,
):
    block = pyo.Block()
    model.add_component(block_name, block)
    block.K = pyo.Set(initialize=plants, ordered=True)

    block.cap = pyo.Param(block.K, initialize={k: float(caps[k]) for k in plants})

    cf_dict: dict[tuple[str, int], float] = {}
    for k in plants:
        col = cf[k] if k in cf.columns else None
        if col is None:
            for t in range(1, n_hours + 1):
                cf_dict[(k, t)] = 0.0
        else:
            for t in range(1, n_hours + 1):
                cf_dict[(k, t)] = float(col.iloc[t - 1])
    block.cf = pyo.Param(block.K, model.h, initialize=cf_dict, mutable=False)

    def _bounds(b, k, t):
        return (0.0, float(caps[k]) * cf_dict[(k, t)])

    var = pyo.Var(block.K, model.h, domain=pyo.NonNegativeReals, bounds=_bounds, initialize=0.0)
    block.add_component(var_name, var)

    # Curtailment expression (potential - dispatched).
    block.potential_minus_dispatch = pyo.Expression(
        expr=sum(
            float(caps[k]) * cf_dict[(k, t)] - var[k, t]
            for k in plants
            for t in model.h
        )
        if plants
        else 0.0
    )
    return block


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_baseline_dispatch(
    designed_system,
    *,
    n_hours=8760,
    min_soc_per_tech=None,
    curtailment_penalty=0.0,
    formulation_overrides=None,
    model_name="SDOM_BaselineDispatch",
):
    """Build the fixed-capacity annual economic-dispatch Pyomo LP.

    Composes blocks for storage, thermal (per-plant), solar (per-plant),
    wind (per-plant), nuclear, hydro, other-renewables, load, imports (with
    monthly demand charges) and exports (pure-LP capacity bound) into a
    single LP minimizing total operational cost.

    Parameters
    ----------
    designed_system : DesignedSystem
        Output of :func:`sdom.resiliency.load_designed_system` (or a
        synthetic equivalent).
    n_hours : int, optional
        Number of hours to simulate. Default ``8760``.
    min_soc_per_tech : dict, optional
        ``{tech: fraction in [0, 1]}`` enforcing operational SOC floor as a
        fraction of ``Cap_E``. Missing techs default to ``0.0``. The user
        dict overrides anything stored on ``designed_system.storage_caps``.
    curtailment_penalty : float, optional
        Penalty applied to curtailed VRE energy (USD/MWh). Default ``0.0``.
    formulation_overrides : dict, optional
        Component-wise formulation overrides (currently advisory; defaults
        already match ``DesignedSystem.formulation_map``).
    model_name : str, optional
        Pyomo model name. Default ``"SDOM_BaselineDispatch"``.

    Returns
    -------
    pyomo.environ.ConcreteModel

    Notes
    -----
    The resiliency module is self-contained and does not call the legacy
    objective from ``formulations_system.py``.
    """
    if not isinstance(designed_system, DesignedSystem):
        raise TypeError("designed_system must be a DesignedSystem instance.")

    n_hours = int(n_hours)
    if n_hours <= 0:
        raise ValueError("n_hours must be a positive integer.")

    # Resolve SOC floors
    soc_min_frac_map: dict[str, float] = {
        s: float(spec.get("soc_min_frac", 0.0))
        for s, spec in designed_system.storage_caps.items()
    }
    if min_soc_per_tech:
        for s, frac in min_soc_per_tech.items():
            soc_min_frac_map[s] = float(frac)

    model = pyo.ConcreteModel(name=model_name)
    model.h = pyo.RangeSet(1, n_hours)

    # Storage / thermal / VRE blocks
    storage = _add_storage_block(model, designed_system, n_hours, soc_min_frac_map)
    thermal = _add_thermal_block(model, designed_system, n_hours)

    solar_plants = list(designed_system.solar_caps.keys())
    wind_plants = list(designed_system.wind_caps.keys())
    solar_block = _add_vre_block(
        model,
        block_name="solar",
        var_name="Psolar",
        plants=solar_plants,
        caps=designed_system.solar_caps,
        cf=designed_system.cf_solar if designed_system.cf_solar is not None else pd.DataFrame(),
        n_hours=n_hours,
    )
    wind_block = _add_vre_block(
        model,
        block_name="wind",
        var_name="Pwind",
        plants=wind_plants,
        caps=designed_system.wind_caps,
        cf=designed_system.cf_wind if designed_system.cf_wind is not None else pd.DataFrame(),
        n_hours=n_hours,
    )

    # Imports (with demand charges) - Phase 2 builder
    add_imports_with_demand_charges(
        model,
        import_cap=designed_system.import_cap.iloc[:n_hours],
        import_price=designed_system.import_price.iloc[:n_hours],
        phi_fix_t=designed_system.phi_fix_t.iloc[:n_hours],
        phi_var_t=designed_system.phi_var_t.iloc[:n_hours],
        month_of_hour=designed_system.month_of_hour.iloc[:n_hours],
        block_name="imports",
    )

    # Exports (pure LP, no net-load coupling)
    _add_exports_block(model, designed_system, n_hours)

    # Time-series (must-run) parameters that enter the power balance directly.
    nuclear = _to_hour_dict(designed_system.nuclear, n_hours)
    hydro = _to_hour_dict(designed_system.hydro, n_hours)
    other_ren = _to_hour_dict(designed_system.other_renewables, n_hours)
    load = _to_hour_dict(designed_system.load, n_hours)

    model.nuclear_param = pyo.Param(model.h, initialize=nuclear, mutable=False)
    model.hydro_param = pyo.Param(model.h, initialize=hydro, mutable=False)
    model.other_ren_param = pyo.Param(model.h, initialize=other_ren, mutable=False)
    model.load_param = pyo.Param(model.h, initialize=load, mutable=False)

    # Power balance
    storage_techs = list(designed_system.storage_caps.keys())
    thermal_plants = list(designed_system.thermal_caps.keys())

    def _balance_rule(m, t):
        gen_thermal = sum(thermal.Pthermal[b, t] for b in thermal_plants) if thermal_plants else 0.0
        gen_solar = sum(solar_block.Psolar[k, t] for k in solar_plants) if solar_plants else 0.0
        gen_wind = sum(wind_block.Pwind[w, t] for w in wind_plants) if wind_plants else 0.0
        dis = sum(storage.Pdis[s, t] for s in storage_techs) if storage_techs else 0.0
        cha = sum(storage.Pcha[s, t] for s in storage_techs) if storage_techs else 0.0
        return (
            gen_thermal
            + gen_solar
            + gen_wind
            + dis
            + m.nuclear_param[t]
            + m.hydro_param[t]
            + m.other_ren_param[t]
            + m.imports.Pimp[t]
            == m.load_param[t] + cha + m.exports.Pexp[t]
        )

    model.power_balance = pyo.Constraint(model.h, rule=_balance_rule)

    # Objective
    curt_penalty = float(curtailment_penalty)
    obj_expr = (
        thermal.cost_expr
        + storage.cost_expr
        + model.imports.total_cost_expr
        - model.exports.revenue_expr
        + curt_penalty * (solar_block.potential_minus_dispatch + wind_block.potential_minus_dispatch)
    )
    model.objective = pyo.Objective(expr=obj_expr, sense=pyo.minimize)

    # Annotate metadata used by run_baseline_dispatch.
    model._sdom_meta = {  # noqa: SLF001 (intentional internal stash)
        "n_hours": n_hours,
        "storage_techs": storage_techs,
        "thermal_plants": thermal_plants,
        "solar_plants": solar_plants,
        "wind_plants": wind_plants,
        "designed_system": designed_system,
    }
    return model


def run_baseline_dispatch(
    model,
    *,
    solver="highs",
    solver_options=None,
    tee=False,
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

    s = _resolve_solver(solver)
    res = s.solve(model, tee=tee, options=solver_options or {})
    status = str(res.solver.termination_condition)

    meta: dict[str, Any] = model._sdom_meta  # noqa: SLF001
    n_hours = meta["n_hours"]
    storage_techs = meta["storage_techs"]
    thermal_plants = meta["thermal_plants"]
    solar_plants = meta["solar_plants"]
    wind_plants = meta["wind_plants"]
    designed_system: DesignedSystem = meta["designed_system"]

    hour_idx = pd.RangeIndex(start=1, stop=n_hours + 1, name="Hour")

    def _df(plants, var):
        if not plants:
            return pd.DataFrame(index=hour_idx)
        data = {p: [pyo.value(var[p, t]) for t in range(1, n_hours + 1)] for p in plants}
        return pd.DataFrame(data, index=hour_idx)

    soc_df = _df(storage_techs, model.storage.SOC)
    pcha_df = _df(storage_techs, model.storage.Pcha)
    pdis_df = _df(storage_techs, model.storage.Pdis)
    pthermal_df = _df(thermal_plants, model.thermal.Pthermal) if thermal_plants else pd.DataFrame(index=hour_idx)
    psolar_df = _df(solar_plants, model.solar.Psolar)
    pwind_df = _df(wind_plants, model.wind.Pwind)

    pimp = pd.Series(
        [pyo.value(model.imports.Pimp[t]) for t in range(1, n_hours + 1)],
        index=hour_idx,
        name="Pimp",
    )
    pexp = pd.Series(
        [pyo.value(model.exports.Pexp[t]) for t in range(1, n_hours + 1)],
        index=hour_idx,
        name="Pexp",
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
        objective_value=float(pyo.value(model.objective)),
        solver_status=status,
        metadata={"solver": solver},
    )
