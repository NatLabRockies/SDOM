"""Collect results from solved single-area copperplate models."""


import logging

import numpy as np
import pandas as pd

from ..common.utilities import safe_pyomo_value
from ..constants import MW_TO_KW
from ._values import _collect_curtailment_costs, _value_or_nan
from .collect_individual_host_results import _collect_thermal_generation_dataframe
from .containers import _RESULT_ATTRIBUTE_UNITS, OptimizationResults
from .hydro import _collect_hydro_budget_energy
from .summary import _append_hydro_curtailment_summary, _build_summary_dataframe


def _collect_results_copperplate(model, solver_result, *, case_name: str = "run") -> OptimizationResults:
    """Collect results from a solved single-area copper-plate model.

    This is the historical body of :func:`collect_results_from_model`
    extracted into a private helper for the legacy path. Existing costs
    remain unchanged; ``curtailment_cost`` adds signed Solar PV, Wind, and
    Hydro contributions in modeled-horizon USD, already included in total cost.

    Parameters mirror :func:`collect_results_from_model`.
    """
    logging.info("Collecting SDOM results...")

    results = OptimizationResults()
    results.attribute_units = _RESULT_ATTRIBUTE_UNITS.copy()

    # Extract solver information
    results.termination_condition = str(solver_result.solver.termination_condition)
    results.solver_status = str(solver_result.solver.status)

    # Extract problem info
    if solver_result.problem:
        problem = solver_result.problem[0]
        # Helper to extract value from Pyomo ScalarData objects
        def get_value(val):
            if hasattr(val, 'value'):
                return val.value
            return val

        results.problem_info = {
            "Number of constraints": get_value(problem.get("Number of constraints", 0)),
            "Number of variables": get_value(problem.get("Number of variables", 0)),
            "Number of binary variables": get_value(problem.get("Number of binary variables", 0)),
            "Number of objectives": get_value(problem.get("Number of objectives", 0)),
            "Number of nonzeros": get_value(problem.get("Number of nonzeros", 0)),
        }

    # Total cost
    results.total_cost = safe_pyomo_value(model.Obj.expr)
    results.gen_mix_target = float(model.GenMix_Target.value)

    # ----------------------------------------------------------------------------------
    # Collect capacity results
    # ----------------------------------------------------------------------------------
    logging.debug("Collecting capacity results...")

    # Generation capacities
    results.capacity = {
        "Thermal": safe_pyomo_value(model.thermal.total_installed_capacity),
        "Solar PV": safe_pyomo_value(model.pv.total_installed_capacity),
        "Wind": safe_pyomo_value(model.wind.total_installed_capacity),
    }
    results.capacity["All"] = (
        results.capacity["Thermal"] + results.capacity["Solar PV"] + results.capacity["Wind"]
    )

    # Storage capacities
    storage_tech_list = list(model.storage.j)

    charge_cap = {}
    discharge_cap = {}
    energy_cap = {}

    for tech in storage_tech_list:
        charge_cap[tech] = safe_pyomo_value(model.storage.Pcha[tech])
        discharge_cap[tech] = safe_pyomo_value(model.storage.Pdis[tech])
        energy_cap[tech] = safe_pyomo_value(model.storage.Ecap[tech])

    charge_cap["All"] = sum(charge_cap[t] for t in storage_tech_list)
    discharge_cap["All"] = sum(discharge_cap[t] for t in storage_tech_list)
    energy_cap["All"] = sum(energy_cap[t] for t in storage_tech_list)

    results.storage_capacity = {
        "charge": charge_cap,
        "discharge": discharge_cap,
        "energy": energy_cap,
    }

    # ----------------------------------------------------------------------------------
    # Collect generation totals
    # ----------------------------------------------------------------------------------
    logging.debug("Collecting generation totals...")

    hydro_generation = np.fromiter(
        (_value_or_nan(model.hydro.generation[hour]) for hour in model.h),
        dtype=float,
        count=len(model.h),
    )
    hydro_budget_energy = _collect_hydro_budget_energy(model, hydro_generation)
    results.generation_totals = {
        "Thermal": safe_pyomo_value(model.thermal.total_generation),
        "Solar PV": safe_pyomo_value(model.pv.total_generation),
        "Wind": safe_pyomo_value(model.wind.total_generation),
        "Other renewables": safe_pyomo_value(sum(model.other_renewables.ts_parameter[h] for h in model.h)) * safe_pyomo_value(model.other_renewables.alpha),
        "Hydro": float(hydro_generation.sum()) * safe_pyomo_value(model.hydro.alpha),
        "Nuclear": safe_pyomo_value(sum(model.nuclear.ts_parameter[h] for h in model.h)) * safe_pyomo_value(model.nuclear.alpha),
    }

    # Storage discharge totals
    storage_discharge_total = 0.0
    for tech in storage_tech_list:
        tech_discharge = safe_pyomo_value(sum(model.storage.PD[h, tech] for h in model.h))
        results.generation_totals[tech] = tech_discharge
        storage_discharge_total += tech_discharge

    results.generation_totals["All"] = (
        results.generation_totals["Thermal"]
        + results.generation_totals["Solar PV"]
        + results.generation_totals["Wind"]
        + results.generation_totals["Other renewables"]
        + results.generation_totals["Hydro"]
        + results.generation_totals["Nuclear"]
        + storage_discharge_total
    )

    # ----------------------------------------------------------------------------------
    # Collect cost breakdown
    # ----------------------------------------------------------------------------------
    logging.debug("Collecting cost breakdown...")

    # CAPEX
    capex = {
        "Solar PV": safe_pyomo_value(model.pv.capex_cost_expr),
        "Wind": safe_pyomo_value(model.wind.capex_cost_expr),
        "Thermal": safe_pyomo_value(model.thermal.capex_cost_expr),
    }
    capex["All"] = capex["Solar PV"] + capex["Wind"] + capex["Thermal"]

    # Storage CAPEX
    power_capex = {}
    energy_capex = {}
    for tech in storage_tech_list:
        power_capex[tech] = safe_pyomo_value(model.storage.power_capex_cost_expr[tech])
        energy_capex[tech] = safe_pyomo_value(model.storage.energy_capex_cost_expr[tech])

    power_capex["All"] = sum(power_capex[t] for t in storage_tech_list)
    energy_capex["All"] = sum(energy_capex[t] for t in storage_tech_list)

    # FOM
    fom = {
        "Thermal": safe_pyomo_value(model.thermal.fixed_om_cost_expr),
        "Solar PV": safe_pyomo_value(model.pv.fixed_om_cost_expr),
        "Wind": safe_pyomo_value(model.wind.fixed_om_cost_expr),
    }
    fom_storage_total = 0.0
    for tech in storage_tech_list:
        fom[tech] = safe_pyomo_value(
            MW_TO_KW * model.storage.data["CostRatio", tech] * model.storage.data["FOM", tech] * model.storage.Pcha[tech]
            + MW_TO_KW * (1 - model.storage.data["CostRatio", tech]) * model.storage.data["FOM", tech] * model.storage.Pdis[tech]
        )
        fom_storage_total += fom[tech]
    fom["All"] = fom["Thermal"] + fom["Solar PV"] + fom["Wind"] + fom_storage_total

    # VOM
    vom = {
        "Thermal": safe_pyomo_value(model.thermal.total_vom_cost_expr),
    }
    vom_storage_total = 0.0
    for tech in storage_tech_list:
        vom[tech] = safe_pyomo_value(model.storage.data["VOM", tech] * sum(model.storage.PD[h, tech] for h in model.h))
        vom_storage_total += vom[tech]
    vom["All"] = vom["Thermal"] + vom_storage_total

    # Fuel cost
    fuel_cost = {
        "Thermal": safe_pyomo_value(model.thermal.total_fuel_cost_expr),
    }

    # Imports/Exports costs
    imports_cost = safe_pyomo_value(model.imports.total_cost_expr)
    exports_revenue = safe_pyomo_value(model.exports.total_cost_expr)

    results.cost_breakdown = {
        "capex": capex,
        "power_capex": power_capex,
        "energy_capex": energy_capex,
        "fom": fom,
        "vom": vom,
        "fuel_cost": fuel_cost,
        "imports_cost": imports_cost,
        "exports_revenue": exports_revenue,
        "curtailment_cost": _collect_curtailment_costs(model),
    }

    # ----------------------------------------------------------------------------------
    # Build generation DataFrame
    # ----------------------------------------------------------------------------------
    logging.debug("Building generation DataFrame...")

    gen_data = {
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

    for h in model.h:
        solar_gen = safe_pyomo_value(model.pv.generation[h])
        solar_curt = safe_pyomo_value(model.pv.curtailment[h])
        wind_gen = safe_pyomo_value(model.wind.generation[h])
        wind_curt = safe_pyomo_value(model.wind.curtailment[h])
        thermal_gen = sum(safe_pyomo_value(model.thermal.generation[h, bu]) for bu in model.thermal.plants_set)
        hydro = safe_pyomo_value(model.hydro.generation[h])
        nuclear = safe_pyomo_value(model.nuclear.alpha * model.nuclear.ts_parameter[h]) if hasattr(model.nuclear, "alpha") else 0
        other_renewables = safe_pyomo_value(model.other_renewables.alpha * model.other_renewables.ts_parameter[h]) if hasattr(model.other_renewables, "alpha") else 0
        imports = safe_pyomo_value(model.imports.variable[h]) if hasattr(model.imports, "variable") else 0
        exports = safe_pyomo_value(model.exports.variable[h]) if hasattr(model.exports, "variable") else 0
        load = safe_pyomo_value(model.demand.ts_parameter[h]) if hasattr(model.demand, "ts_parameter") else 0
        net_load = safe_pyomo_value(model.net_load[h]) if hasattr(model, "net_load") else 0
        power_to_storage = sum(safe_pyomo_value(model.storage.PC[h, j]) or 0 for j in model.storage.j) - sum(safe_pyomo_value(model.storage.PD[h, j]) or 0 for j in model.storage.j)

        if None not in [solar_gen, solar_curt, wind_gen, wind_curt, thermal_gen, hydro, imports, exports, load]:
            gen_data["Scenario"].append(case_name)
            gen_data["Hour"].append(h)
            gen_data["Solar PV Generation (MW)"].append(solar_gen)
            gen_data["Solar PV Curtailment (MW)"].append(solar_curt)
            gen_data["Wind Generation (MW)"].append(wind_gen)
            gen_data["Wind Curtailment (MW)"].append(wind_curt)
            gen_data["All Thermal Generation (MW)"].append(thermal_gen)
            gen_data["Hydro Generation (MW)"].append(hydro)
            gen_data["Nuclear Generation (MW)"].append(nuclear)
            gen_data["Other Renewables Generation (MW)"].append(other_renewables)
            gen_data["Imports (MW)"].append(imports)
            gen_data["Storage Charge/Discharge (MW)"].append(power_to_storage)
            gen_data["Exports (MW)"].append(exports)
            gen_data["Load (MW)"].append(load)
            gen_data["Net Load (MW)"].append(net_load)

    results.generation_df = pd.DataFrame(gen_data)

    # ----------------------------------------------------------------------------------
    # Build storage DataFrame
    # ----------------------------------------------------------------------------------
    logging.debug("Building storage DataFrame...")

    storage_data = {
        "Hour": [],
        "Technology": [],
        "Charging power (MW)": [],
        "Discharging power (MW)": [],
        "State of charge (MWh)": [],
    }

    for h in model.h:
        for j in model.storage.j:
            charge_power = safe_pyomo_value(model.storage.PC[h, j])
            discharge_power = safe_pyomo_value(model.storage.PD[h, j])
            soc = safe_pyomo_value(model.storage.SOC[h, j])
            if None not in [charge_power, discharge_power, soc]:
                storage_data["Hour"].append(h)
                storage_data["Technology"].append(j)
                storage_data["Charging power (MW)"].append(charge_power)
                storage_data["Discharging power (MW)"].append(discharge_power)
                storage_data["State of charge (MWh)"].append(soc)

    results.storage_df = pd.DataFrame(storage_data)

    # ----------------------------------------------------------------------------------
    # Build thermal generation DataFrame (disaggregated)
    # ----------------------------------------------------------------------------------
    logging.debug("Building thermal generation DataFrame...")

    results.thermal_generation_df = _collect_thermal_generation_dataframe(model)
    results.thermal_generation_df.insert(1, "Area", "copperplate")

    # ----------------------------------------------------------------------------------
    # Build installed power plants DataFrame
    # ----------------------------------------------------------------------------------
    logging.debug("Building installed power plants DataFrame...")

    installed_plants_data = {
        "Plant ID": [],
        "Technology": [],
        "Installed Capacity (MW)": [],
        "Max Capacity (MW)": [],
        "Capacity Fraction": [],
    }

    # Solar PV plants
    for plant in model.pv.plants_set:
        installed_cap = safe_pyomo_value(model.pv.plant_installed_capacity[plant])
        max_cap = safe_pyomo_value(model.pv.max_capacity[plant])
        cap_fraction = safe_pyomo_value(model.pv.capacity_fraction[plant])
        installed_plants_data["Plant ID"].append(str(plant))
        installed_plants_data["Technology"].append("Solar PV")
        installed_plants_data["Installed Capacity (MW)"].append(installed_cap)
        installed_plants_data["Max Capacity (MW)"].append(max_cap)
        installed_plants_data["Capacity Fraction"].append(cap_fraction)

    # Wind plants
    for plant in model.wind.plants_set:
        installed_cap = safe_pyomo_value(model.wind.plant_installed_capacity[plant])
        max_cap = safe_pyomo_value(model.wind.max_capacity[plant])
        cap_fraction = safe_pyomo_value(model.wind.capacity_fraction[plant])
        installed_plants_data["Plant ID"].append(str(plant))
        installed_plants_data["Technology"].append("Wind")
        installed_plants_data["Installed Capacity (MW)"].append(installed_cap)
        installed_plants_data["Max Capacity (MW)"].append(max_cap)
        installed_plants_data["Capacity Fraction"].append(cap_fraction)

    # Thermal plants
    for plant in model.thermal.plants_set:
        installed_cap = safe_pyomo_value(model.thermal.plant_installed_capacity[plant])
        max_cap = safe_pyomo_value(model.thermal.data["MaxCapacity", plant])
        # For thermal, capacity fraction is installed/max (there's no explicit fraction variable)
        cap_fraction = installed_cap / max_cap if max_cap > 0 else 0.0
        installed_plants_data["Plant ID"].append(str(plant))
        installed_plants_data["Technology"].append("Thermal")
        installed_plants_data["Installed Capacity (MW)"].append(installed_cap)
        installed_plants_data["Max Capacity (MW)"].append(max_cap)
        installed_plants_data["Capacity Fraction"].append(cap_fraction)

    results.installed_plants_df = pd.DataFrame(installed_plants_data)

    # ----------------------------------------------------------------------------------
    # Build summary DataFrame
    # ----------------------------------------------------------------------------------
    logging.debug("Building summary DataFrame...")

    results.summary_df = _append_hydro_curtailment_summary(
        _build_summary_dataframe(model, results, storage_tech_list), hydro_budget_energy
    )

    return results
