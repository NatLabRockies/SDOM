import logging
import pandas as pd
import os
import csv

from pyomo.environ import sqrt

from .common.utilities import safe_pyomo_value, check_file_exists, compare_lists, concatenate_dataframes, get_dict_string_void_list_from_keys_in_list
from .constants import (
    INPUT_CSV_NAMES,
    MW_TO_KW,
    VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP,
    VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP,
    VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP,
    DEFAULT_NETWORK_FORMULATION,
)

# Sentinel used to distinguish 'no default supplied' from 'default is None'.
_GET_FORMULATION_NO_DEFAULT = object()


def check_formulation( formulation:str, valid_formulations ):
    """Validate that a formulation string is in the list of valid formulations.
    
    Checks if the user-specified formulation (from formulations.csv) is valid for
    the component being configured. Raises an error with helpful message if invalid.
    
    Args:
        formulation (str): The formulation name specified by user (e.g.,
            'MonthlyBudgetFormulation', 'RunOfRiverFormulation').
        valid_formulations: Iterable (typically dict.keys()) containing all valid
            formulation names for the component.
    
    Returns:
        None
    
    Raises:
        ValueError: If formulation is not in valid_formulations, with a message
            listing all valid options.
    
    Notes:
        This function is called during data loading to validate formulation.csv entries.
    """
    
    if formulation not in valid_formulations:
        raise ValueError(f"Invalid formulation '{formulation}' selected by the user in file 'formulations.csv'. Valid options are: {valid_formulations}")
    return

def get_formulation(data: dict, component: str = 'hydro', *, default=_GET_FORMULATION_NO_DEFAULT):
    """Retrieve the selected formulation for a specific model component.

    Extracts the formulation name from the loaded formulations DataFrame for a
    given component (e.g., hydro, imports, exports, network). Used throughout
    model initialization to conditionally add constraints based on formulation.

    Parameters
    ----------
    data : dict
        Dictionary containing the 'formulations' DataFrame loaded from
        ``formulations.csv``.
    component : str, optional
        Component name to look up (case-insensitive). Examples: ``'hydro'``,
        ``'Imports'``, ``'Exports'``, ``'Network'``. Defaults to ``'hydro'``.
    default : str, optional
        Value returned (and logged at INFO level) when the requested component
        row is absent from ``formulations.csv``. If omitted, a missing row
        raises ``IndexError`` (preserves the legacy behaviour).

    Returns
    -------
    str
        The formulation name for the specified component.

    Notes
    -----
    - Performs case-insensitive matching on component name.
    - Returns the first matching formulation (expects unique component names).
    - The ``default`` keyword is keyword-only to keep the function's mandatory
      positional surface unchanged.
    """
    formulations = data["formulations"]
    matches = formulations.loc[
        formulations["Component"].str.lower() == component.lower()
    ]["Formulation"]
    if matches.empty:
        if default is _GET_FORMULATION_NO_DEFAULT:
            return matches.iloc[0]  # original IndexError surface
        logging.info(
            "Component '%s' not present in formulations.csv. Falling back to default '%s'.",
            component,
            default,
        )
        return default
    return matches.iloc[0]


def load_data( input_data_dir:str = '.\\Data\\' ):
    """Load all required SDOM input datasets from CSV files in the specified directory.
    
    Reads and validates all input CSV files needed for SDOM optimization including
    VRE data, fixed generation profiles, storage characteristics, thermal units,
    scalars, and formulation specifications. Performs data consistency checks and
    filters datasets based on completeness.
    
    Args:
        input_data_dir (str, optional): Path to directory containing input CSV files.
            Defaults to '.\\Data\\'. Should contain all required files defined in
            constants.INPUT_CSV_NAMES.
    
    Returns:
        dict: Dictionary containing loaded and processed data with keys:
            - 'formulations' (pd.DataFrame): Component formulation specifications
            - 'solar_plants', 'wind_plants' (list): Plant IDs for VRE technologies
            - 'cf_solar', 'cf_wind' (pd.DataFrame): Hourly capacity factors
            - 'cap_solar', 'cap_wind' (pd.DataFrame): Plant CAPEX and capacity data
            - 'load_data' (pd.DataFrame): Hourly electricity demand
            - 'nuclear_data' (pd.DataFrame): Hourly nuclear generation
            - 'large_hydro_data' (pd.DataFrame): Hourly hydropower generation/availability
            - 'large_hydro_max', 'large_hydro_min' (pd.DataFrame): Hydro bounds
              (if budget formulation)
            - 'other_renewables_data' (pd.DataFrame): Hourly other renewable generation
            - 'storage_data' (pd.DataFrame): Storage technology characteristics
            - 'STORAGE_SET_J_TECHS', 'STORAGE_SET_B_TECHS' (list): Storage tech identifiers
            - 'thermal_data' (pd.DataFrame): Thermal balancing unit parameters
            - 'scalars' (pd.DataFrame): System-level scalar parameters
            - 'import_cap', 'export_cap', 'import_prices', 'export_prices' (pd.DataFrame):
              Trade data (if import/export formulation active)
            - 'complete_solar_data', 'complete_wind_data' (pd.DataFrame): Filtered VRE data
            - 'filtered_cap_solar_dict', 'filtered_cap_wind_dict' (dict): Capacity mappings
    
    Raises:
        FileNotFoundError: If any required input file is missing from input_data_dir.
        ValueError: If formulation specifications are invalid.
    
    Notes:
        - All numeric data rounded to 5 decimal places for consistency
        - VRE plant lists filtered to include only plants with complete data
        - Conditionally loads hydro bounds and import/export data based on formulations
        - Uses flexible filename matching via normalize_string() for CSV files
        - Logs detailed progress at debug level for troubleshooting data loading issues
    """
    logging.info("Loading SDOM input data...")
    
    logging.debug("- Trying to load formulations data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["formulations"], "CSV file to specify the formulations for different components")
    if input_file_path != "":
        formulations = pd.read_csv( input_file_path )
    
    logging.debug("- Trying to load VRE data...")
    # THE SET CSV FILES WERE REMOVED
    # input_file_path = os.path.join(input_data_dir, INPUT_CSV_NAMES["solar_plants"])
    # if check_file_exists(input_file_path, "solar plants ids"):
    #     solar_plants = pd.read_csv( input_file_path, header=None )[0].tolist()
    
    # input_file_path = os.path.join(input_data_dir, INPUT_CSV_NAMES["wind_plants"])
    # if check_file_exists(input_file_path, "wind plants ids"):
    #     wind_plants = pd.read_csv( input_file_path, header=None )[0].tolist()


    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["cf_solar"], "Capacity factors for pv solar")
    if input_file_path != "":
        cf_solar = pd.read_csv( input_file_path ).round(5)
        cf_solar.columns = cf_solar.columns.astype(str)
        solar_plants = cf_solar.columns[1:].tolist()
        logging.debug( f"-- It were loaded a total of {len( solar_plants )} solar plants profiles." )
    
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["cf_wind"], "Capacity factors for wind")
    if input_file_path != "":
        cf_wind = pd.read_csv( input_file_path ).round(5)
        cf_wind.columns = cf_wind.columns.astype(str)
        wind_plants = cf_wind.columns[1:].tolist()
        logging.debug( f"-- It were loaded a total of {len( wind_plants )} wind plants profiles." )

    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["cap_solar"], "Capex information for solar")
    if input_file_path != "":
        cap_solar = pd.read_csv( input_file_path ).round(5)
        cap_solar['sc_gid'] = cap_solar['sc_gid'].astype(str)
        solar_plants_capex = cap_solar['sc_gid'].tolist()
        compare_lists(solar_plants, solar_plants_capex, text_comp="solar plants", list_names=["CF", "Capex"])

    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["cap_wind"], "Capex information for wind")
    if input_file_path != "":
        cap_wind = pd.read_csv( input_file_path ).round(5)
        cap_wind['sc_gid'] = cap_wind['sc_gid'].astype(str)
        wind_plants_capex = cap_wind['sc_gid'].tolist()
        compare_lists(wind_plants, wind_plants_capex, text_comp="wind plants", list_names=["CF", "Capex"])

    logging.debug("- Trying to load demand data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["load_data"], "load data")
    if input_file_path != "":
        load_data = pd.read_csv( input_file_path ).round(5)

    logging.debug("- Trying to load nuclear data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["nuclear_data"], "nuclear data")
    if input_file_path != "":
        nuclear_data = pd.read_csv( input_file_path ).round(5)

    logging.debug("- Trying to load large hydro data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["large_hydro_data"], "large hydro data")
    if input_file_path != "":
        large_hydro_data = pd.read_csv( input_file_path ).round(5)

    logging.debug("- Trying to load other renewables data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["other_renewables_data"], "other renewables data")
    if input_file_path != "":
        other_renewables_data = pd.read_csv( input_file_path ).round(5)

    logging.debug("- Trying to load storage data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["storage_data"], "Storage data")
    if input_file_path != "":
        storage_data = pd.read_csv( input_file_path, index_col=0 ).round(5)
        storage_set_j_techs = storage_data.columns[0:].astype(str).tolist()
        storage_set_b_techs = storage_data.columns[ storage_data.loc["Coupled"] == 1 ].astype( str ).tolist()

    logging.debug("- Trying to load thermal generation data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["thermal_data"], "thermal data")
    if input_file_path != "":
        thermal_data = pd.read_csv( input_file_path ).round(5)

    logging.debug("- Trying to load scalars data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["scalars"], "scalars")
    if input_file_path != "":
        scalars = pd.read_csv( input_file_path, index_col="Parameter" )
    #os.chdir('../')

    data_dict =  {
            "formulations": formulations,
            "solar_plants": solar_plants,
            "wind_plants": wind_plants,
            "load_data": load_data,
            "nuclear_data": nuclear_data,
            "large_hydro_data": large_hydro_data,
            "other_renewables_data": other_renewables_data,
            "cf_solar": cf_solar,
            "cf_wind": cf_wind,
            "cap_solar": cap_solar,
            "cap_wind": cap_wind,
            "storage_data": storage_data,
            "STORAGE_SET_J_TECHS": storage_set_j_techs,
            "STORAGE_SET_B_TECHS": storage_set_b_techs,
            "thermal_data": thermal_data,
            "scalars": scalars,
        }

    # --- Network (zonal) formulation: backward-compatible default ---
    network_formulation = get_formulation(
        data_dict, component="Network", default=DEFAULT_NETWORK_FORMULATION
    )
    check_formulation(network_formulation, VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP.keys())
    data_dict["network_formulation"] = network_formulation

    hydro_formulation = get_formulation(data_dict, component='hydro')
    check_formulation( hydro_formulation, VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP.keys() )

    if not (hydro_formulation == "RunOfRiverFormulation"):
        logging.debug("- Hydro was set to MonthlyBudgetFormulation. Trying to load large hydro max/min data...")
        
        input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["large_hydro_max"], "large hydro Maximum  capacity data")
        if input_file_path != "":
            large_hydro_max = pd.read_csv( input_file_path ).round(5)
        
        input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["large_hydro_min"], "large hydro Minimum capacity data")
        if input_file_path != "":
            large_hydro_min = pd.read_csv( input_file_path ).round(5)
        data_dict["large_hydro_max"] = large_hydro_max
        data_dict["large_hydro_min"] = large_hydro_min
    

    logging.debug("- Trying to load imports data...")    
    imports_formulation = get_formulation(data_dict, component='imports')
    check_formulation( imports_formulation, VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP.keys() )
    if (imports_formulation == "CapacityPriceNetLoadFormulation"):
        logging.debug("- Imports was set to CapacityPriceNetLoadFormulation. Trying to load capacity and price...")
        
        input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["cap_imports"], "Imports hourly upper bound capacity data")
        if input_file_path != "":
            cap_imports = pd.read_csv( input_file_path ).round(5)

        input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["price_imports"], "Imports hourly price data")
        if input_file_path != "":
            price_imports = pd.read_csv( input_file_path ).round(5)
        data_dict["cap_imports"] = cap_imports
        data_dict["price_imports"] = price_imports

    
    logging.debug("- Trying to load exports data...")
    exports_formulation = get_formulation(data_dict, component='exports')
    check_formulation( exports_formulation, VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP.keys() )
    if (exports_formulation == "CapacityPriceNetLoadFormulation"):
        logging.debug("- Exports was set to CapacityPriceNetLoadFormulation. Trying to load capacity and price...")
        
        input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["cap_exports"], "Exports hourly upper bound capacity data")
        if input_file_path != "":
            cap_exports = pd.read_csv( input_file_path ).round(5)

        input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["price_exports"], "Exports hourly price data")
        if input_file_path != "":
            price_exports = pd.read_csv( input_file_path ).round(5)
        data_dict["cap_exports"] = cap_exports
        data_dict["price_exports"] = price_exports
    
    return data_dict
    



# ---------------------------------------------------------------------------------
# Export results to CSV files
# ---------------------------------------------------------------------------------

def export_results(results, case: str, output_dir: str = "./results_pyomo/"):
    """Export optimization results to CSV files.

    Writes the results from an OptimizationResults object to CSV files in the
    specified directory. Creates output directory if it doesn't exist.

    Parameters
    ----------
    results : OptimizationResults
        The optimization results object from run_solver().
    case : str or int
        Case identifier used in output filenames to distinguish between
        different scenarios or runs.
    output_dir : str, optional
        Directory path for output files. Defaults to './results_pyomo/'.
        Directory will be created if it doesn't exist.

    Returns
    -------
    None

    Output Files
    ------------
    OutputGeneration_{case}.csv
        Hourly dispatch results containing: Scenario, Hour, Solar PV/Wind
        generation and curtailment, Thermal, hydro, nuclear, other renewables
        generation, Storage net charge/discharge, imports, exports, Load.

    OutputStorage_{case}.csv
        Hourly storage operation for each technology: Hour, Technology,
        Charging power (MW), Discharging power (MW), State of charge (MWh).

    OutputSummary_{case}.csv
        Summary metrics including: Total costs, Installed capacities by
        technology, Total generation by technology, Demand statistics,
        Cost breakdowns (VRE, storage, thermal CAPEX/FOM/VOM).

    OutputThermalGeneration_{case}.csv
        Disaggregated hourly thermal generation by plant (only if more than
        one thermal plant exists).

    Notes
    -----
    This function accepts either an OptimizationResults dataclass (new API)
    or the legacy tuple return from run_solver (deprecated).
    """
    # Import here to avoid circular imports
    from .results import OptimizationResults

    logging.info("Exporting SDOM results...")
    os.makedirs(output_dir, exist_ok=True)

    # Handle both new OptimizationResults and legacy model input
    if isinstance(results, OptimizationResults):
        _export_from_results_object(results, case, output_dir)
    else:
        # Legacy support: assume it's a model object
        logging.warning(
            "export_results() received a model object instead of OptimizationResults. "
            "This usage is deprecated. Please use the OptimizationResults from run_solver()."
        )
        _export_from_model_legacy(results, case, output_dir)


def _export_from_results_object(results, case: str, output_dir: str):
    """Export results from OptimizationResults object to CSV files.

    Parameters
    ----------
    results : OptimizationResults
        The optimization results object.
    case : str
        Case identifier for filenames.
    output_dir : str
        Output directory path.
    """
    logging.info("Exporting csv files containing SDOM results...")

    # Save generation results to CSV
    logging.debug("-- Saving generation results to CSV...")
    gen_df = results.get_generation_dataframe()
    if not gen_df.empty:
        # Update scenario column with the case name
        gen_df["Scenario"] = case
        gen_df.to_csv(os.path.join(output_dir, f"OutputGeneration_{case}.csv"), index=False)

    # Save storage results to CSV
    logging.debug("-- Saving storage results to CSV...")
    storage_df = results.get_storage_dataframe()
    if not storage_df.empty:
        storage_df.to_csv(os.path.join(output_dir, f"OutputStorage_{case}.csv"), index=False)

    # Save summary results to CSV
    logging.debug("-- Saving summary results to CSV...")
    summary_df = results.get_summary_dataframe()
    if not summary_df.empty:
        summary_df.to_csv(os.path.join(output_dir, f"OutputSummary_{case}.csv"), index=False)

    # Save thermal generation results to CSV (if available)
    logging.debug("-- Saving disaggregated thermal generation results to CSV...")
    thermal_df = results.get_thermal_generation_dataframe()
    if not thermal_df.empty:
        thermal_df.to_csv(os.path.join(output_dir, f"OutputThermalGeneration_{case}.csv"), index=False)

    # Save installed power plants results to CSV
    logging.debug("-- Saving installed power plants results to CSV...")
    installed_plants_df = results.get_installed_plants_dataframe()
    if not installed_plants_df.empty:
        installed_plants_df.to_csv(os.path.join(output_dir, f"OutputInstalledPowerPlants_{case}.csv"), index=False)


def _export_from_model_legacy(model, case, output_dir="./results_pyomo/"):
    """Legacy export function that works directly with a model object.

    This is the original implementation preserved for backward compatibility.

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
        nuclear = safe_pyomo_value(model.nuclear.alpha * model.nuclear.ts_parameter[h]) if hasattr(model.nuclear, "alpha") else 0
        other_renewables = safe_pyomo_value(model.other_renewables.alpha * model.other_renewables.ts_parameter[h]) if hasattr(model.other_renewables, "alpha") else 0
        imports = safe_pyomo_value(model.imports.variable[h]) if hasattr(model.imports, "variable") else 0
        exports = safe_pyomo_value(model.exports.variable[h]) if hasattr(model.exports, "variable") else 0
        load = safe_pyomo_value(model.demand.ts_parameter[h]) if hasattr(model.demand, "ts_parameter") else 0
        net_load = safe_pyomo_value(model.net_load[h]) if hasattr(model, "net_load") else 0
        # Only append results if all values are valid (not None)
        if None not in [solar_gen, solar_curt, wind_gen, wind_curt, gas_cc_gen, hydro, imports, exports, load]:
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

            power_to_storage = sum(safe_pyomo_value(model.storage.PC[h, j]) or 0 for j in model.storage.j) - sum(safe_pyomo_value(model.storage.PD[h, j]) or 0 for j in model.storage.j)
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
    cap["Thermal"] = sum(safe_pyomo_value(model.thermal.plant_installed_capacity[bu]) for bu in model.thermal.plants_set)
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

    summary_results = concatenate_dataframes(summary_results, charge, run=1, unit="MW", metric="Charge power capacity")

    ## Discharge power capacity
    dcharge = {}
    sum_all = 0.0

    for tech in storage_tech_list:
        dcharge[tech] = safe_pyomo_value(model.storage.Pdis[tech])
        sum_all += dcharge[tech]
    dcharge["All"] = sum_all

    summary_results = concatenate_dataframes(summary_results, dcharge, run=1, unit="MW", metric="Discharge power capacity")

    ## Average power capacity
    avgpocap = {}
    sum_all = 0.0
    for tech in storage_tech_list:
        avgpocap[tech] = (charge[tech] + dcharge[tech]) / 2
        sum_all += avgpocap[tech]
    avgpocap["All"] = sum_all

    summary_results = concatenate_dataframes(summary_results, avgpocap, run=1, unit="MW", metric="Average power capacity")

    ## Energy capacity
    encap = {}
    sum_all = 0.0
    for tech in storage_tech_list:
        encap[tech] = safe_pyomo_value(model.storage.Ecap[tech])
        sum_all += encap[tech]
    encap["All"] = sum_all

    summary_results = concatenate_dataframes(summary_results, encap, run=1, unit="MWh", metric="Energy capacity")

    ## Discharge duration
    dis_dur = {}
    for tech in storage_tech_list:
        dis_dur[tech] = safe_pyomo_value(sqrt(model.storage.data["Eff", tech]) * model.storage.Ecap[tech] / (model.storage.Pdis[tech] + 1e-15))

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

    gen["All"] = gen["Thermal"] + gen["Solar PV"] + gen["Wind"] + gen["Other renewables"] + gen["Hydro"] + gen["Nuclear"] + sum_all

    summary_results = concatenate_dataframes(summary_results, gen, run=1, unit="MWh", metric="Total generation")

    imp_exp = {}
    imp_exp["Imports"] = safe_pyomo_value(sum(model.imports.variable[h] for h in model.h)) if hasattr(model.imports, "variable") else 0
    imp_exp["Exports"] = safe_pyomo_value(sum(model.exports.variable[h] for h in model.h)) if hasattr(model.exports, "variable") else 0
    summary_results = concatenate_dataframes(summary_results, imp_exp, run=1, unit="MWh", metric="Total Imports/Exports")

    ## Storage energy discharging
    sum_all = 0.0
    stodisch = {}
    for tech in storage_tech_list:
        stodisch[tech] = safe_pyomo_value(sum(model.storage.PD[h, tech] for h in model.h))
        sum_all += stodisch[tech]
    stodisch["All"] = sum_all

    summary_results = concatenate_dataframes(summary_results, stodisch, run=1, unit="MWh", metric="Storage energy discharging")

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

    summary_results = concatenate_dataframes(summary_results, stoch, run=1, unit="MWh", metric="Storage energy charging")

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

    summary_results = concatenate_dataframes(summary_results, ecapex, run=1, unit="$US", metric="Energy-CAPEX")
    summary_results = concatenate_dataframes(summary_results, tcapex, run=1, unit="$US", metric="Total-CAPEX")

    ## FOM
    fom = {}
    sum_all = 0.0
    fom["Thermal"] = safe_pyomo_value(model.thermal.fixed_om_cost_expr)
    fom["Solar PV"] = safe_pyomo_value(model.pv.fixed_om_cost_expr)
    fom["Wind"] = safe_pyomo_value(model.wind.fixed_om_cost_expr)

    for tech in storage_tech_list:
        fom[tech] = safe_pyomo_value(
            MW_TO_KW * model.storage.data["CostRatio", tech] * model.storage.data["FOM", tech] * model.storage.Pcha[tech]
            + MW_TO_KW * (1 - model.storage.data["CostRatio", tech]) * model.storage.data["FOM", tech] * model.storage.Pdis[tech]
        )
        sum_all += fom[tech]

    fom["All"] = fom["Thermal"] + fom["Solar PV"] + fom["Wind"] + sum_all

    summary_results = concatenate_dataframes(summary_results, fom, run=1, unit="$US", metric="FOM")

    ## VOM
    vom = {}
    sum_all = 0.0
    vom["Thermal"] = safe_pyomo_value(model.thermal.total_vom_cost_expr)

    for tech in storage_tech_list:
        vom[tech] = safe_pyomo_value(model.storage.data["VOM", tech] * sum(model.storage.PD[h, tech] for h in model.h))
        sum_all += vom[tech]
    vom["All"] = vom["Thermal"] + sum_all

    summary_results = concatenate_dataframes(summary_results, vom, run=1, unit="$US", metric="VOM")

    fuel_cost = {}
    fuel_cost["Thermal"] = safe_pyomo_value(model.thermal.total_fuel_cost_expr)
    summary_results = concatenate_dataframes(summary_results, fuel_cost, run=1, unit="$US", metric="Fuel-Cost")

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
    summary_results = concatenate_dataframes(summary_results, cost_revenue, run=1, unit="$US", metric="Revenue")

    ## Equivalent number of cycles
    cyc = {}
    for tech in storage_tech_list:
        cyc[tech] = safe_pyomo_value(gen[tech] / (model.storage.Ecap[tech] + 1e-15))

    summary_results = concatenate_dataframes(summary_results, cyc, run=1, unit="-", metric="Equivalent number of cycles")

    ## VRE Curtailment
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

    logging.info("Exporting csv files containing SDOM results...")
    # Save generation results to CSV
    logging.debug("-- Saving generation results to CSV...")
    if gen_results["Hour"]:
        with open(output_dir + f"OutputGeneration_{case}.csv", mode="w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=gen_results.keys())
            writer.writeheader()
            writer.writerows([dict(zip(gen_results, t)) for t in zip(*gen_results.values())])

    # Save storage results to CSV
    logging.debug("-- Saving storage results to CSV...")
    if storage_results["Hour"]:
        with open(output_dir + f"OutputStorage_{case}.csv", mode="w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=storage_results.keys())
            writer.writeheader()
            writer.writerows([dict(zip(storage_results, t)) for t in zip(*storage_results.values())])

    # Save summary results to CSV
    logging.debug("-- Saving summary results to CSV...")
    if len(summary_results) > 0:
        summary_results.to_csv(output_dir + f"OutputSummary_{case}.csv", index=False)

    if len(model.thermal.plants_set) <= 1:
        return
    thermal_gen_columns = ["Hour"] + [str(plant) for plant in model.thermal.plants_set]
    disaggregated_thermal_gen_results = get_dict_string_void_list_from_keys_in_list(thermal_gen_columns)

    for h in model.h:
        disaggregated_thermal_gen_results["Hour"].append(h)
        for plant in model.thermal.plants_set:
            disaggregated_thermal_gen_results[plant].append(safe_pyomo_value(model.thermal.generation[h, plant]))

    logging.debug("-- Saving disaggregated thermal generation results to CSV...")
    if disaggregated_thermal_gen_results["Hour"]:
        with open(output_dir + f"OutputThermalGeneration_{case}.csv", mode="w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=disaggregated_thermal_gen_results.keys())
            writer.writeheader()
            writer.writerows([dict(zip(disaggregated_thermal_gen_results, t)) for t in zip(*disaggregated_thermal_gen_results.values())])