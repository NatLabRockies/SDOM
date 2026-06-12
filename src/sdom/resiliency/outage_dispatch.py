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
import math
from typing import Any

import pandas as pd
import pyomo.environ as pyo

from sdom.constants import MW_TO_KW
from sdom.resiliency.system_state import BaselineDispatchResults, DesignedSystem
from sdom.utils_performance_meassure import ModelInitProfiler


logger = logging.getLogger(__name__)


__all__ = ["build_outage_dispatch"]


def _run_step(profiler, name, func, *args, **kwargs):
    """Run ``func(*args, **kwargs)``, optionally measuring it via ``profiler``."""
    if profiler is None:
        return func(*args, **kwargs)
    return profiler.measure_step(name, func, *args, **kwargs)


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


def _compute_prorated_fom_USD(
    designed_system: DesignedSystem,
    *,
    horizon_hours: int,
    year_hours: int = 8760,
) -> float:
    """Total fixed-O&M cost (USD) prorated to ``horizon_hours / year_hours``.

    Storage FOM splits by ``CostRatio`` between charge / discharge sides,
    mirroring
    :func:`sdom.models.formulations_storage.storage_fixed_om_cost_expr_rule`.
    Thermal / solar / wind FOM are USD/kW-yr, multiplied by capacity (MW)
    and :data:`sdom.constants.MW_TO_KW` to give USD/yr, then scaled by the
    horizon fraction. FOM is independent of dispatch, so this enters the
    outage LP as a constant.
    """
    if horizon_hours <= 0 or year_hours <= 0:
        return 0.0
    frac = float(horizon_hours) / float(year_hours)

    fom_annual_USD = 0.0
    for spec in designed_system.storage_caps.values():
        fom = float(spec.get("fom", 0.0))
        cr = float(spec.get("cost_ratio", 0.5))
        cap_pch = float(spec.get("Cap_Pch", 0.0))
        cap_pdis = float(spec.get("Cap_Pdis", 0.0))
        fom_annual_USD += MW_TO_KW * fom * (cr * cap_pch + (1.0 - cr) * cap_pdis)

    for spec in designed_system.thermal_caps.values():
        fom = float(spec.get("fom", 0.0))
        cap = float(spec.get("capacity_MW", 0.0))
        fom_annual_USD += MW_TO_KW * fom * cap

    for k, cap in designed_system.solar_caps.items():
        fom = float(designed_system.solar_fom.get(k, 0.0))
        fom_annual_USD += MW_TO_KW * fom * float(cap)

    for k, cap in designed_system.wind_caps.items():
        fom = float(designed_system.wind_fom.get(k, 0.0))
        fom_annual_USD += MW_TO_KW * fom * float(cap)

    return fom_annual_USD * frac


# ---------------------------------------------------------------------------
# Sub-block builders (outage variants)
# ---------------------------------------------------------------------------
def _add_storage_block_outage(
    model: pyo.ConcreteModel,
    designed_system: DesignedSystem,
    soc_min_frac_map: dict[str, float],
    start_hour: int,
    delta_storage: dict[tuple[str, int], float] | None = None,
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

    delta_storage = delta_storage or {}

    block.Cap_Pch = pyo.Param(block.S, initialize=cap_pch)
    block.Cap_Pdis = pyo.Param(block.S, initialize=cap_pdis)
    block.Cap_E = pyo.Param(block.S, initialize=cap_e)
    block.eta_ch = pyo.Param(block.S, initialize=eta_ch)
    block.eta_dis = pyo.Param(block.S, initialize=eta_dis)
    block.vom = pyo.Param(block.S, initialize=vom)

    def _pcha_bounds(b, s, t):
        return (0.0, delta_storage.get((s, t), 1.0) * cap_pch[s])

    def _pdis_bounds(b, s, t):
        return (0.0, delta_storage.get((s, t), 1.0) * cap_pdis[s])

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

    # Prior-state boundary: SOC at the start of ``start_hour`` (= SOC at the
    # end of ``start_hour - 1``). Seeded later by ``_seed_initial_soc``.
    block.SOC_init = pyo.Param(block.S, mutable=True, initialize=0.0)

    def _soc_dynamics(b, s, t):
        prev = b.SOC_init[s] if t == start_hour else b.SOC[s, t - 1]
        return (
            b.SOC[s, t]
            == prev + b.eta_ch[s] * b.Pcha[s, t] - b.Pdis[s, t] / b.eta_dis[s]
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
    soc_slack_penalty=1_000.0,
    min_soc_per_tech=None,
    n_hours=8760,
    critical_load_MW=None,
    model_name="SDOM_OutageDispatch",
    profile=False,
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
    soc_slack_penalty : float, optional
        Penalty :math:`\\pi^{soc}` (USD/MWh) on the per-storage-tech
        slack variable that relaxes the SOC recovery-target constraint
        (see notes). Default ``1_000.0``. The operational SOC floor
        remains a hard bound; only the end-of-recovery target is
        relaxed.
    min_soc_per_tech : dict, optional
        Operational SOC floor per storage tech (fraction of ``Cap_E``).
        Same semantics as :func:`build_baseline_dispatch`.
    n_hours : int, optional
        Length of the baseline horizon used for end-of-year clipping.
        Default ``8760``.
    critical_load_MW : float, optional
        Constant critical load (MW) used in place of
        ``designed_system.load[t]`` for every hour ``t`` in the outage
        sub-horizon ``[start_hour, start_hour + duration_hours - 1]``
        (clipped to the LP end hour). Recovery-window hours continue to
        use the original ``D_t``. ``None`` (default) preserves the
        original behaviour: the hourly load series is used everywhere.
        Must be non-negative.
    model_name : str, optional
        Pyomo model name. Default ``"SDOM_OutageDispatch"``.
    profile : bool, optional
        When ``True``, instrument the build stages with a
        :class:`~sdom.utils_performance_meassure.ModelInitProfiler`,
        attach it as ``model.profiler`` and print a summary table.
        Default ``False``. Note: enabling this from inside a parallel
        ``ProcessPoolExecutor`` will produce one summary per worker on
        each spawned process, which is rarely useful. Prefer ``profile``
        only in serial runs.

    Returns
    -------
    pyomo.environ.ConcreteModel
        A Pyomo LP exposing ``model.h`` (hour set), ``model.u`` (slack,
        ``NonNegativeReals``), the standard dispatch sub-blocks
        (``storage``, ``thermal``, ``solar``, ``wind``, ``imports``,
        ``exports``) without demand-charge variables, ``model.fom_cost_expr``
        (constant fixed-O&M cost prorated to the outage horizon), and an
        objective that minimises operational cost plus slack and
        curtailment penalties plus the prorated FOM constant.

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
    Initial SOC is seeded by setting the mutable parameter
    ``model.storage.SOC_init[s]`` from ``baseline_results.soc_trajectory``
    at ``start_hour``. ``SOC_init`` represents the SOC at the *start* of
    the outage horizon (i.e., the boundary value :math:`SOC_{s,h-1}` that
    the dynamics equation at :math:`t = h` reads as its prior state). The
    SOC dynamics constraint therefore covers every hour in
    :math:`\\mathcal{T}^{out}_h`, including the anchor hour ``start_hour``,
    so that the charge and discharge variables at the anchor hour appear
    in a balance equation. Earlier versions fixed ``SOC[s, start_hour]``
    via :py:meth:`pyomo.environ.Var.fix` and skipped the dynamics
    equation at the anchor; under that formulation ``Pcha[s, start_hour]``
    and ``Pdis[s, start_hour]`` for surviving (non-outaged) storage techs
    were unconstrained by any SOC balance.

    When ``critical_load_MW`` is provided, the load parameter is overridden
    only over the outage sub-horizon
    :math:`\\mathcal{T}^{out}_h = \\{h, \\ldots, h + \\Delta^{out} - 1\\}`;
    hours in the recovery sub-horizon retain the original ``D_t`` so that
    storage replenishment toward the end-of-recovery target reflects
    realistic post-outage operations.
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
    if critical_load_MW is not None:
        crit_val = float(critical_load_MW)
        if not math.isfinite(crit_val):
            raise ValueError(
                f"critical_load_MW must be a finite number; got {critical_load_MW}."
            )
        if crit_val < 0:
            raise ValueError(
                f"critical_load_MW must be non-negative; got {critical_load_MW}."
            )
        critical_load_MW = crit_val

    profiler = None
    if profile:
        profiler = ModelInitProfiler(track_memory=True, enabled=True)
        profiler.start()

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
    def _build_deltas():
        delta_thermal: dict[tuple[str, int], float] = {}
        delta_wind: dict[tuple[str, int], float] = {}
        delta_solar: dict[tuple[str, int], float] = {}
        delta_storage: dict[tuple[str, int], float] = {}
        delta_imports: dict[int, float] = {}
        delta_nuc: dict[int, float] = {}
        delta_hydro: dict[int, float] = {}
        delta_other: dict[int, float] = {}

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
        _populate("storage", designed_system.storage_caps.keys(), delta_storage)

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
        return (
            delta_thermal,
            delta_wind,
            delta_solar,
            delta_storage,
            delta_imports,
            delta_nuc,
            delta_hydro,
            delta_other,
        )

    horizon = list(range(start_hour, end_hour + 1))
    (
        delta_thermal,
        delta_wind,
        delta_solar,
        delta_storage,
        delta_imports,
        delta_nuc,
        delta_hydro,
        delta_other,
    ) = _run_step(profiler, "Build delta multipliers", _build_deltas)

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
    def _create_model_and_index():
        m = pyo.ConcreteModel(name=model_name)
        m.h = pyo.RangeSet(start_hour, end_hour)
        return m

    model = _run_step(profiler, "Create model & hour index", _create_model_and_index)

    storage_block = _run_step(
        profiler,
        "Add storage block",
        _add_storage_block_outage,
        model,
        designed_system,
        soc_min_frac_map,
        start_hour,
        delta_storage,
    )
    thermal_block = _run_step(
        profiler,
        "Add thermal block",
        _add_thermal_block_outage,
        model,
        designed_system,
        delta_thermal,
    )

    solar_plants = list(designed_system.solar_caps.keys())
    wind_plants = list(designed_system.wind_caps.keys())
    solar_block = _run_step(
        profiler,
        "Add solar VRE block",
        _add_vre_block_outage,
        model,
        block_name="solar",
        var_name="Psolar",
        plants=solar_plants,
        caps=designed_system.solar_caps,
        cf=designed_system.cf_solar if designed_system.cf_solar is not None else pd.DataFrame(),
        delta_map=delta_solar,
    )
    wind_block = _run_step(
        profiler,
        "Add wind VRE block",
        _add_vre_block_outage,
        model,
        block_name="wind",
        var_name="Pwind",
        plants=wind_plants,
        caps=designed_system.wind_caps,
        cf=designed_system.cf_wind if designed_system.cf_wind is not None else pd.DataFrame(),
        delta_map=delta_wind,
    )
    imports_block = _run_step(
        profiler,
        "Add imports block",
        _add_imports_block_outage,
        model,
        designed_system,
        delta_imports,
    )
    exports_block = _run_step(
        profiler,
        "Add exports block",
        _add_exports_block_outage,
        model,
        designed_system,
    )

    # Effective must-run parameters
    def _add_must_run_params():
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
        if critical_load_MW is None:
            load_param = {t: _series_value(designed_system.load, t) for t in horizon}
        else:
            outage_end = min(start_hour + duration - 1, end_hour)
            load_param = {
                t: critical_load_MW
                if start_hour <= t <= outage_end
                else _series_value(designed_system.load, t)
                for t in horizon
            }

        model.nuclear_eff_param = pyo.Param(model.h, initialize=nuclear_eff, mutable=False)
        model.hydro_eff_param = pyo.Param(model.h, initialize=hydro_eff, mutable=False)
        model.other_ren_eff_param = pyo.Param(model.h, initialize=other_ren_eff, mutable=False)
        model.load_param = pyo.Param(model.h, initialize=load_param, mutable=False)

    _run_step(profiler, "Add must-run / load params", _add_must_run_params)

    # Slack u[t] (MWh)
    def _add_slack_var():
        model.u = pyo.Var(model.h, domain=pyo.NonNegativeReals, initialize=0.0)

    _run_step(profiler, "Add slack variable u[t]", _add_slack_var)

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

    def _add_power_balance():
        model.power_balance = pyo.Constraint(model.h, rule=_balance_rule)

    _run_step(profiler, "Add power balance constraint", _add_power_balance)

    # Initial SOC (math_model 5.5)
    def _seed_initial_soc():
        soc_traj = baseline_results.soc_trajectory
        if soc_traj is None:
            raise ValueError(
                "baseline_results.soc_trajectory is required to seed initial SOC."
            )
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
            storage_block.SOC_init[s] = init_value

    _run_step(profiler, "Seed initial SOC", _seed_initial_soc)

    # Recovery target
    def _build_recovery_target():
        recovery_target_frac_local = outage_spec.resolve_min_soc_recovery(
            baseline_results,
            designed_system,
            recovery_end_hour=recovery_end_hour,
        )
        recovery_target_MWh_local: dict[str, float] = {}
        for s in storage_techs:
            cap_e = float(designed_system.storage_caps[s]["Cap_E"])
            recovery_target_MWh_local[s] = (
                float(recovery_target_frac_local.get(s, 0.0)) * cap_e
            )

        # Recovery-target SOC slack (#68): non-negative per-tech relaxation
        # of the end-of-recovery target. The operational SOC floor stays
        # a hard bound; only this end-of-recovery target is softened.
        model.recovery_soc_slack = pyo.Var(
            storage_block.S,
            domain=pyo.NonNegativeReals,
            initialize=0.0,
        )

        def _recovery_target_rule(m, s):
            t_end = recovery_end_hour[s]
            if t_end < start_hour or t_end > end_hour:
                return pyo.Constraint.Skip
            return (
                storage_block.SOC[s, t_end] + model.recovery_soc_slack[s]
                >= recovery_target_MWh_local[s]
            )

        model.recovery_target = pyo.Constraint(
            storage_block.S, rule=_recovery_target_rule
        )
        return recovery_target_frac_local, recovery_target_MWh_local

    recovery_target_frac, recovery_target_MWh = _run_step(
        profiler, "Add recovery target constraint", _build_recovery_target
    )

    # Objective
    slack_pen = float(slack_penalty)
    curt_pen = float(curtailment_penalty)
    soc_slack_pen = float(soc_slack_penalty)
    if slack_pen < 0:
        raise ValueError("slack_penalty must be non-negative.")
    if curt_pen < 0:
        raise ValueError("curtailment_penalty must be non-negative.")
    if soc_slack_pen < 0:
        raise ValueError("soc_slack_penalty must be non-negative.")

    horizon_hours = end_hour - start_hour + 1
    fom_cost_USD = _compute_prorated_fom_USD(
        designed_system, horizon_hours=horizon_hours, year_hours=8760
    )
    model.fom_cost_expr = pyo.Expression(expr=float(fom_cost_USD))

    def _add_objective():
        obj_expr = (
            thermal_block.cost_expr
            + storage_block.cost_expr
            + imports_block.total_cost_expr
            - exports_block.revenue_expr
            + slack_pen * sum(model.u[t] for t in model.h)
            + soc_slack_pen
            * sum(model.recovery_soc_slack[s] for s in storage_techs)
            + curt_pen
            * (
                solar_block.potential_minus_dispatch
                + wind_block.potential_minus_dispatch
            )
            + model.fom_cost_expr
        )
        model.objective = pyo.Objective(expr=obj_expr, sense=pyo.minimize)

    _run_step(profiler, "Add objective", _add_objective)

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
        "delta_storage": delta_storage,
        "delta_imports": delta_imports,
        "delta_nuclear": delta_nuc,
        "delta_hydro": delta_hydro,
        "delta_other_renewables": delta_other,
        "slack_penalty": slack_pen,
        "curtailment_penalty": curt_pen,
        "soc_slack_penalty": soc_slack_pen,
        "horizon_hours": horizon_hours,
        "fom_cost_USD": float(fom_cost_USD),
        "critical_load_MW": None if critical_load_MW is None else float(critical_load_MW),
        "designed_system": designed_system,
    }
    if profiler is not None:
        profiler.stop()
        profiler.print_summary_table(
            logger,
            title=f"OUTAGE DISPATCH BUILD PROFILING SUMMARY (start_hour={start_hour})",
        )
        model.profiler = profiler
    return model
