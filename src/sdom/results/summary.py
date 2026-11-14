"""Build metric summary tables with reporting labels and units."""

import pandas as pd
from pyomo.environ import sqrt

from ..common.utilities import safe_pyomo_value
from ._values import _sum_initialized_dispatch
from .containers import OptimizationResults


def _curtailment_cost_metrics(cost_breakdown: dict) -> list[tuple[str, dict, str]]:
    """Return additive cost rows; older result dictionaries imply zero costs."""
    costs = cost_breakdown.get("curtailment_cost", {})
    return [
        (f"Total {label} curtailment cost", {technology: costs.get(technology, 0.0)}, "$US")
        for label, technology in (("Solar", "Solar PV"), ("Wind", "Wind"), ("Hydro", "Hydro"))
    ]


def _build_metric_summary(total_cost: float, metrics: list[tuple[str, dict, str]]) -> pd.DataFrame:
    """Build ordered summary rows in a single DataFrame construction."""
    # Total cost
    rows = [("Total cost", None, 1, total_cost, "$US")]
    for metric, values, unit in metrics:
        rows.extend((metric, technology, 1, value, unit) for technology, value in values.items())
    frame = pd.DataFrame.from_records(
        rows, columns=pd.Index(["Metric", "Technology", "Run", "Optimal Value", "Unit"])
    )
    frame["Technology"] = pd.Series([row[1] for row in rows], dtype=object)
    frame["Optimal Value"] = pd.to_numeric(frame["Optimal Value"], errors="coerce")
    return frame


def _build_summary_dataframe(model, results: OptimizationResults, storage_tech_list: list) -> pd.DataFrame:
    """Build the copperplate or per-area summary DataFrame from results.

    Parameters
    ----------
    model : pyomo.core.base.block.BlockData
        Solved model or area block exposing the technology components.
    results : OptimizationResults
        Results object with collected capacities, generation, and costs.
    storage_tech_list : list
        Storage technology identifiers in their existing reporting order.

    Returns
    -------
    pandas.DataFrame
        Ordered metrics with columns Metric, Technology, Run, Optimal Value,
        and Unit, including three signed technology curtailment costs in USD.
        These costs are already included in Total cost and are not added again.

    Raises
    ------
    ValueError
        If modeled imports, exports, or storage charging contain missing or
        nonfinite dispatch. Optional unmodeled imports and exports remain zero.
    """
    # Average power capacity
    avgpocap = {
        tech: (results.storage_capacity["charge"][tech] + results.storage_capacity["discharge"][tech]) / 2
        for tech in storage_tech_list
    }
    avgpocap["All"] = sum(avgpocap[t] for t in storage_tech_list)
    # Duration
    dis_dur = {
        tech: safe_pyomo_value(
            sqrt(model.storage.data["Eff", tech]) * model.storage.Ecap[tech] / (model.storage.Pdis[tech] + 1e-15)
        )
        for tech in storage_tech_list
    }
    # Imports/Exports totals
    imp_exp = {
        "Imports": (
            _sum_initialized_dispatch(model.imports.variable, model.h)
            if hasattr(model, "imports") and hasattr(model.imports, "variable")
            else 0
        ),
        "Exports": (
            _sum_initialized_dispatch(model.exports.variable, model.h)
            if hasattr(model, "exports") and hasattr(model.exports, "variable")
            else 0
        ),
    }
    # Storage discharge
    stodisch = {tech: results.generation_totals.get(tech, 0.0) for tech in storage_tech_list}
    stodisch["All"] = sum(stodisch[t] for t in storage_tech_list)
    # Demand
    dem = {"demand": sum(model.demand.ts_parameter[h] for h in model.h)}
    # Storage charging
    stoch = {
        tech: _sum_initialized_dispatch(model.storage.PC, model.h, technology=tech)
        for tech in storage_tech_list
    }
    stoch["All"] = sum(stoch[t] for t in storage_tech_list)
    # Total CAPEX (storage)
    tcapex = {
        tech: results.cost_breakdown["power_capex"][tech] + results.cost_breakdown["energy_capex"][tech]
        for tech in storage_tech_list
    }
    tcapex["All"] = sum(tcapex[t] for t in storage_tech_list)
    # OPEX
    opex = {
        "Thermal": results.cost_breakdown["fom"]["Thermal"] + results.cost_breakdown["vom"]["Thermal"],
        "Solar PV": results.cost_breakdown["fom"]["Solar PV"],
        "Wind": results.cost_breakdown["fom"]["Wind"],
    }
    opex_storage_total = 0.0
    for tech in storage_tech_list:
        opex[tech] = results.cost_breakdown["fom"][tech] + results.cost_breakdown["vom"][tech]
        opex_storage_total += opex[tech]
    opex["All"] = opex["Thermal"] + opex["Solar PV"] + opex["Wind"] + opex_storage_total
    # Equivalent number of cycles
    cyc = {
        tech: safe_pyomo_value(results.generation_totals.get(tech, 0.0) / (model.storage.Ecap[tech] + 1e-15))
        for tech in storage_tech_list
    }
    # VRE Curtailment
    pv_curtailment = safe_pyomo_value(model.pv.total_curtailment) if hasattr(model.pv, "total_curtailment") else 0.0
    wind_curtailment = safe_pyomo_value(model.wind.total_curtailment) if hasattr(model.wind, "total_curtailment") else 0.0
    pv_generation = safe_pyomo_value(model.pv.total_generation) if hasattr(model.pv, "total_generation") else 0.0
    wind_generation = safe_pyomo_value(model.wind.total_generation) if hasattr(model.wind, "total_generation") else 0.0
    total_vre_curtailment_mwh = pv_curtailment + wind_curtailment
    total_vre_availability = pv_generation + wind_generation + pv_curtailment + wind_curtailment
    total_vre_curtailment_pct = (
        total_vre_curtailment_mwh / total_vre_availability * 100 if total_vre_availability > 0 else 0.0
    )
    return _build_metric_summary(
        results.total_cost,
        [
            # Capacity
            ("Capacity", results.capacity, "MW"),
            # Storage capacities
            ("Charge power capacity", results.storage_capacity["charge"], "MW"),
            ("Discharge power capacity", results.storage_capacity["discharge"], "MW"),
            ("Average power capacity", avgpocap, "MW"),
            # Energy capacity
            ("Energy capacity", results.storage_capacity["energy"], "MWh"),
            ("Duration", dis_dur, "h"),
            # Generation
            ("Total generation", results.generation_totals, "MWh"),
            ("Total Imports/Exports", imp_exp, "MWh"),
            ("Storage energy discharging", stodisch, "MWh"),
            ("Total demand", dem, "MWh"),
            ("Storage energy charging", stoch, "MWh"),
            # CAPEX
            ("CAPEX", results.cost_breakdown["capex"], "$US"),
            # Power CAPEX
            ("Power-CAPEX", results.cost_breakdown["power_capex"], "$US"),
            # Energy CAPEX
            ("Energy-CAPEX", results.cost_breakdown["energy_capex"], "$US"),
            ("Total-CAPEX", tcapex, "$US"),
            # FOM
            ("FOM", results.cost_breakdown["fom"], "$US"),
            # VOM
            ("VOM", results.cost_breakdown["vom"], "$US"),
            # Fuel cost
            ("Fuel-Cost", results.cost_breakdown["fuel_cost"], "$US"),
            ("OPEX", opex, "$US"),
            # Imports/Exports costs
            ("Cost", {"Imports Cost": results.cost_breakdown["imports_cost"]}, "$US"),
            ("Revenue", {"Exports Revenue": results.cost_breakdown["exports_revenue"]}, "$US"),
            ("Equivalent number of cycles", cyc, "-"),
            (
                "Total VRE curtailment",
                {"Solar PV": pv_curtailment, "Wind": wind_curtailment, "All": total_vre_curtailment_mwh},
                "MWh",
            ),
            ("VRE curtailment percentage", {"All": total_vre_curtailment_pct}, "%"),
            *_curtailment_cost_metrics(results.cost_breakdown),
        ],
    )


def _build_zonal_summary_dataframe(
    results: OptimizationResults,
    storage_tech_list: list,
) -> pd.DataFrame:
    """Build a system-level summary from zonal aggregate result dictionaries.

    Parameters
    ----------
    results : OptimizationResults
        Zonal results with system-level aggregate dictionaries populated.
    storage_tech_list : list
        Storage technologies present in one or more areas.

    Returns
    -------
    pandas.DataFrame
        Summary rows matching the existing CSV and plotting schema, constructed
        from ordered metric groups in a single DataFrame. Technology curtailment
        costs sum the collected area contributions, without double counting.
    """
    storage_capacity = results.storage_capacity
    cost_breakdown = results.cost_breakdown
    # Average power capacity
    avgpocap = {
        tech: (storage_capacity["charge"].get(tech, 0.0) + storage_capacity["discharge"].get(tech, 0.0)) / 2
        for tech in storage_tech_list
    }
    avgpocap["All"] = sum(avgpocap.values())
    # Demand
    generation_df = results.generation_df
    total_demand = pd.to_numeric(
        generation_df.get("Load (MW)", pd.Series(dtype=float)), errors="coerce"
    ).sum()
    # Total CAPEX (storage)
    tcapex = {
        tech: cost_breakdown["power_capex"].get(tech, 0.0) + cost_breakdown["energy_capex"].get(tech, 0.0)
        for tech in storage_tech_list
    }
    tcapex["All"] = sum(tcapex.values())
    # OPEX
    opex = {
        tech: cost_breakdown["fom"].get(tech, 0.0) + cost_breakdown["vom"].get(tech, 0.0)
        for tech in ("Thermal", "Solar PV", "Wind", *storage_tech_list)
    }
    opex["All"] = sum(opex.values())
    # VRE Curtailment
    pv_curtailment = pd.to_numeric(
        generation_df.get("Solar PV Curtailment (MW)", pd.Series(dtype=float)), errors="coerce"
    ).sum()
    wind_curtailment = pd.to_numeric(
        generation_df.get("Wind Curtailment (MW)", pd.Series(dtype=float)), errors="coerce"
    ).sum()
    pv_generation = pd.to_numeric(
        generation_df.get("Solar PV Generation (MW)", pd.Series(dtype=float)), errors="coerce"
    ).sum()
    wind_generation = pd.to_numeric(
        generation_df.get("Wind Generation (MW)", pd.Series(dtype=float)), errors="coerce"
    ).sum()
    total_curtailment = pv_curtailment + wind_curtailment
    total_vre = total_curtailment + pv_generation + wind_generation
    return _build_metric_summary(
        results.total_cost,
        [
            # Capacity
            ("Capacity", results.capacity, "MW"),
            # Storage capacities
            ("Charge power capacity", storage_capacity["charge"], "MW"),
            ("Discharge power capacity", storage_capacity["discharge"], "MW"),
            ("Average power capacity", avgpocap, "MW"),
            # Energy capacity
            ("Energy capacity", storage_capacity["energy"], "MWh"),
            # Generation
            ("Total generation", results.generation_totals, "MWh"),
            ("Total demand", {"demand": total_demand}, "MWh"),
            # CAPEX
            ("CAPEX", cost_breakdown["capex"], "$US"),
            # Power CAPEX
            ("Power-CAPEX", cost_breakdown["power_capex"], "$US"),
            # Energy CAPEX
            ("Energy-CAPEX", cost_breakdown["energy_capex"], "$US"),
            ("Total-CAPEX", tcapex, "$US"),
            ("OPEX", opex, "$US"),
            (
                "Total VRE curtailment",
                {"Solar PV": pv_curtailment, "Wind": wind_curtailment, "All": total_curtailment},
                "MWh",
            ),
            ("VRE curtailment percentage", {"All": total_curtailment / total_vre * 100 if total_vre > 0 else 0.0}, "%"),
            *_curtailment_cost_metrics(cost_breakdown),
        ],
    )


def _append_hydro_curtailment_summary(
    summary: pd.DataFrame, budget_energy: tuple[float, float]
) -> pd.DataFrame:
    """Append system-wide unused hydro budget energy and its percentage.

    Parameters
    ----------
    summary : pandas.DataFrame
        Existing summary, including unchanged VRE metrics.
    budget_energy : tuple of float
        Aggregated budget and unused budget energy in MWh.

    Returns
    -------
    pandas.DataFrame
        Summary with two rows using technology Hydro and units TWh and %.
    """
    # Hydro curtailment
    budget, unused = budget_energy
    hydro_rows = pd.DataFrame(
        {
            "Metric": ["Total Hydro curtailment", "Hydro curtailment percentage"],
            "Technology": ["Hydro", "Hydro"],
            "Run": [1, 1],
            "Optimal Value": [unused / 1e6, 100.0 * unused / budget if budget > 0 else 0.0],
            "Unit": ["TWh", "%"],
        }
    )
    return pd.concat([summary, hydro_rows], ignore_index=True)
