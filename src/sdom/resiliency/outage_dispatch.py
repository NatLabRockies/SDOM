"""Per-hour outage economic-dispatch Pyomo LP builder.

This module implements ``build_outage_dispatch``, the Phase 4 builder for the
short-horizon dispatch problem (O) anchored at hour ``h``. The model layout
mirrors :func:`sdom.resiliency.build_baseline_dispatch` but:

* the hour set is the clipped outage horizon ``[h, h + Delta_out + Delta_rec - 1]``;
* every capacity-bounded asset has a time-varying upper bound
  ``delta_{a,t} * Cap_a`` that drops to ``rho_a`` inside the outage window;
* must-run time-series sources (nuclear, hydro, other_renewables) are scaled
  by ``delta^m_t`` directly in the power balance;
* a non-negative slack ``u[t]`` (MWh) is added to the power balance and
  penalised in the objective;
* demand charges (``D_fix``, ``D_var``) are excluded; the outage horizon is
  sub-monthly so monthly peak charges do not apply (see math_model.md
  section 4.2).

Math reference: ``dev_guidelines/resiliency evaluation/math_model.md``,
sections 1, 4.2, 5.1, 5.2, 5.3, 5.5, 6.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pyomo.environ as pyo

from sdom.resiliency.system_state import BaselineDispatchResults, DesignedSystem


logger = logging.getLogger(__name__)


__all__ = ["build_outage_dispatch"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _series_value(series: pd.Series | None, hour: int) -> float:
    if series is None:
        return 0.0
    try:
        return float(series.loc[hour])
    except KeyError:
        return float(series.iloc[hour - 1])


# ---------------------------------------------------------------------------
# Sub-block builders (outage variants)
# ---------------------------------------------------------------------------
def _add_storage_block_outage(
    model: pyo.ConcreteModel,
    designed_system: DesignedSystem,
    soc_min_frac_map: dict[str, float],
    start_hour: int,
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

    block.Pcha = pyo.Var(
        block.S, model.h, domain=pyo.NonNegativeReals, bounds=_pcha_bounds, initialize=0.0
    )
    block.Pdis = pyo.Var(
        block.S, model.h, domain=pyo.NonNegativeReals, bounds=_pdis_bounds, initialize=0.0
    )
    block.SOC = pyo.Var(
        block.S, model.h, domain=pyo.NonNegativeReals, bounds=_soc_bounds, initialize=0.0
    )

    def _soc_dynamics(b, s, t):
        if t == start_hour:
            return pyo.Constraint.Skip
        return (
            b.SOC[s, t]
            == b.SOC[s, t - 1] + b.eta_ch[s] * b.Pcha[s, t] - b.Pdis[s, t] / b.eta_dis[s]
        )

    block.soc_dynamics = pyo.Constraint(block.S, model.h, rule=_soc_dynamics)

    block.cost_expr = pyo.Expression(
        expr=sum(
            vom[s] * (block.Pcha[s, t] + block.Pdis[s, t])
            for s in techs
            for t in model.h
        )
        if techs
        else 0.0
    )
    return block


def _add_thermal_block_outage(
    model: pyo.ConcreteModel,
    designed_system: DesignedSystem,
    delta_thermal: dict[tuple[str, int], float],
):
    block = pyo.Block()
    model.add_component("thermal", block)

    plants = list(designed_system.thermal_caps.keys())
    block.B = pyo.Set(initialize=plants, ordered=True)

    cap = {b: float(designed_system.thermal_caps[b].get("capacity_MW", 0.0)) for b in plants}
    var_cost = {b: float(designed_system.thermal_caps[b].get("var_cost", 0.0)) for b in plants}
    block.cap = pyo.Param(block.B, initialize=cap)
    block.var_cost = pyo.Param(block.B, initialize=var_cost)

    def _bounds(b, plant, t):
        delta = delta_thermal.get((plant, t), 1.0)
        return (0.0, delta * cap[plant])

    block.Pthermal = pyo.Var(
        block.B, model.h, domain=pyo.NonNegativeReals, bounds=_bounds, initialize=0.0
    )
    block.cost_expr = pyo.Expression(
        expr=sum(var_cost[p] * block.Pthermal[p, t] for p in plants for t in model.h)
        if plants
        else 0.0
    )
    return block


def _add_vre_block_outage(
    model: pyo.ConcreteModel,
    *,
    block_name: str,
    var_name: str,
    plants: list[str],
    caps: dict[str, float],
    cf: pd.DataFrame,
    delta_map: dict[tuple[str, int], float],
):
    block = pyo.Block()
    model.add_component(block_name, block)
    block.K = pyo.Set(initialize=plants, ordered=True)
    block.cap = pyo.Param(block.K, initialize={k: float(caps[k]) for k in plants})

    cf_dict: dict[tuple[str, int], float] = {}
    cf_columns = list(getattr(cf, "columns", [])) if cf is not None else []
    for k in plants:
        col = cf[k] if k in cf_columns else None
        for t in model.h:
            if col is None:
                cf_dict[(k, t)] = 0.0
            else:
                try:
                    cf_dict[(k, t)] = float(col.loc[t])
                except KeyError:
                    cf_dict[(k, t)] = float(col.iloc[t - 1])
    block.cf = pyo.Param(block.K, model.h, initialize=cf_dict, mutable=False)

    def _bounds(b, k, t):
        delta = delta_map.get((k, t), 1.0)
        return (0.0, delta * float(caps[k]) * cf_dict[(k, t)])

    var = pyo.Var(
        block.K, model.h, domain=pyo.NonNegativeReals, bounds=_bounds, initialize=0.0
    )
    block.add_component(var_name, var)

    block.potential_minus_dispatch = pyo.Expression(
        expr=sum(
            delta_map.get((k, t), 1.0) * float(caps[k]) * cf_dict[(k, t)] - var[k, t]
            for k in plants
            for t in model.h
        )
        if plants
        else 0.0
    )
    return block


def _add_imports_block_outage(
    model: pyo.ConcreteModel,
    designed_system: DesignedSystem,
    delta_imports: dict[int, float],
):
    block = pyo.Block()
    model.add_component("imports", block)

    cap = {t: float(_series_value(designed_system.import_cap, t)) for t in model.h}
    price = {t: float(_series_value(designed_system.import_price, t)) for t in model.h}

    block.cap_param = pyo.Param(model.h, initialize=cap, mutable=False)
    block.price_param = pyo.Param(model.h, initialize=price, mutable=False)

    def _bounds(b, t):
        delta = delta_imports.get(t, 1.0)
        return (0.0, delta * cap[t])

    block.Pimp = pyo.Var(model.h, domain=pyo.NonNegativeReals, bounds=_bounds, initialize=0.0)
    block.total_cost_expr = pyo.Expression(
        expr=sum(block.price_param[t] * block.Pimp[t] for t in model.h)
    )
    return block


def _add_exports_block_outage(model: pyo.ConcreteModel, designed_system: DesignedSystem):
    block = pyo.Block()
    model.add_component("exports", block)

    cap = {t: float(_series_value(designed_system.export_cap, t)) for t in model.h}
    price = {t: float(_series_value(designed_system.export_price, t)) for t in model.h}

    block.cap_param = pyo.Param(model.h, initialize=cap, mutable=False)
    block.price_param = pyo.Param(model.h, initialize=price, mutable=False)

    def _bounds(b, t):
        return (0.0, cap[t])

    block.Pexp = pyo.Var(model.h, domain=pyo.NonNegativeReals, bounds=_bounds, initialize=0.0)
    block.revenue_expr = pyo.Expression(
        expr=sum(block.price_param[t] * block.Pexp[t] for t in model.h)
    )
    return block


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_outage_dispatch(
    baseline_results,
    *,
    start_hour,
    outage_spec,
    designed_system=None,
    slack_penalty=10_000.0,
    curtailment_penalty=0.0,
    min_soc_per_tech=None,
    n_hours=8760,
    model_name="SDOM_OutageDispatch",
):
    """Build the per-hour outage economic-dispatch Pyomo LP anchored at ``start_hour``.

    Parameters
    ----------
    baseline_results : BaselineDispatchResults
        Output of :func:`sdom.resiliency.run_baseline_dispatch`. Used to seed
        the initial SOC and (optionally) the recovery SOC target. May carry
        the originating :class:`DesignedSystem` under
        ``baseline_results.metadata["designed_system"]``.
    start_hour : int
        Anchor hour ``h``. The outage horizon is
        ``[h, h + duration + max_recovery - 1]``, clipped to ``[1, n_hours]``.
    outage_spec : OutageSpec
        Outage / de-rating specification.
    designed_system : DesignedSystem, optional
        Source of truth for capacities and time series. If ``None``, taken
        from ``baseline_results.metadata["designed_system"]``.
    slack_penalty : float, optional
        Penalty :math:`\\pi^{slack}` (USD/MWh) on unserved-energy slack.
        Default ``10_000.0``.
    curtailment_penalty : float, optional
        Penalty on curtailed VRE energy (USD/MWh). Default ``0.0``.
    min_soc_per_tech : dict, optional
        Operational SOC floor per storage tech (fraction of ``Cap_E``).
        Same semantics as :func:`build_baseline_dispatch`.
    n_hours : int, optional
        Length of the baseline horizon used for end-of-year clipping.
        Default ``8760``.
    model_name : str, optional
        Pyomo model name. Default ``"SDOM_OutageDispatch"``.

    Returns
    -------
    pyomo.environ.ConcreteModel
        A Pyomo LP exposing ``model.h`` (hour set), ``model.u`` (slack,
        ``NonNegativeReals``), the standard dispatch sub-blocks
        (``storage``, ``thermal``, ``solar``, ``wind``, ``imports``,
        ``exports``) without demand-charge variables, and an objective that
        minimises operational cost plus slack and curtailment penalties.

    Raises
    ------
    ValueError
        If ``designed_system`` is not provided and cannot be recovered from
        ``baseline_results.metadata``, or if validation of ``outage_spec``
        against ``designed_system`` fails.
    TypeError
        If ``baseline_results`` or ``designed_system`` is the wrong type.

    Notes
    -----
    Initial SOC is seeded with :py:meth:`pyomo.environ.Var.fix` rather than
    via an equality constraint, which keeps the LP tighter and avoids one
    extra row per storage technology.
    """
    if designed_system is None:
        designed_system = (baseline_results.metadata or {}).get("designed_system")
    if designed_system is None:
        raise ValueError(
            "designed_system must be provided (or stored in "
            "baseline_results.metadata['designed_system'])."
        )
    if not isinstance(designed_system, DesignedSystem):
        raise TypeError("designed_system must be a DesignedSystem instance.")
    if not isinstance(baseline_results, BaselineDispatchResults):
        raise TypeError("baseline_results must be a BaselineDispatchResults instance.")

    outage_spec.validate(designed_system)

    n_hours = int(n_hours)
    start_hour = int(start_hour)
    if not (1 <= start_hour <= n_hours):
        raise ValueError(f"start_hour must be in [1, {n_hours}]; got {start_hour}.")

    duration = int(outage_spec.duration_hours)
    recovery_per_tech = outage_spec.resolve_recovery_hours(designed_system)
    max_recovery = max(recovery_per_tech.values()) if recovery_per_tech else 0
    end_hour = min(start_hour + duration + max_recovery - 1, n_hours)
    logger.debug(
        "Building outage LP: start_hour=%d, duration=%d, max_recovery=%d, "
        "horizon=[%d, %d], slack_penalty=%g.",
        start_hour,
        duration,
        max_recovery,
        start_hour,
        end_hour,
        slack_penalty,
    )

    recovery_end_hour = {
        s: min(start_hour + duration + recovery_per_tech[s] - 1, n_hours)
        for s in recovery_per_tech
    }

    # ------------------------------------------------------------------
    # Build delta multipliers per (component, asset_id, t)
    # ------------------------------------------------------------------
    delta_thermal: dict[tuple[str, int], float] = {}
    delta_wind: dict[tuple[str, int], float] = {}
    delta_solar: dict[tuple[str, int], float] = {}
    delta_imports: dict[int, float] = {}
    delta_nuc: dict[int, float] = {}
    delta_hydro: dict[int, float] = {}
    delta_other: dict[int, float] = {}

    horizon = list(range(start_hour, end_hour + 1))

    def _populate(component: str, asset_universe, target: dict):
        for plant in asset_universe:
            plant_id = str(plant)
            rho = outage_spec.resolve_derating(component, plant_id)
            if rho == 1.0:
                continue
            dur = outage_spec.resolve_duration(component, plant_id)
            for t in range(start_hour, min(start_hour + dur, end_hour + 1)):
                target[(plant, t)] = rho

    _populate("balancing_units", designed_system.thermal_caps.keys(), delta_thermal)
    _populate("wind", designed_system.wind_caps.keys(), delta_wind)
    _populate("solar", designed_system.solar_caps.keys(), delta_solar)

    rho_imp = outage_spec.resolve_derating("imports", "grid")
    if rho_imp != 1.0:
        dur = outage_spec.resolve_duration("imports", "grid")
        for t in range(start_hour, min(start_hour + dur, end_hour + 1)):
            delta_imports[t] = rho_imp

    must_run_delta_maps = {
        "nuclear": delta_nuc,
        "hydro": delta_hydro,
        "other_renewables": delta_other,
    }
    for comp, dmap in must_run_delta_maps.items():
        if comp not in outage_spec.outaged_assets:
            continue
        rho = outage_spec.resolve_derating(comp, "all")
        if rho == 1.0:
            continue
        dur = outage_spec.resolve_duration(comp, "all")
        for t in range(start_hour, min(start_hour + dur, end_hour + 1)):
            dmap[t] = rho

    # ------------------------------------------------------------------
    # SOC floors
    # ------------------------------------------------------------------
    soc_min_frac_map: dict[str, float] = {
        s: float(spec.get("soc_min_frac", 0.0))
        for s, spec in designed_system.storage_caps.items()
    }
    if min_soc_per_tech:
        for s, frac in min_soc_per_tech.items():
            soc_min_frac_map[s] = float(frac)

    # ------------------------------------------------------------------
    # Build model
    # ------------------------------------------------------------------
    model = pyo.ConcreteModel(name=model_name)
    model.h = pyo.RangeSet(start_hour, end_hour)

    storage_block = _add_storage_block_outage(
        model, designed_system, soc_min_frac_map, start_hour
    )
    thermal_block = _add_thermal_block_outage(model, designed_system, delta_thermal)

    solar_plants = list(designed_system.solar_caps.keys())
    wind_plants = list(designed_system.wind_caps.keys())
    solar_block = _add_vre_block_outage(
        model,
        block_name="solar",
        var_name="Psolar",
        plants=solar_plants,
        caps=designed_system.solar_caps,
        cf=designed_system.cf_solar if designed_system.cf_solar is not None else pd.DataFrame(),
        delta_map=delta_solar,
    )
    wind_block = _add_vre_block_outage(
        model,
        block_name="wind",
        var_name="Pwind",
        plants=wind_plants,
        caps=designed_system.wind_caps,
        cf=designed_system.cf_wind if designed_system.cf_wind is not None else pd.DataFrame(),
        delta_map=delta_wind,
    )
    imports_block = _add_imports_block_outage(model, designed_system, delta_imports)
    exports_block = _add_exports_block_outage(model, designed_system)

    # Effective must-run parameters
    nuclear_eff = {
        t: _series_value(designed_system.nuclear, t) * delta_nuc.get(t, 1.0)
        for t in horizon
    }
    hydro_eff = {
        t: _series_value(designed_system.hydro, t) * delta_hydro.get(t, 1.0)
        for t in horizon
    }
    other_ren_eff = {
        t: _series_value(designed_system.other_renewables, t) * delta_other.get(t, 1.0)
        for t in horizon
    }
    load_param = {t: _series_value(designed_system.load, t) for t in horizon}

    model.nuclear_eff_param = pyo.Param(model.h, initialize=nuclear_eff, mutable=False)
    model.hydro_eff_param = pyo.Param(model.h, initialize=hydro_eff, mutable=False)
    model.other_ren_eff_param = pyo.Param(model.h, initialize=other_ren_eff, mutable=False)
    model.load_param = pyo.Param(model.h, initialize=load_param, mutable=False)

    # Slack u[t] (MWh)
    model.u = pyo.Var(model.h, domain=pyo.NonNegativeReals, initialize=0.0)

    storage_techs = list(designed_system.storage_caps.keys())
    thermal_plants = list(designed_system.thermal_caps.keys())

    def _balance_rule(m, t):
        gen_thermal = (
            sum(thermal_block.Pthermal[b, t] for b in thermal_plants)
            if thermal_plants
            else 0.0
        )
        gen_solar = (
            sum(solar_block.Psolar[k, t] for k in solar_plants) if solar_plants else 0.0
        )
        gen_wind = (
            sum(wind_block.Pwind[w, t] for w in wind_plants) if wind_plants else 0.0
        )
        dis = sum(storage_block.Pdis[s, t] for s in storage_techs) if storage_techs else 0.0
        cha = sum(storage_block.Pcha[s, t] for s in storage_techs) if storage_techs else 0.0
        return (
            gen_thermal
            + gen_solar
            + gen_wind
            + dis
            + m.nuclear_eff_param[t]
            + m.hydro_eff_param[t]
            + m.other_ren_eff_param[t]
            + imports_block.Pimp[t]
            + m.u[t]
            == m.load_param[t] + cha + exports_block.Pexp[t]
        )

    model.power_balance = pyo.Constraint(model.h, rule=_balance_rule)

    # Initial SOC (math_model 5.5)
    soc_traj = baseline_results.soc_trajectory
    if soc_traj is None:
        raise ValueError("baseline_results.soc_trajectory is required to seed initial SOC.")
    for s in storage_techs:
        try:
            init_value = float(soc_traj.loc[start_hour, s])
        except KeyError as exc:
            raise ValueError(
                f"baseline SOC trajectory missing entry for tech '{s}' at hour {start_hour}."
            ) from exc
        cap_e = float(designed_system.storage_caps[s]["Cap_E"])
        lb = soc_min_frac_map.get(s, 0.0) * cap_e
        init_value = min(max(init_value, lb), cap_e)
        storage_block.SOC[s, start_hour].fix(init_value)

    # Recovery target
    recovery_target_frac = outage_spec.resolve_min_soc_recovery(
        baseline_results,
        designed_system,
        recovery_end_hour=recovery_end_hour,
    )
    recovery_target_MWh: dict[str, float] = {}
    for s in storage_techs:
        cap_e = float(designed_system.storage_caps[s]["Cap_E"])
        recovery_target_MWh[s] = float(recovery_target_frac.get(s, 0.0)) * cap_e

    def _recovery_target_rule(m, s):
        t_end = recovery_end_hour[s]
        if t_end < start_hour or t_end > end_hour:
            return pyo.Constraint.Skip
        return storage_block.SOC[s, t_end] >= recovery_target_MWh[s]

    model.recovery_target = pyo.Constraint(storage_block.S, rule=_recovery_target_rule)

    # Objective
    slack_pen = float(slack_penalty)
    curt_pen = float(curtailment_penalty)
    obj_expr = (
        thermal_block.cost_expr
        + storage_block.cost_expr
        + imports_block.total_cost_expr
        - exports_block.revenue_expr
        + slack_pen * sum(model.u[t] for t in model.h)
        + curt_pen
        * (solar_block.potential_minus_dispatch + wind_block.potential_minus_dispatch)
    )
    model.objective = pyo.Objective(expr=obj_expr, sense=pyo.minimize)

    model._sdom_outage_meta: dict[str, Any] = {  # noqa: SLF001
        "start_hour": start_hour,
        "end_hour": end_hour,
        "duration_hours": duration,
        "recovery_end_hour": recovery_end_hour,
        "recovery_target_MWh": recovery_target_MWh,
        "recovery_target_frac": dict(recovery_target_frac),
        "delta_thermal": delta_thermal,
        "delta_wind": delta_wind,
        "delta_solar": delta_solar,
        "delta_imports": delta_imports,
        "delta_nuclear": delta_nuc,
        "delta_hydro": delta_hydro,
        "delta_other_renewables": delta_other,
        "slack_penalty": slack_pen,
        "curtailment_penalty": curt_pen,
        "designed_system": designed_system,
    }
    return model
