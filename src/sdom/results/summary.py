"""Build metric summary tables with reporting labels and units."""


import pandas as pd
from pyomo.environ import sqrt

from ..common.utilities import concatenate_dataframes, safe_pyomo_value
from .containers import OptimizationResults


def _build_summary_dataframe(model, results: OptimizationResults, storage_tech_list: list) -> pd.DataFrame:
    """Build the summary DataFrame from results.

    Parameters
    ----------
    model : pyomo.core.base.PyomoModel.ConcreteModel
        The solved Pyomo model instance.
    results : OptimizationResults
        The results object with collected data.
    storage_tech_list : list
        List of storage technology identifiers.

    Returns
    -------
    pd.DataFrame
        Summary DataFrame with metrics.
    """
    # Total cost
    total_cost = pd.DataFrame.from_dict(
        {"Total cost": [None, 1, results.total_cost, "$US"]},
        orient="index",
        columns=["Technology", "Run", "Optimal Value", "Unit"],
    )
    total_cost = total_cost.reset_index(names="Metric")
    summary_results = total_cost

    # Capacity
    summary_results = concatenate_dataframes(summary_results, results.capacity, run=1, unit="MW", metric="Capacity")

    # Storage capacities
    summary_results = concatenate_dataframes(
        summary_results, results.storage_capacity["charge"], run=1, unit="MW", metric="Charge power capacity"
    )
    summary_results = concatenate_dataframes(
        summary_results, results.storage_capacity["discharge"], run=1, unit="MW", metric="Discharge power capacity"
    )

    # Average power capacity
    avgpocap = {}
    for tech in storage_tech_list:
        avgpocap[tech] = (results.storage_capacity["charge"][tech] + results.storage_capacity["discharge"][tech]) / 2
    avgpocap["All"] = sum(avgpocap[t] for t in storage_tech_list)
    summary_results = concatenate_dataframes(summary_results, avgpocap, run=1, unit="MW", metric="Average power capacity")

    # Energy capacity
    summary_results = concatenate_dataframes(
        summary_results, results.storage_capacity["energy"], run=1, unit="MWh", metric="Energy capacity"
    )

    # Duration
    dis_dur = {}
    for tech in storage_tech_list:
        dis_dur[tech] = safe_pyomo_value(
            sqrt(model.storage.data["Eff", tech]) * model.storage.Ecap[tech] / (model.storage.Pdis[tech] + 1e-15)
        )
    summary_results = concatenate_dataframes(summary_results, dis_dur, run=1, unit="h", metric="Duration")

    # Generation
    summary_results = concatenate_dataframes(
        summary_results, results.generation_totals, run=1, unit="MWh", metric="Total generation"
    )

    # Imports/Exports totals
    imp_exp = {}
    imp_exp["Imports"] = safe_pyomo_value(sum(model.imports.variable[h] for h in model.h)) if hasattr(model.imports, "variable") else 0
    imp_exp["Exports"] = safe_pyomo_value(sum(model.exports.variable[h] for h in model.h)) if hasattr(model.exports, "variable") else 0
    summary_results = concatenate_dataframes(summary_results, imp_exp, run=1, unit="MWh", metric="Total Imports/Exports")

    # Storage discharge
    stodisch = {tech: results.generation_totals.get(tech, 0.0) for tech in storage_tech_list}
    stodisch["All"] = sum(stodisch[t] for t in storage_tech_list)
    summary_results = concatenate_dataframes(summary_results, stodisch, run=1, unit="MWh", metric="Storage energy discharging")

    # Demand
    dem = {"demand": sum(model.demand.ts_parameter[h] for h in model.h)}
    summary_results = concatenate_dataframes(summary_results, dem, run=1, unit="MWh", metric="Total demand")

    # Storage charging
    stoch = {}
    for tech in storage_tech_list:
        stoch[tech] = safe_pyomo_value(sum(model.storage.PC[h, tech] for h in model.h))
    stoch["All"] = sum(stoch[t] for t in storage_tech_list)
    summary_results = concatenate_dataframes(summary_results, stoch, run=1, unit="MWh", metric="Storage energy charging")

    # CAPEX
    summary_results = concatenate_dataframes(
        summary_results, results.cost_breakdown["capex"], run=1, unit="$US", metric="CAPEX"
    )

    # Power CAPEX
    summary_results = concatenate_dataframes(
        summary_results, results.cost_breakdown["power_capex"], run=1, unit="$US", metric="Power-CAPEX"
    )

    # Energy CAPEX
    summary_results = concatenate_dataframes(
        summary_results, results.cost_breakdown["energy_capex"], run=1, unit="$US", metric="Energy-CAPEX"
    )

    # Total CAPEX (storage)
    tcapex = {}
    for tech in storage_tech_list:
        tcapex[tech] = results.cost_breakdown["power_capex"][tech] + results.cost_breakdown["energy_capex"][tech]
    tcapex["All"] = sum(tcapex[t] for t in storage_tech_list)
    summary_results = concatenate_dataframes(summary_results, tcapex, run=1, unit="$US", metric="Total-CAPEX")

    # FOM
    summary_results = concatenate_dataframes(summary_results, results.cost_breakdown["fom"], run=1, unit="$US", metric="FOM")

    # VOM
    summary_results = concatenate_dataframes(summary_results, results.cost_breakdown["vom"], run=1, unit="$US", metric="VOM")

    # Fuel cost
    summary_results = concatenate_dataframes(
        summary_results, results.cost_breakdown["fuel_cost"], run=1, unit="$US", metric="Fuel-Cost"
    )

    # OPEX
    opex = {}
    opex["Thermal"] = results.cost_breakdown["fom"]["Thermal"] + results.cost_breakdown["vom"]["Thermal"]
    opex["Solar PV"] = results.cost_breakdown["fom"]["Solar PV"]
    opex["Wind"] = results.cost_breakdown["fom"]["Wind"]
    opex_storage_total = 0.0
    for tech in storage_tech_list:
        opex[tech] = results.cost_breakdown["fom"][tech] + results.cost_breakdown["vom"][tech]
        opex_storage_total += opex[tech]
    opex["All"] = opex["Thermal"] + opex["Solar PV"] + opex["Wind"] + opex_storage_total
    summary_results = concatenate_dataframes(summary_results, opex, run=1, unit="$US", metric="OPEX")

    # Imports/Exports costs
    cost_revenue = {"Imports Cost": results.cost_breakdown["imports_cost"]}
    summary_results = concatenate_dataframes(summary_results, cost_revenue, run=1, unit="$US", metric="Cost")
    cost_revenue = {"Exports Revenue": results.cost_breakdown["exports_revenue"]}
    summary_results = concatenate_dataframes(summary_results, cost_revenue, run=1, unit="$US", metric="Revenue")

    # Equivalent number of cycles
    cyc = {}
    for tech in storage_tech_list:
        cyc[tech] = safe_pyomo_value(results.generation_totals.get(tech, 0.0) / (model.storage.Ecap[tech] + 1e-15))
    summary_results = concatenate_dataframes(summary_results, cyc, run=1, unit="-", metric="Equivalent number of cycles")

    # VRE Curtailment
    pv_curtailment = safe_pyomo_value(model.pv.total_curtailment) if hasattr(model.pv, "total_curtailment") else 0.0
    wind_curtailment = safe_pyomo_value(model.wind.total_curtailment) if hasattr(model.wind, "total_curtailment") else 0.0
    pv_generation = safe_pyomo_value(model.pv.total_generation) if hasattr(model.pv, "total_generation") else 0.0
    wind_generation = safe_pyomo_value(model.wind.total_generation) if hasattr(model.wind, "total_generation") else 0.0

    total_vre_curtailment_mwh = pv_curtailment + wind_curtailment
    total_vre_availability = pv_generation + wind_generation + pv_curtailment + wind_curtailment
    total_vre_curtailment_pct = (total_vre_curtailment_mwh / total_vre_availability * 100) if total_vre_availability > 0 else 0.0

    vre_curt_mwh = {"Solar PV": pv_curtailment, "Wind": wind_curtailment, "All": total_vre_curtailment_mwh}
    summary_results = concatenate_dataframes(summary_results, vre_curt_mwh, run=1, unit="MWh", metric="Total VRE curtailment")

    vre_curt_pct = {"All": total_vre_curtailment_pct}
    summary_results = concatenate_dataframes(summary_results, vre_curt_pct, run=1, unit="%", metric="VRE curtailment percentage")

    return summary_results


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
    pd.DataFrame
        Summary rows matching the legacy summary schema used by CSV export and
        standard plotting functions.
    """
    total_cost = pd.DataFrame.from_dict(
        {"Total cost": [None, 1, results.total_cost, "$US"]},
        orient="index",
        columns=["Technology", "Run", "Optimal Value", "Unit"],
    ).reset_index(names="Metric")

    def append(metric: str, values: dict, unit: str) -> None:
        nonlocal total_cost
        total_cost = concatenate_dataframes(
            total_cost, values, run=1, unit=unit, metric=metric
        )

    storage_capacity = results.storage_capacity
    cost_breakdown = results.cost_breakdown
    append("Capacity", results.capacity, "MW")
    append("Charge power capacity", storage_capacity["charge"], "MW")
    append("Discharge power capacity", storage_capacity["discharge"], "MW")
    append(
        "Average power capacity",
        {
            tech: (
                storage_capacity["charge"].get(tech, 0.0)
                + storage_capacity["discharge"].get(tech, 0.0)
            )
            / 2
            for tech in storage_tech_list
        }
        | {
            "All": sum(
                (
                    storage_capacity["charge"].get(tech, 0.0)
                    + storage_capacity["discharge"].get(tech, 0.0)
                )
                / 2
                for tech in storage_tech_list
            )
        },
        "MW",
    )
    append("Energy capacity", storage_capacity["energy"], "MWh")
    append("Total generation", results.generation_totals, "MWh")

    generation_df = results.generation_df
    total_demand = pd.to_numeric(
        generation_df.get("Load (MW)", pd.Series(dtype=float)), errors="coerce"
    ).sum()
    append("Total demand", {"demand": total_demand}, "MWh")

    append("CAPEX", cost_breakdown["capex"], "$US")
    append("Power-CAPEX", cost_breakdown["power_capex"], "$US")
    append("Energy-CAPEX", cost_breakdown["energy_capex"], "$US")
    append(
        "Total-CAPEX",
        {
            tech: cost_breakdown["power_capex"].get(tech, 0.0)
            + cost_breakdown["energy_capex"].get(tech, 0.0)
            for tech in storage_tech_list
        }
        | {
            "All": sum(
                cost_breakdown["power_capex"].get(tech, 0.0)
                + cost_breakdown["energy_capex"].get(tech, 0.0)
                for tech in storage_tech_list
            )
        },
        "$US",
    )
    opex = {
        tech: cost_breakdown["fom"].get(tech, 0.0)
        + cost_breakdown["vom"].get(tech, 0.0)
        for tech in ("Thermal", "Solar PV", "Wind", *storage_tech_list)
    }
    opex["All"] = sum(opex.values())
    append("OPEX", opex, "$US")

    pv_curtailment = pd.to_numeric(
        generation_df.get("Solar PV Curtailment (MW)", pd.Series(dtype=float)),
        errors="coerce",
    ).sum()
    wind_curtailment = pd.to_numeric(
        generation_df.get("Wind Curtailment (MW)", pd.Series(dtype=float)),
        errors="coerce",
    ).sum()
    pv_generation = pd.to_numeric(
        generation_df.get("Solar PV Generation (MW)", pd.Series(dtype=float)),
        errors="coerce",
    ).sum()
    wind_generation = pd.to_numeric(
        generation_df.get("Wind Generation (MW)", pd.Series(dtype=float)),
        errors="coerce",
    ).sum()
    total_curtailment = pv_curtailment + wind_curtailment
    total_vre = total_curtailment + pv_generation + wind_generation
    append(
        "Total VRE curtailment",
        {"Solar PV": pv_curtailment, "Wind": wind_curtailment, "All": total_curtailment},
        "MWh",
    )
    append(
        "VRE curtailment percentage",
        {"All": total_curtailment / total_vre * 100 if total_vre > 0 else 0.0},
        "%",
    )
    return total_cost


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
        Summary with two rows using technology ``Hydro`` and units TWh and %.
    """
    budget, unused = budget_energy
    summary = concatenate_dataframes(
        summary, {"Hydro": unused / 1e6}, run=1, unit="TWh", metric="Total Hydro curtailment"
    )
    return concatenate_dataframes(
        summary,
        {"Hydro": 100.0 * unused / budget if budget > 0 else 0.0},
        run=1,
        unit="%",
        metric="Hydro curtailment percentage",
    )
