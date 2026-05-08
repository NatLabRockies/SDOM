"""Module for SDOM optimization results data structures and utilities."""

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from pyomo.environ import sqrt, value as pyo_value

from .common.utilities import safe_pyomo_value
from .constants import MW_TO_KW


@dataclass
class OptimizationResults:
    """Data class containing all optimization results from SDOM.

    This class stores the complete results from an SDOM optimization run,
    organized into DataFrames for different result categories (generation,
    storage, summary) and provides convenient accessors for specific metrics.

    Attributes
    ----------
    termination_condition : str
        The solver termination condition (e.g., 'optimal', 'infeasible').
    solver_status : str
        The solver status (e.g., 'ok', 'warning').
    total_cost : float
        The total objective value (cost) from the optimization.
    gen_mix_target : float
        The generation mix target value used in this run.
    generation_df : pd.DataFrame
        Hourly generation dispatch results for all technologies.
    storage_df : pd.DataFrame
        Hourly storage operation results (charge, discharge, SOC).
    thermal_generation_df : pd.DataFrame
        Disaggregated hourly thermal generation by plant.
    installed_plants_df : pd.DataFrame
        Installed capacity for each individual power plant (solar, wind, thermal).
    summary_df : pd.DataFrame
        Summary metrics including capacities, costs, and totals.
    problem_info : dict
        Solver problem information (constraints, variables, etc.).
    capacity : dict
        Installed capacity by technology.
    storage_capacity : dict
        Storage capacity details (charge, discharge, energy).
    generation_totals : dict
        Total generation by technology.
    cost_breakdown : dict
        Detailed cost breakdown (CAPEX, OPEX, FOM, VOM).
    """

    # Solver information
    termination_condition: str = ""
    solver_status: str = ""

    # Main objective
    total_cost: float = 0.0
    gen_mix_target: float = 0.0

    # DataFrames for CSV export
    generation_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    storage_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    thermal_generation_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    installed_plants_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    summary_df: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Problem info from solver
    problem_info: dict = field(default_factory=dict)

    # Capacity results
    capacity: dict = field(default_factory=dict)
    storage_capacity: dict = field(default_factory=dict)

    # Generation totals
    generation_totals: dict = field(default_factory=dict)

    # Cost breakdown
    cost_breakdown: dict = field(default_factory=dict)

    # ----------------------------------------------------------------------------------
    # Zonal-aware optional fields (PRD §6.1).
    #
    # These fields are populated only when the solved model is a zonal
    # ``AreaTransportationModelNetwork`` model (detected by the presence of
    # ``model.A``/``model.area``). On the legacy copper-plate path they keep
    # their default empty values so existing code paths are unaffected.
    # ----------------------------------------------------------------------------------
    is_zonal: bool = False
    areas: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    area_capacity: dict = field(default_factory=dict)
    area_storage_capacity: dict = field(default_factory=dict)
    area_generation_totals: dict = field(default_factory=dict)
    area_cost_breakdown: dict = field(default_factory=dict)
    area_generation_df: dict = field(default_factory=dict)
    area_storage_df: dict = field(default_factory=dict)
    area_thermal_generation_df: dict = field(default_factory=dict)
    area_installed_plants_df: dict = field(default_factory=dict)
    area_summary_df: dict = field(default_factory=dict)
    interregional_exchanges_df: pd.DataFrame = field(default_factory=pd.DataFrame)

    # ----------------------------------------------------------------------------------
    # Convenience properties for backward compatibility and easy access
    # ----------------------------------------------------------------------------------

    @property
    def is_optimal(self) -> bool:
        """Check if the solution is optimal."""
        return self.termination_condition == "optimal"

    # Capacity accessors
    @property
    def total_cap_thermal(self) -> float:
        """Total installed thermal capacity (MW)."""
        return self.capacity.get("Thermal", 0.0)

    @property
    def total_cap_pv(self) -> float:
        """Total installed solar PV capacity (MW)."""
        return self.capacity.get("Solar PV", 0.0)

    @property
    def total_cap_wind(self) -> float:
        """Total installed wind capacity (MW)."""
        return self.capacity.get("Wind", 0.0)

    @property
    def total_cap_storage_charge(self) -> dict:
        """Storage charging power capacity by technology (MW)."""
        return self.storage_capacity.get("charge", {})

    @property
    def total_cap_storage_discharge(self) -> dict:
        """Storage discharging power capacity by technology (MW)."""
        return self.storage_capacity.get("discharge", {})

    @property
    def total_cap_storage_energy(self) -> dict:
        """Storage energy capacity by technology (MWh)."""
        return self.storage_capacity.get("energy", {})

    # Generation accessors
    @property
    def total_gen_pv(self) -> float:
        """Total solar PV generation (MWh)."""
        return self.generation_totals.get("Solar PV", 0.0)

    @property
    def total_gen_wind(self) -> float:
        """Total wind generation (MWh)."""
        return self.generation_totals.get("Wind", 0.0)

    @property
    def total_gen_thermal(self) -> float:
        """Total thermal generation (MWh)."""
        return self.generation_totals.get("Thermal", 0.0)

    # ----------------------------------------------------------------------------------
    # DataFrame accessors
    # ----------------------------------------------------------------------------------

    def get_generation_dataframe(self) -> pd.DataFrame:
        """Get the hourly generation dispatch DataFrame.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: Scenario, Hour, Solar PV Generation (MW),
            Solar PV Curtailment (MW), Wind Generation (MW), Wind Curtailment (MW),
            All Thermal Generation (MW), Hydro Generation (MW), Nuclear Generation (MW),
            Other Renewables Generation (MW), Imports (MW), Storage Charge/Discharge (MW),
            Exports (MW), Load (MW).
        """
        return self.generation_df.copy()

    def get_storage_dataframe(self) -> pd.DataFrame:
        """Get the hourly storage operation DataFrame.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: Hour, Technology, Charging power (MW),
            Discharging power (MW), State of charge (MWh).
        """
        return self.storage_df.copy()

    def get_thermal_generation_dataframe(self) -> pd.DataFrame:
        """Get the disaggregated hourly thermal generation DataFrame.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: Hour, and one column per thermal plant.
        """
        return self.thermal_generation_df.copy()

    def get_summary_dataframe(self) -> pd.DataFrame:
        """Get the summary metrics DataFrame.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: Metric, Technology, Run, Optimal Value, Unit.
        """
        return self.summary_df.copy()

    def get_installed_plants_dataframe(self) -> pd.DataFrame:
        """Get the installed power plants capacity DataFrame.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: Plant ID, Technology, Installed Capacity (MW),
            Max Capacity (MW), Capacity Fraction.
        """
        return self.installed_plants_df.copy()

    # ----------------------------------------------------------------------------------
    # Problem info accessors
    # ----------------------------------------------------------------------------------

    def get_problem_info(self) -> dict:
        """Get solver problem information.

        Returns
        -------
        dict
            Dictionary with keys: Number of constraints, Number of variables,
            Number of binary variables, Number of objectives, Number of nonzeros.
        """
        return self.problem_info.copy()


def collect_results_from_model(model, solver_result, case_name: str = "run") -> OptimizationResults:
    """Collect all optimization results from a solved Pyomo model.

    Dispatches to the legacy single-area collector or the zonal collector
    based on whether ``model`` exposes a top-level area set ``model.A`` and
    a per-area ``Block`` ``model.area`` (the convention established by
    :func:`sdom.optimization_main._initialize_model_zonal`).

    On the **legacy** path the returned :class:`OptimizationResults` matches
    today's schema bit-identically (locked by
    ``tests/test_zonal_legacy_regression.py``). On the **zonal** path the
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

    Notes
    -----
    Top-level ``summary_df`` is **left empty under the zonal path**; per-area
    summaries are populated in :attr:`OptimizationResults.area_summary_df`
    instead. A system-level zonal summary is a follow-up. CSV emission of
    ``interregional_exchanges_df`` is also a follow-up (commit #11).
    """
    is_zonal = hasattr(model, "A") and hasattr(model, "area")
    if is_zonal:
        return _collect_results_zonal(model, solver_result, case_name=case_name)
    return _collect_results_legacy(model, solver_result, case_name=case_name)


def _collect_results_legacy(model, solver_result, *, case_name: str = "run") -> OptimizationResults:
    """Collect results from a solved single-area copper-plate model.

    This is the historical body of :func:`collect_results_from_model`
    extracted verbatim into a private helper so the new dispatcher can route
    here unchanged for the legacy path. **Do not modify this body without
    updating ``tests/test_zonal_legacy_regression.py``** — it locks the
    objective and per-technology values produced by this function.

    Parameters mirror :func:`collect_results_from_model`.
    """
    logging.info("Collecting SDOM results...")

    results = OptimizationResults()

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

    results.generation_totals = {
        "Thermal": safe_pyomo_value(model.thermal.total_generation),
        "Solar PV": safe_pyomo_value(model.pv.total_generation),
        "Wind": safe_pyomo_value(model.wind.total_generation),
        "Other renewables": safe_pyomo_value(sum(model.other_renewables.ts_parameter[h] for h in model.h)) * safe_pyomo_value(model.other_renewables.alpha),
        "Hydro": safe_pyomo_value(sum(model.hydro.generation[h] for h in model.h)) * safe_pyomo_value(model.hydro.alpha),
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

    if len(model.thermal.plants_set) > 1:
        thermal_data = {"Hour": []}
        for plant in model.thermal.plants_set:
            thermal_data[str(plant)] = []

        for h in model.h:
            thermal_data["Hour"].append(h)
            for plant in model.thermal.plants_set:
                thermal_data[str(plant)].append(safe_pyomo_value(model.thermal.generation[h, plant]))

        results.thermal_generation_df = pd.DataFrame(thermal_data)

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

    results.summary_df = _build_summary_dataframe(model, results, storage_tech_list)

    return results


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
    from .common.utilities import concatenate_dataframes

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


# ---------------------------------------------------------------------------------
# Zonal (AreaTransportationModelNetwork) results collection
# ---------------------------------------------------------------------------------
def _collect_host_metrics(host, hours, *, case_name: str = "run") -> dict:
    """Collect dispatch and capacity metrics from a single host block.

    Mirrors the legacy collection logic in
    :func:`_collect_results_legacy` but operates on an arbitrary ``host``
    (either the top-level model or an area sub-block ``model.area[a]``).
    Imports / exports terms are guarded by ``hasattr`` so this helper is
    safe to call on a zonal area block where the imports / exports
    variables and cost expressions are intentionally not added.

    Parameters
    ----------
    host : pyomo.environ.Block or pyomo.environ.ConcreteModel
        The block exposing ``pv``, ``wind``, ``thermal``, ``storage``,
        ``hydro``, ``demand``, ``nuclear``, ``other_renewables`` (and,
        on legacy hosts, ``imports``/``exports``) sub-blocks.
    hours : iterable of int
        Hours to iterate over (e.g. ``list(model.h)`` or ``list(host.h)``).
    case_name : str, optional
        Scenario label for the per-row ``"Scenario"`` column of the
        generation DataFrame. Defaults to ``"run"``.

    Returns
    -------
    dict
        Bundle with keys:

        - ``capacity`` : dict by technology (Thermal, Solar PV, Wind, All).
        - ``storage_capacity`` : dict with ``charge``/``discharge``/``energy``.
        - ``storage_tech_list`` : list of storage tech identifiers.
        - ``generation_totals`` : dict by technology (incl. each storage tech).
        - ``cost_breakdown`` : dict (``capex``, ``power_capex``, ``energy_capex``,
          ``fom``, ``vom``, ``fuel_cost``, ``imports_cost``, ``exports_revenue``).
        - ``generation_df``, ``storage_df``, ``thermal_generation_df``,
          ``installed_plants_df`` : pandas DataFrames with the same schema
          as the legacy top-level frames.
    """
    storage_tech_list = list(host.storage.j)

    # Capacities -----------------------------------------------------------
    capacity = {
        "Thermal": safe_pyomo_value(host.thermal.total_installed_capacity),
        "Solar PV": safe_pyomo_value(host.pv.total_installed_capacity),
        "Wind": safe_pyomo_value(host.wind.total_installed_capacity),
    }
    capacity["All"] = capacity["Thermal"] + capacity["Solar PV"] + capacity["Wind"]

    charge_cap = {t: safe_pyomo_value(host.storage.Pcha[t]) for t in storage_tech_list}
    discharge_cap = {t: safe_pyomo_value(host.storage.Pdis[t]) for t in storage_tech_list}
    energy_cap = {t: safe_pyomo_value(host.storage.Ecap[t]) for t in storage_tech_list}
    charge_cap["All"] = sum(charge_cap[t] for t in storage_tech_list)
    discharge_cap["All"] = sum(discharge_cap[t] for t in storage_tech_list)
    energy_cap["All"] = sum(energy_cap[t] for t in storage_tech_list)
    storage_capacity = {
        "charge": charge_cap,
        "discharge": discharge_cap,
        "energy": energy_cap,
    }

    # Generation totals ----------------------------------------------------
    generation_totals = {
        "Thermal": safe_pyomo_value(host.thermal.total_generation),
        "Solar PV": safe_pyomo_value(host.pv.total_generation),
        "Wind": safe_pyomo_value(host.wind.total_generation),
        "Other renewables": safe_pyomo_value(
            sum(host.other_renewables.ts_parameter[h] for h in hours)
        ) * safe_pyomo_value(host.other_renewables.alpha),
        "Hydro": safe_pyomo_value(
            sum(host.hydro.generation[h] for h in hours)
        ) * safe_pyomo_value(host.hydro.alpha),
        "Nuclear": safe_pyomo_value(
            sum(host.nuclear.ts_parameter[h] for h in hours)
        ) * safe_pyomo_value(host.nuclear.alpha),
    }
    storage_discharge_total = 0.0
    for tech in storage_tech_list:
        tech_discharge = safe_pyomo_value(sum(host.storage.PD[h, tech] for h in hours))
        generation_totals[tech] = tech_discharge
        storage_discharge_total += tech_discharge
    generation_totals["All"] = (
        generation_totals["Thermal"]
        + generation_totals["Solar PV"]
        + generation_totals["Wind"]
        + generation_totals["Other renewables"]
        + generation_totals["Hydro"]
        + generation_totals["Nuclear"]
        + storage_discharge_total
    )

    # Cost breakdown -------------------------------------------------------
    capex = {
        "Solar PV": safe_pyomo_value(host.pv.capex_cost_expr),
        "Wind": safe_pyomo_value(host.wind.capex_cost_expr),
        "Thermal": safe_pyomo_value(host.thermal.capex_cost_expr),
    }
    capex["All"] = capex["Solar PV"] + capex["Wind"] + capex["Thermal"]

    power_capex = {
        t: safe_pyomo_value(host.storage.power_capex_cost_expr[t]) for t in storage_tech_list
    }
    energy_capex = {
        t: safe_pyomo_value(host.storage.energy_capex_cost_expr[t]) for t in storage_tech_list
    }
    power_capex["All"] = sum(power_capex[t] for t in storage_tech_list)
    energy_capex["All"] = sum(energy_capex[t] for t in storage_tech_list)

    fom = {
        "Thermal": safe_pyomo_value(host.thermal.fixed_om_cost_expr),
        "Solar PV": safe_pyomo_value(host.pv.fixed_om_cost_expr),
        "Wind": safe_pyomo_value(host.wind.fixed_om_cost_expr),
    }
    fom_storage_total = 0.0
    for tech in storage_tech_list:
        fom[tech] = safe_pyomo_value(
            MW_TO_KW * host.storage.data["CostRatio", tech] * host.storage.data["FOM", tech] * host.storage.Pcha[tech]
            + MW_TO_KW * (1 - host.storage.data["CostRatio", tech]) * host.storage.data["FOM", tech] * host.storage.Pdis[tech]
        )
        fom_storage_total += fom[tech]
    fom["All"] = fom["Thermal"] + fom["Solar PV"] + fom["Wind"] + fom_storage_total

    vom = {"Thermal": safe_pyomo_value(host.thermal.total_vom_cost_expr)}
    vom_storage_total = 0.0
    for tech in storage_tech_list:
        vom[tech] = safe_pyomo_value(
            host.storage.data["VOM", tech] * sum(host.storage.PD[h, tech] for h in hours)
        )
        vom_storage_total += vom[tech]
    vom["All"] = vom["Thermal"] + vom_storage_total

    fuel_cost = {"Thermal": safe_pyomo_value(host.thermal.total_fuel_cost_expr)}

    imports_cost = (
        safe_pyomo_value(host.imports.total_cost_expr)
        if hasattr(host, "imports") and hasattr(host.imports, "total_cost_expr")
        else 0.0
    )
    exports_revenue = (
        safe_pyomo_value(host.exports.total_cost_expr)
        if hasattr(host, "exports") and hasattr(host.exports, "total_cost_expr")
        else 0.0
    )

    cost_breakdown = {
        "capex": capex,
        "power_capex": power_capex,
        "energy_capex": energy_capex,
        "fom": fom,
        "vom": vom,
        "fuel_cost": fuel_cost,
        "imports_cost": imports_cost,
        "exports_revenue": exports_revenue,
    }

    # Generation DataFrame -------------------------------------------------
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
    for h in hours:
        solar_gen = safe_pyomo_value(host.pv.generation[h])
        solar_curt = safe_pyomo_value(host.pv.curtailment[h])
        wind_gen = safe_pyomo_value(host.wind.generation[h])
        wind_curt = safe_pyomo_value(host.wind.curtailment[h])
        thermal_gen = sum(safe_pyomo_value(host.thermal.generation[h, bu]) for bu in host.thermal.plants_set)
        hydro = safe_pyomo_value(host.hydro.generation[h])
        nuclear = safe_pyomo_value(host.nuclear.alpha * host.nuclear.ts_parameter[h]) if hasattr(host.nuclear, "alpha") else 0
        other_renewables = safe_pyomo_value(host.other_renewables.alpha * host.other_renewables.ts_parameter[h]) if hasattr(host.other_renewables, "alpha") else 0
        imports = safe_pyomo_value(host.imports.variable[h]) if hasattr(host, "imports") and hasattr(host.imports, "variable") else 0
        exports = safe_pyomo_value(host.exports.variable[h]) if hasattr(host, "exports") and hasattr(host.exports, "variable") else 0
        load = safe_pyomo_value(host.demand.ts_parameter[h]) if hasattr(host.demand, "ts_parameter") else 0
        net_load = safe_pyomo_value(host.net_load[h]) if hasattr(host, "net_load") else 0
        power_to_storage = sum(safe_pyomo_value(host.storage.PC[h, j]) or 0 for j in host.storage.j) - sum(safe_pyomo_value(host.storage.PD[h, j]) or 0 for j in host.storage.j)

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
    generation_df = pd.DataFrame(gen_data)

    # Storage DataFrame ----------------------------------------------------
    storage_data = {
        "Hour": [],
        "Technology": [],
        "Charging power (MW)": [],
        "Discharging power (MW)": [],
        "State of charge (MWh)": [],
    }
    for h in hours:
        for j in host.storage.j:
            charge_power = safe_pyomo_value(host.storage.PC[h, j])
            discharge_power = safe_pyomo_value(host.storage.PD[h, j])
            soc = safe_pyomo_value(host.storage.SOC[h, j])
            if None not in [charge_power, discharge_power, soc]:
                storage_data["Hour"].append(h)
                storage_data["Technology"].append(j)
                storage_data["Charging power (MW)"].append(charge_power)
                storage_data["Discharging power (MW)"].append(discharge_power)
                storage_data["State of charge (MWh)"].append(soc)
    storage_df = pd.DataFrame(storage_data)

    # Thermal generation DataFrame (disaggregated) -------------------------
    thermal_generation_df = pd.DataFrame()
    if len(host.thermal.plants_set) > 1:
        thermal_data = {"Hour": []}
        for plant in host.thermal.plants_set:
            thermal_data[str(plant)] = []
        for h in hours:
            thermal_data["Hour"].append(h)
            for plant in host.thermal.plants_set:
                thermal_data[str(plant)].append(safe_pyomo_value(host.thermal.generation[h, plant]))
        thermal_generation_df = pd.DataFrame(thermal_data)

    # Installed plants DataFrame ------------------------------------------
    installed_plants_data = {
        "Plant ID": [],
        "Technology": [],
        "Installed Capacity (MW)": [],
        "Max Capacity (MW)": [],
        "Capacity Fraction": [],
    }
    for plant in host.pv.plants_set:
        installed_cap = safe_pyomo_value(host.pv.plant_installed_capacity[plant])
        max_cap = safe_pyomo_value(host.pv.max_capacity[plant])
        cap_fraction = safe_pyomo_value(host.pv.capacity_fraction[plant])
        installed_plants_data["Plant ID"].append(str(plant))
        installed_plants_data["Technology"].append("Solar PV")
        installed_plants_data["Installed Capacity (MW)"].append(installed_cap)
        installed_plants_data["Max Capacity (MW)"].append(max_cap)
        installed_plants_data["Capacity Fraction"].append(cap_fraction)
    for plant in host.wind.plants_set:
        installed_cap = safe_pyomo_value(host.wind.plant_installed_capacity[plant])
        max_cap = safe_pyomo_value(host.wind.max_capacity[plant])
        cap_fraction = safe_pyomo_value(host.wind.capacity_fraction[plant])
        installed_plants_data["Plant ID"].append(str(plant))
        installed_plants_data["Technology"].append("Wind")
        installed_plants_data["Installed Capacity (MW)"].append(installed_cap)
        installed_plants_data["Max Capacity (MW)"].append(max_cap)
        installed_plants_data["Capacity Fraction"].append(cap_fraction)
    for plant in host.thermal.plants_set:
        installed_cap = safe_pyomo_value(host.thermal.plant_installed_capacity[plant])
        max_cap = safe_pyomo_value(host.thermal.data["MaxCapacity", plant])
        cap_fraction = installed_cap / max_cap if max_cap > 0 else 0.0
        installed_plants_data["Plant ID"].append(str(plant))
        installed_plants_data["Technology"].append("Thermal")
        installed_plants_data["Installed Capacity (MW)"].append(installed_cap)
        installed_plants_data["Max Capacity (MW)"].append(max_cap)
        installed_plants_data["Capacity Fraction"].append(cap_fraction)
    installed_plants_df = pd.DataFrame(installed_plants_data)

    return {
        "capacity": capacity,
        "storage_capacity": storage_capacity,
        "storage_tech_list": storage_tech_list,
        "generation_totals": generation_totals,
        "cost_breakdown": cost_breakdown,
        "generation_df": generation_df,
        "storage_df": storage_df,
        "thermal_generation_df": thermal_generation_df,
        "installed_plants_df": installed_plants_df,
    }


def _merge_dict_sum(target: dict, source: dict) -> None:
    """Sum scalar values from ``source`` into ``target`` in-place.

    Numeric values are added; nested dicts are merged recursively.
    Used to aggregate per-area capacity / cost / generation dicts into the
    system-level rollups under the zonal path.

    Parameters
    ----------
    target : dict
        Destination dict (mutated).
    source : dict
        Per-area dict whose values are added to ``target``.
    """
    for key, val in source.items():
        if isinstance(val, dict):
            sub = target.setdefault(key, {})
            _merge_dict_sum(sub, val)
        elif isinstance(val, (int, float)):
            target[key] = target.get(key, 0.0) + float(val)
        else:
            # Non-numeric (e.g. nested list) — overwrite if absent.
            target.setdefault(key, val)


def _build_interregional_exchanges_df(model) -> pd.DataFrame:
    """Build the per-line / per-hour interregional exchanges DataFrame.

    Implements PRD §2.4: one row per ``(line_id, hour)`` with signed flow,
    decomposed FT / TF flows, asymmetric capacities, and NaN-safe
    utilization ratios.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Solved zonal model with ``model.L``, ``model.h``, ``model.f``,
        ``model.line_from``, ``model.line_to``, ``model.LineCap_FT``,
        ``model.LineCap_TF``.

    Returns
    -------
    pandas.DataFrame
        Empty DataFrame if ``model.L`` is empty; otherwise a DataFrame
        with the schema specified in PRD §2.4.
    """
    columns = [
        "line_id",
        "from_area",
        "to_area",
        "hour",
        "flow_signed_MW",
        "flow_FT_MW",
        "flow_TF_MW",
        "cap_FT_MW",
        "cap_TF_MW",
        "utilization_FT",
        "utilization_TF",
    ]
    if not hasattr(model, "L") or len(model.L) == 0:
        return pd.DataFrame(columns=columns)

    rows = []
    for l in model.L:
        from_a = pyo_value(model.line_from[l])
        to_a = pyo_value(model.line_to[l])
        for h in model.h:
            f_signed = float(safe_pyomo_value(model.f[l, h]) or 0.0)
            cap_ft = float(pyo_value(model.LineCap_FT[l, h]))
            cap_tf = float(pyo_value(model.LineCap_TF[l, h]))
            f_ft = max(f_signed, 0.0)
            f_tf = max(-f_signed, 0.0)
            rows.append(
                {
                    "line_id": l,
                    "from_area": from_a,
                    "to_area": to_a,
                    "hour": h,
                    "flow_signed_MW": f_signed,
                    "flow_FT_MW": f_ft,
                    "flow_TF_MW": f_tf,
                    "cap_FT_MW": cap_ft,
                    "cap_TF_MW": cap_tf,
                }
            )
    df = pd.DataFrame(rows, columns=columns[:-2])
    df["utilization_FT"] = np.where(
        df["cap_FT_MW"].to_numpy() > 0,
        df["flow_FT_MW"].to_numpy() / np.where(
            df["cap_FT_MW"].to_numpy() > 0, df["cap_FT_MW"].to_numpy(), 1.0
        ),
        np.nan,
    )
    df["utilization_TF"] = np.where(
        df["cap_TF_MW"].to_numpy() > 0,
        df["flow_TF_MW"].to_numpy() / np.where(
            df["cap_TF_MW"].to_numpy() > 0, df["cap_TF_MW"].to_numpy(), 1.0
        ),
        np.nan,
    )
    return df[columns]


def _collect_results_zonal(model, solver_result, *, case_name: str = "run") -> OptimizationResults:
    """Collect zonal results from a solved ``AreaTransportationModelNetwork`` model.

    Builds per-area DataFrames and dicts via :func:`_collect_host_metrics`
    on each ``model.area[a]`` block, aggregates them into top-level frames
    with a leading ``Area`` column, sums the scalar dicts across areas for
    system-level rollups, and constructs the
    :attr:`OptimizationResults.interregional_exchanges_df` per PRD §2.4.

    Top-level :attr:`OptimizationResults.summary_df` is **left empty**: the
    legacy :func:`_build_summary_dataframe` is keyed off ``model.storage`` /
    ``model.demand`` / etc. which under the zonal path live on per-area
    sub-blocks. Per-area summaries are built and attached to
    :attr:`OptimizationResults.area_summary_df` instead. A system-level
    zonal summary is a follow-up.

    Parameters mirror :func:`collect_results_from_model`.
    """
    logging.info("Collecting SDOM zonal results...")

    results = OptimizationResults()
    results.is_zonal = True
    results.areas = list(model.A)
    if hasattr(model, "L"):
        results.lines = [
            {
                "line_id": l,
                "from_area": pyo_value(model.line_from[l]),
                "to_area": pyo_value(model.line_to[l]),
            }
            for l in model.L
        ]

    # Solver information ---------------------------------------------------
    results.termination_condition = str(solver_result.solver.termination_condition)
    results.solver_status = str(solver_result.solver.status)
    if solver_result.problem:
        problem = solver_result.problem[0]
        def _gv(val):
            return val.value if hasattr(val, "value") else val
        results.problem_info = {
            "Number of constraints": _gv(problem.get("Number of constraints", 0)),
            "Number of variables": _gv(problem.get("Number of variables", 0)),
            "Number of binary variables": _gv(problem.get("Number of binary variables", 0)),
            "Number of objectives": _gv(problem.get("Number of objectives", 0)),
            "Number of nonzeros": _gv(problem.get("Number of nonzeros", 0)),
        }

    # Top-level scalars ----------------------------------------------------
    results.total_cost = safe_pyomo_value(model.Obj.expr)
    results.gen_mix_target = float(model.GenMix_Target.value)

    # Hours come from the top-level model (mirrors per-area host.h).
    hours = list(model.h)

    # Per-area collection --------------------------------------------------
    gen_pieces = []
    storage_pieces = []
    thermal_pieces = []
    plants_pieces = []
    for a in results.areas:
        host = model.area[a]
        bundle = _collect_host_metrics(host, hours, case_name=case_name)

        results.area_capacity[a] = bundle["capacity"]
        results.area_storage_capacity[a] = bundle["storage_capacity"]
        results.area_generation_totals[a] = bundle["generation_totals"]
        results.area_cost_breakdown[a] = bundle["cost_breakdown"]

        gen_df_a = bundle["generation_df"].copy()
        if not gen_df_a.empty:
            gen_df_a.insert(0, "Area", a)
            gen_pieces.append(gen_df_a)
        results.area_generation_df[a] = bundle["generation_df"]

        storage_df_a = bundle["storage_df"].copy()
        if not storage_df_a.empty:
            insert_pos = list(storage_df_a.columns).index("Hour") + 1
            storage_df_a.insert(insert_pos, "Area", a)
            storage_pieces.append(storage_df_a)
        results.area_storage_df[a] = bundle["storage_df"]

        thermal_df_a = bundle["thermal_generation_df"].copy()
        if not thermal_df_a.empty:
            insert_pos = list(thermal_df_a.columns).index("Hour") + 1
            thermal_df_a.insert(insert_pos, "Area", a)
            thermal_pieces.append(thermal_df_a)
        results.area_thermal_generation_df[a] = bundle["thermal_generation_df"]

        plants_df_a = bundle["installed_plants_df"].copy()
        if not plants_df_a.empty:
            insert_pos = list(plants_df_a.columns).index("Plant ID") + 1
            plants_df_a.insert(insert_pos, "Area", a)
            plants_pieces.append(plants_df_a)
        results.area_installed_plants_df[a] = bundle["installed_plants_df"]

        # Per-area summary frame: reuse _build_summary_dataframe with the
        # area block as the host. The summary helper only touches
        # ``storage`` / ``demand`` / ``imports`` / ``exports`` / ``pv`` /
        # ``wind`` / ``h`` on the host, all of which exist on the area
        # block (imports/exports guarded by hasattr). ``total_cost`` for
        # the per-area summary is the sum of the area's cost components.
        per_area_results = OptimizationResults(
            total_cost=(
                bundle["cost_breakdown"]["capex"]["All"]
                + bundle["cost_breakdown"]["power_capex"]["All"]
                + bundle["cost_breakdown"]["energy_capex"]["All"]
                + bundle["cost_breakdown"]["fom"]["All"]
                + bundle["cost_breakdown"]["vom"]["All"]
                + bundle["cost_breakdown"]["fuel_cost"]["Thermal"]
                + bundle["cost_breakdown"]["imports_cost"]
                - bundle["cost_breakdown"]["exports_revenue"]
            ),
            capacity=bundle["capacity"],
            storage_capacity=bundle["storage_capacity"],
            generation_totals=bundle["generation_totals"],
            cost_breakdown=bundle["cost_breakdown"],
        )
        try:
            results.area_summary_df[a] = _build_summary_dataframe(
                host, per_area_results, bundle["storage_tech_list"]
            )
        except Exception as exc:  # pragma: no cover - defensive
            logging.warning(
                "Could not build per-area summary for area '%s': %s", a, exc
            )
            results.area_summary_df[a] = pd.DataFrame()

    # Top-level concatenated DataFrames ------------------------------------
    if gen_pieces:
        results.generation_df = pd.concat(gen_pieces, ignore_index=True)
    if storage_pieces:
        results.storage_df = pd.concat(storage_pieces, ignore_index=True)
    if thermal_pieces:
        results.thermal_generation_df = pd.concat(thermal_pieces, ignore_index=True)
    if plants_pieces:
        results.installed_plants_df = pd.concat(plants_pieces, ignore_index=True)

    # System-level scalar rollups (sum across areas) -----------------------
    capacity_sys: dict = {}
    storage_capacity_sys: dict = {}
    generation_totals_sys: dict = {}
    cost_breakdown_sys: dict = {}
    for a in results.areas:
        _merge_dict_sum(capacity_sys, results.area_capacity[a])
        _merge_dict_sum(storage_capacity_sys, results.area_storage_capacity[a])
        _merge_dict_sum(generation_totals_sys, results.area_generation_totals[a])
        _merge_dict_sum(cost_breakdown_sys, results.area_cost_breakdown[a])
    results.capacity = capacity_sys
    results.storage_capacity = storage_capacity_sys
    results.generation_totals = generation_totals_sys
    results.cost_breakdown = cost_breakdown_sys

    # Interregional exchanges (PRD §2.4) -----------------------------------
    results.interregional_exchanges_df = _build_interregional_exchanges_df(model)

    # Top-level summary intentionally left empty under the zonal path; see
    # the function docstring. CSV writers guard with ``if not df.empty``.
    logging.info(
        "Zonal results collected: %d areas, %d lines, summary_df left empty "
        "(see area_summary_df for per-area summaries).",
        len(results.areas),
        len(results.lines),
    )

    return results

