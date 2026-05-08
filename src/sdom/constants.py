# INCLUDE HERE ALL THE CONSTATS AND USE UPPER CASE NAMES

MW_TO_KW = 1000.0

#---------------- -------------------- --------------|
#---------------- LOGGING COLOR CONFIG --------------|
#---------------- -------------------- --------------|
LOG_COLORS = {
        'INFO': '\033[92m',    # Green
        'WARNING': '\033[93m', # Yellow
        'ERROR': '\033[91m',   # Red
        'CRITICAL': '\033[91m',# Red
        'DEBUG': '\033[94m',   # Blue (optional)
    }

INPUT_CSV_NAMES = {
    # 'solar_plants': 'Set_k_SolarPV.csv', #Now this set is optional since are col names CFSolar_2050.csv
    # 'wind_plants': 'Set_w_Wind.csv', #Now this set is optional since are col names CFWind_2050.csv
    'formulations': 'formulations.csv',
    'load_data': 'Load_hourly.csv',#'Load_hourly_2050.csv',
    'nuclear_data': 'Nucl_hourly.csv',#'Nucl_hourly_2019.csv',
    'large_hydro_data': 'lahy_hourly.csv', #'lahy_hourly_2019.csv',
    'large_hydro_max': 'lahy_max_hourly.csv', #'lahy_hourly_2019.csv',
    'large_hydro_min': 'lahy_min_hourly.csv', #'lahy_hourly_2019.csv',
    'other_renewables_data': 'otre_hourly.csv', #'otre_hourly_2019.csv',
    'cf_solar': 'CFSolar.csv', #'CFSolar_2050.csv',
    'cf_wind': 'CFWind.csv', #'CFWind_2050.csv',
    'cap_solar': 'CapSolar.csv', #'CapSolar_2050.csv',
    'cap_wind': 'CapWind.csv', #'CapWind_2050.csv',
    'thermal_data': 'Data_BalancingUnits.csv', #'Data_BalancingUnits_2030(in).csv',
    'storage_data': 'StorageData.csv', #'StorageData_2050.csv',
    "cap_imports": "Import_Cap.csv",
    "cap_exports": "Export_Cap.csv",
    "price_imports": "Import_Prices.csv",
    "price_exports": "Export_Prices.csv",
    # --- Zonal (Network=AreaTransportationModelNetwork) topology + line caps ---
    "interconnections": "interconnections.csv",
    "line_cap_ft": "LineCap_FT.csv",
    "line_cap_tf": "LineCap_TF.csv",
    'scalars': 'scalars.csv', #'scalars.csv',
}

VRE_PROPERTIES_NAMES = ['trans_cap_cost', 'CAPEX_M', 'FOM_M']
STORAGE_PROPERTIES_NAMES = ['P_Capex', 'E_Capex', 'Eff', 'Min_Duration',
                          'Max_Duration', 'Max_P', 'Coupled', 'FOM', 'VOM', 'Lifetime', 'CostRatio']

THERMAL_PROPERTIES_NAMES = ['MinCapacity', 'MaxCapacity', 'Lifetime', 'Capex', 'HeatRate', 'FuelCost', 'VOM', 'FOM']

#TODO this set is the col names of the StorageData_2050.csv file
#STORAGE_SET_J_TECHS = ['Li-Ion', 'CAES', 'PHS', 'H2'] - THIS WAS REPLACED BY "data["STORAGE_SET_J_TECHS"]" which reads the cols of storage_data
#STORAGE_SET_B_TECHS = ['Li-Ion', 'PHS'] #THIS WAS REPLACED BY "data["STORAGE_SET_B_TECHS"]"

MONTHLY_BUDGET_HOURS_AGGREGATION = 730
DAILY_BUDGET_HOURS_AGGREGATION = 24
RUN_OF_RIVER_AGGREGATION = 1
VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP = {
    "MonthlyBudgetFormulation": MONTHLY_BUDGET_HOURS_AGGREGATION,
    "DailyBudgetFormulation": DAILY_BUDGET_HOURS_AGGREGATION,
    "RunOfRiverFormulation": RUN_OF_RIVER_AGGREGATION
}

VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP = {
    "NotModel": "No imports/exports considered in the model.",
    #"FixedTimeSeriesFormulation": "Formulation to load a time series of import data and fixed it according to that.",
    "CapacityPriceNetLoadFormulation": "Formulation to load a time series parameter with the import/export maximum capacity and import/export prices and dispatch it. Imports only allowed when net load is positive/negative",
    "WithoutNetLoadConstraints": "Linear formulation: imports/exports bounded by hourly capacity and priced by hourly price; no net-load binary coupling. Used by the resiliency module.",
    #"CapacityPriceBudgetFormulation": "Formulation to load a time series parameter with the maximum capacity and import prices and dispatch it. Imports allowed always, but limited by a budget.",
}

# Network (zonal) formulation choices.
# Used by io_manager.get_formulation(data, "Network") and by initialize_model
# to dispatch between the legacy single-area copper-plate path and the
# multi-area transportation network path.
VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP = {
    "CopperPlateNetwork": "Single system-wide energy balance (legacy behavior). Default when the 'Network' row is absent from formulations.csv.",
    "AreaTransportationModelNetwork": "Per-area energy balance linked by a lossless transportation model with signed, asymmetric, time-varying line capacities.",
}

# Default Network formulation when 'Network' row is missing from formulations.csv
# (preserves backward compatibility with all legacy data folders).
DEFAULT_NETWORK_FORMULATION = "CopperPlateNetwork"

# Reserved area_id used when a legacy (non-zonal) data folder is loaded so
# downstream zonal-aware code can treat all data as belonging to a single area.
DEFAULT_AREA_ID = "default"

# Reserved character used in wide-CSV column headers to delimit the area-id
# metadata tag, e.g. "load@A1@". Entity ids and area ids must not contain it.
AREA_TAG_DELIMITER = "@"

#RESILIENCY CONSTANTS HARD-CODED
# PCLS - Percentage of Critical Load Served - Constraint : Resilience
CRITICAL_LOAD_PERCENTAGE = 1  # 10% of the total load
PCLS_TARGET = 0.9  # 90% of the total load