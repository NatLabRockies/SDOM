"""Preserve deprecated direct-Pyomo CSV export behavior."""

import csv
import logging
import os

import pandas as pd
from pyomo.environ import sqrt

from ..common.utilities import (
    concatenate_dataframes,
    safe_pyomo_value,
)
from ..constants import (
    MW_TO_KW,
)
from ..results import _collect_thermal_generation_dataframe


def _export_from_model_legacy(model, case, output_dir="./results_pyomo/"):
    """Legacy export function that works directly with a model object.

    Preserve the original outputs except individual thermal dispatch, which
    uses the same long schema as the structured results export.

    Parameters
    ----------
    model : pyomo.core.base.PyomoModel.ConcreteModel
        Solved Pyomo model instance.
    case : str
        Case identifier for filenames.
    output_dir : str
        Output directory path.
    """
    logging.info("Exporting SDOM results (legacy mode)...")
    os.makedirs(output_dir, exist_ok=True)

    # Initialize results dictionaries column: [values]
    logging.debug("--Initializing results dictionaries...")
    gen_results = {
        "Scenario": [],
        "Hour": [],
        "Solar PV Generation (MW)": [],
        "Solar PV Curtailment (MW)": [],
        "Wind Generation (MW)": [],
        "Wind Curtailment (MW)": [],
        "All Thermal Generation (MW)": [],
        "Hydro Generation (MW)": [],
        "Nuclear Generation (MW)": [],
        "Other Renewables Generation (MW)": [],
        "Imports (MW)": [],
        "Storage Charge/Discharge (MW)": [],
        "Exports (MW)": [],
        "Load (MW)": [],
        "Net Load (MW)": [],
    }

    storage_results = {
        "Hour": [],
        "Technology": [],
        "Charging power (MW)": [],
        "Discharging power (MW)": [],
        "State of charge (MWh)": [],
    }

    # Extract generation results
    logging.debug("--Extracting generation results...")
    for h in model.h:
        solar_gen = safe_pyomo_value(model.pv.generation[h])
        solar_curt = safe_pyomo_value(model.pv.curtailment[h])
        wind_gen = safe_pyomo_value(model.wind.generation[h])
        wind_curt = safe_pyomo_value(model.wind.curtailment[h])
        gas_cc_gen = sum(safe_pyomo_value(model.thermal.generation[h, bu]) for bu in model.thermal.plants_set)
        hydro = safe_pyomo_value(model.hydro.generation[h])
        nuclear = (
            safe_pyomo_value(model.nuclear.alpha * model.nuclear.ts_parameter[h])
            if hasattr(model.nuclear, "alpha")
            else 0
        )
        other_renewables = (
            safe_pyomo_value(model.other_renewables.alpha * model.other_renewables.ts_parameter[h])
            if hasattr(model.other_renewables, "alpha")
            else 0
        )
        imports = safe_pyomo_value(model.imports.variable[h]) if hasattr(model.imports, "variable") else 0
        exports = safe_pyomo_value(model.exports.variable[h]) if hasattr(model.exports, "variable") else 0
        load = safe_pyomo_value(model.demand.ts_parameter[h]) if hasattr(model.demand, "ts_parameter") else 0
        net_load = safe_pyomo_value(model.net_load[h]) if hasattr(model, "net_load") else 0
        # Only append results if all values are valid (not None)
        if None not in [
            solar_gen,
            solar_curt,
            wind_gen,
            wind_curt,
            gas_cc_gen,
            hydro,
            imports,
            exports,
            load,
        ]:
            gen_results["Hour"].append(h)
            gen_results["Solar PV Generation (MW)"].append(solar_gen)
            gen_results["Solar PV Curtailment (MW)"].append(solar_curt)
            gen_results["Wind Generation (MW)"].append(wind_gen)
            gen_results["Wind Curtailment (MW)"].append(wind_curt)
            gen_results["All Thermal Generation (MW)"].append(gas_cc_gen)
            gen_results["Hydro Generation (MW)"].append(hydro)
            gen_results["Nuclear Generation (MW)"].append(nuclear)
            gen_results["Other Renewables Generation (MW)"].append(other_renewables)
            gen_results["Imports (MW)"].append(imports)

            power_to_storage = sum(
                safe_pyomo_value(model.storage.PC[h, j]) or 0 for j in model.storage.j
            ) - sum(safe_pyomo_value(model.storage.PD[h, j]) or 0 for j in model.storage.j)
            gen_results["Storage Charge/Discharge (MW)"].append(power_to_storage)
            gen_results["Exports (MW)"].append(exports)
            gen_results["Load (MW)"].append(load)
            gen_results["Net Load (MW)"].append(net_load)
        gen_results["Scenario"].append(case)

    # Extract storage results
    logging.debug("--Extracting storage results...")
    for h in model.h:
        for j in model.storage.j:
            charge_power = safe_pyomo_value(model.storage.PC[h, j])
            discharge_power = safe_pyomo_value(model.storage.PD[h, j])
            soc = safe_pyomo_value(model.storage.SOC[h, j])
            if None not in [charge_power, discharge_power, soc]:
                storage_results["Hour"].append(h)
                storage_results["Technology"].append(j)
                storage_results["Charging power (MW)"].append(charge_power)
                storage_results["Discharging power (MW)"].append(discharge_power)
                storage_results["State of charge (MWh)"].append(soc)

    # Summary results (total capacities and costs)
    ## Total cost
    logging.debug("--Extracting summary results...")
    total_cost = pd.DataFrame.from_dict(
        {"Total cost": [None, 1, safe_pyomo_value(model.Obj()), "$US"]},
        orient="index",
        columns=["Technology", "Run", "Optimal Value", "Unit"],
    )
    total_cost = total_cost.reset_index(names="Metric")
    summary_results = total_cost

    ## Total capacity
    cap = {}
    cap["Thermal"] = sum(
        safe_pyomo_value(model.thermal.plant_installed_capacity[bu]) for bu in model.thermal.plants_set
    )
    cap["Solar PV"] = safe_pyomo_value(model.pv.total_installed_capacity)
    cap["Wind"] = safe_pyomo_value(model.wind.total_installed_capacity)
    cap["All"] = cap["Thermal"] + cap["Solar PV"] + cap["Wind"]

    summary_results = concatenate_dataframes(summary_results, cap, run=1, unit="MW", metric="Capacity")

    ## Charge power capacity
    storage_tech_list = list(model.storage.j)
    charge = {}
    sum_all = 0.0
    for tech in storage_tech_list:
        charge[tech] = safe_pyomo_value(model.storage.Pcha[tech])
        sum_all += charge[tech]
    charge["All"] = sum_all

    summary_results = concatenate_dataframes(
        summary_results, charge, run=1, unit="MW", metric="Charge power capacity"
    )

    ## Discharge power capacity
    dcharge = {}
    sum_all = 0.0

    for tech in storage_tech_list:
        dcharge[tech] = safe_pyomo_value(model.storage.Pdis[tech])
        sum_all += dcharge[tech]
    dcharge["All"] = sum_all

    summary_results = concatenate_dataframes(
        summary_results, dcharge, run=1, unit="MW", metric="Discharge power capacity"
    )

    ## Average power capacity
    avgpocap = {}
    sum_all = 0.0
    for tech in storage_tech_list:
        avgpocap[tech] = (charge[tech] + dcharge[tech]) / 2
        sum_all += avgpocap[tech]
    avgpocap["All"] = sum_all

    summary_results = concatenate_dataframes(
        summary_results, avgpocap, run=1, unit="MW", metric="Average power capacity"
    )

    ## Energy capacity
    encap = {}
    sum_all = 0.0
    for tech in storage_tech_list:
        encap[tech] = safe_pyomo_value(model.storage.Ecap[tech])
        sum_all += encap[tech]
    encap["All"] = sum_all

    summary_results = concatenate_dataframes(
        summary_results, encap, run=1, unit="MWh", metric="Energy capacity"
    )

    ## Discharge duration
    dis_dur = {}
    for tech in storage_tech_list:
        dis_dur[tech] = safe_pyomo_value(
            sqrt(model.storage.data["Eff", tech])
            * model.storage.Ecap[tech]
            / (model.storage.Pdis[tech] + 1e-15)
        )

    summary_results = concatenate_dataframes(summary_results, dis_dur, run=1, unit="h", metric="Duration")

    ## Generation
    gen = {}
    gen["Thermal"] = safe_pyomo_value(model.thermal.total_generation)
    gen["Solar PV"] = safe_pyomo_value(model.pv.total_generation)
    gen["Wind"] = safe_pyomo_value(model.wind.total_generation)
    gen["Other renewables"] = safe_pyomo_value(sum(model.other_renewables.ts_parameter[h] for h in model.h))
    gen["Hydro"] = safe_pyomo_value(sum(model.hydro.generation[h] for h in model.h))
    gen["Nuclear"] = safe_pyomo_value(sum(model.nuclear.ts_parameter[h] for h in model.h))

    # Storage energy discharging
    sum_all = 0.0
    storage_tech_list = list(model.storage.j)
    for tech in storage_tech_list:
        gen[tech] = safe_pyomo_value(sum(model.storage.PD[h, tech] for h in model.h))
        sum_all += gen[tech]

    gen["All"] = (
        gen["Thermal"]
        + gen["Solar PV"]
        + gen["Wind"]
        + gen["Other renewables"]
        + gen["Hydro"]
        + gen["Nuclear"]
        + sum_all
    )

    summary_results = concatenate_dataframes(
        summary_results, gen, run=1, unit="MWh", metric="Total generation"
    )

    imp_exp = {}
    imp_exp["Imports"] = (
        safe_pyomo_value(sum(model.imports.variable[h] for h in model.h))
        if hasattr(model.imports, "variable")
        else 0
    )
    imp_exp["Exports"] = (
        safe_pyomo_value(sum(model.exports.variable[h] for h in model.h))
        if hasattr(model.exports, "variable")
        else 0
    )
    summary_results = concatenate_dataframes(
        summary_results, imp_exp, run=1, unit="MWh", metric="Total Imports/Exports"
    )

    ## Storage energy discharging
    sum_all = 0.0
    stodisch = {}
    for tech in storage_tech_list:
        stodisch[tech] = safe_pyomo_value(sum(model.storage.PD[h, tech] for h in model.h))
        sum_all += stodisch[tech]
    stodisch["All"] = sum_all

    summary_results = concatenate_dataframes(
        summary_results, stodisch, run=1, unit="MWh", metric="Storage energy discharging"
    )

    ## Demand
    dem = {}
    dem["demand"] = sum(model.demand.ts_parameter[h] for h in model.h)

    summary_results = concatenate_dataframes(summary_results, dem, run=1, unit="MWh", metric="Total demand")

    ## Storage energy charging
    sum_all = 0.0
    stoch = {}
    for tech in storage_tech_list:
        stoch[tech] = safe_pyomo_value(sum(model.storage.PC[h, tech] for h in model.h))
        sum_all += stoch[tech]
    stoch["All"] = sum_all

    summary_results = concatenate_dataframes(
        summary_results, stoch, run=1, unit="MWh", metric="Storage energy charging"
    )

    ## CAPEX
    capex = {}
    capex["Solar PV"] = safe_pyomo_value(model.pv.capex_cost_expr)
    capex["Wind"] = safe_pyomo_value(model.wind.capex_cost_expr)
    capex["Thermal"] = safe_pyomo_value(model.thermal.capex_cost_expr)
    capex["All"] = capex["Solar PV"] + capex["Wind"] + capex["Thermal"]

    summary_results = concatenate_dataframes(summary_results, capex, run=1, unit="$US", metric="CAPEX")

    ## Power CAPEX
    pcapex = {}
    sum_all = 0.0
    for tech in storage_tech_list:
        pcapex[tech] = safe_pyomo_value(model.storage.power_capex_cost_expr[tech])
        sum_all += pcapex[tech]

    pcapex["All"] = sum_all

    summary_results = concatenate_dataframes(summary_results, pcapex, run=1, unit="$US", metric="Power-CAPEX")

    ## Energy CAPEX and Total CAPEX
    ecapex = {}
    tcapex = {}
    sum_all = 0.0
    sum_all_t = 0.0
    for tech in storage_tech_list:
        ecapex[tech] = safe_pyomo_value(model.storage.energy_capex_cost_expr[tech])
        sum_all += ecapex[tech]
        tcapex[tech] = pcapex[tech] + ecapex[tech]
        sum_all_t += tcapex[tech]
    ecapex["All"] = sum_all
    tcapex["All"] = sum_all_t

    summary_results = concatenate_dataframes(
        summary_results, ecapex, run=1, unit="$US", metric="Energy-CAPEX"
    )
    summary_results = concatenate_dataframes(summary_results, tcapex, run=1, unit="$US", metric="Total-CAPEX")

    ## FOM
    fom = {}
    sum_all = 0.0
    fom["Thermal"] = safe_pyomo_value(model.thermal.fixed_om_cost_expr)
    fom["Solar PV"] = safe_pyomo_value(model.pv.fixed_om_cost_expr)
    fom["Wind"] = safe_pyomo_value(model.wind.fixed_om_cost_expr)

    for tech in storage_tech_list:
        fom[tech] = safe_pyomo_value(
            MW_TO_KW
            * model.storage.data["CostRatio", tech]
            * model.storage.data["FOM", tech]
            * model.storage.Pcha[tech]
            + MW_TO_KW
            * (1 - model.storage.data["CostRatio", tech])
            * model.storage.data["FOM", tech]
            * model.storage.Pdis[tech]
        )
        sum_all += fom[tech]

    fom["All"] = fom["Thermal"] + fom["Solar PV"] + fom["Wind"] + sum_all

    summary_results = concatenate_dataframes(summary_results, fom, run=1, unit="$US", metric="FOM")

    ## VOM
    vom = {}
    sum_all = 0.0
    vom["Thermal"] = safe_pyomo_value(model.thermal.total_vom_cost_expr)

    for tech in storage_tech_list:
        vom[tech] = safe_pyomo_value(
            model.storage.data["VOM", tech] * sum(model.storage.PD[h, tech] for h in model.h)
        )
        sum_all += vom[tech]
    vom["All"] = vom["Thermal"] + sum_all

    summary_results = concatenate_dataframes(summary_results, vom, run=1, unit="$US", metric="VOM")

    fuel_cost = {}
    fuel_cost["Thermal"] = safe_pyomo_value(model.thermal.total_fuel_cost_expr)
    summary_results = concatenate_dataframes(
        summary_results, fuel_cost, run=1, unit="$US", metric="Fuel-Cost"
    )

    ## OPEX
    opex = {}
    sum_all = 0.0
    opex["Thermal"] = fom["Thermal"] + vom["Thermal"]
    opex["Solar PV"] = fom["Solar PV"]
    opex["Wind"] = fom["Wind"]

    for tech in storage_tech_list:
        opex[tech] = fom[tech] + vom[tech]
        sum_all += opex[tech]
    opex["All"] = opex["Thermal"] + opex["Solar PV"] + opex["Wind"] + sum_all

    summary_results = concatenate_dataframes(summary_results, opex, run=1, unit="$US", metric="OPEX")

    # IMPORTS/EXPORTS COSTS
    cost_revenue = {}
    cost_revenue["Imports Cost"] = safe_pyomo_value(model.imports.total_cost_expr)
    summary_results = concatenate_dataframes(summary_results, cost_revenue, run=1, unit="$US", metric="Cost")
    cost_revenue = {}
    cost_revenue["Exports Revenue"] = safe_pyomo_value(model.exports.total_cost_expr)
    summary_results = concatenate_dataframes(
        summary_results, cost_revenue, run=1, unit="$US", metric="Revenue"
    )

    ## Equivalent number of cycles
    cyc = {}
    for tech in storage_tech_list:
        cyc[tech] = safe_pyomo_value(gen[tech] / (model.storage.Ecap[tech] + 1e-15))

    summary_results = concatenate_dataframes(
        summary_results, cyc, run=1, unit="-", metric="Equivalent number of cycles"
    )

    ## VRE Curtailment
    pv_curtailment = (
        safe_pyomo_value(model.pv.total_curtailment) if hasattr(model.pv, "total_curtailment") else 0.0
    )
    wind_curtailment = (
        safe_pyomo_value(model.wind.total_curtailment) if hasattr(model.wind, "total_curtailment") else 0.0
    )
    pv_generation = (
        safe_pyomo_value(model.pv.total_generation) if hasattr(model.pv, "total_generation") else 0.0
    )
    wind_generation = (
        safe_pyomo_value(model.wind.total_generation) if hasattr(model.wind, "total_generation") else 0.0
    )

    total_vre_curtailment_mwh = pv_curtailment + wind_curtailment
    total_vre_availability = pv_generation + wind_generation + pv_curtailment + wind_curtailment
    total_vre_curtailment_pct = (
        (total_vre_curtailment_mwh / total_vre_availability * 100) if total_vre_availability > 0 else 0.0
    )

    vre_curt_mwh = {"Solar PV": pv_curtailment, "Wind": wind_curtailment, "All": total_vre_curtailment_mwh}
    summary_results = concatenate_dataframes(
        summary_results, vre_curt_mwh, run=1, unit="MWh", metric="Total VRE curtailment"
    )

    vre_curt_pct = {"All": total_vre_curtailment_pct}
    summary_results = concatenate_dataframes(
        summary_results, vre_curt_pct, run=1, unit="%", metric="VRE curtailment percentage"
    )

    logging.info("Exporting csv files containing SDOM results...")
    # Save generation results to CSV
    logging.debug("-- Saving generation results to CSV...")
    if gen_results["Hour"]:
        with open(output_dir + f"OutputGeneration_{case}.csv", mode="w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=gen_results.keys())
            writer.writeheader()
            writer.writerows(
                [dict(zip(gen_results, t, strict=False)) for t in zip(*gen_results.values(), strict=False)]
            )

    # Save storage results to CSV
    logging.debug("-- Saving storage results to CSV...")
    if storage_results["Hour"]:
        with open(output_dir + f"OutputStorage_{case}.csv", mode="w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=storage_results.keys())
            writer.writeheader()
            writer.writerows(
                [
                    dict(zip(storage_results, t, strict=False))
                    for t in zip(*storage_results.values(), strict=False)
                ]
            )

    # Save summary results to CSV
    logging.debug("-- Saving summary results to CSV...")
    if len(summary_results) > 0:
        summary_results.to_csv(output_dir + f"OutputSummary_{case}.csv", index=False)

    logging.debug("-- Saving disaggregated thermal generation results to CSV...")
    thermal_frame = _collect_thermal_generation_dataframe(model)
    thermal_frame.insert(1, "Area", "copperplate")
    if not thermal_frame.empty:
        thermal_frame.to_csv(os.path.join(output_dir, f"OutputThermalGeneration_{case}.csv"), index=False)
