import logging

from pyomo.environ import Param, Set, RangeSet

from .models.formulations_vre import add_vre_parameters
from .models.formulations_thermal import add_thermal_parameters, initialize_thermal_sets
from .models.formulations_nuclear import add_nuclear_parameters
from .models.formulations_hydro import add_large_hydro_parameters, add_large_hydro_bound_parameters
from .models.formulations_other_renewables import add_other_renewables_parameters
from .models.formulations_load import add_load_parameters
from .models.formulations_storage import add_storage_parameters, initialize_storage_sets
from .models.formulations_resiliency import add_resiliency_parameters
from .models.formulations_imports_exports import add_imports_parameters, add_exports_parameters

from .constants import (
    VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP,
    RUN_OF_RIVER_FORMULATION,
    IMPORTS_EXPORTS_NOT_MODEL,
)
from .io_manager import get_formulation

def initialize_vre_sets(data, block, vre_type: str):
    """Initialize VRE (Variable Renewable Energy) plant sets and filter data for a technology.
    
    Identifies common plants between capacity factor and CAPEX datasets, filters out
    incomplete records, and creates a Pyomo Set for the VRE plants. Also stores
    filtered capacity data back into the data dictionary for later use.
    
    Args:
        data (dict): Dictionary containing all input DataFrames including capacity
            factors and CAPEX data for VRE technologies.
        block: The Pyomo Block (e.g., model.pv or model.wind) where the plants_set
            will be created.
        vre_type (str): Type of VRE technology - either 'solar' or 'wind'. Used to
            construct dictionary keys for accessing the appropriate DataFrames.
    
    Returns:
        None
    
    Notes:
        - Creates block.plants_set as a Pyomo Set containing plant identifiers
        - Filters plants that have complete data (CAPEX_M, trans_cap_cost, FOM_M, capacity)
        - Updates data dict with 'filtered_cap_{vre_type}_dict' and 'complete_{vre_type}_data'
        - Plant IDs are converted to strings for consistent indexing
    """
     # Solar plant ID alignment
    vre_plants_cf = data[f'cf_{vre_type}'].columns[1:].astype(str).tolist()
    vre_plants_cap = data[f'cap_{vre_type}']['sc_gid'].astype(str).tolist()
    common_vre_plants = list(set(vre_plants_cf) & set(vre_plants_cap))

    # Filter solar data and initialize model set
    complete_vre_data = data[f"cap_{vre_type}"][data[f"cap_{vre_type}"]['sc_gid'].astype(str).isin(common_vre_plants)]
    complete_vre_data = complete_vre_data.dropna(subset=['CAPEX_M', 'trans_cap_cost', 'FOM_M', 'capacity'])
    common_vre_plants_filtered = complete_vre_data['sc_gid'].astype(str).tolist()
    
    block.plants_set = Set( initialize = common_vre_plants_filtered )

    # Load the solar capacities
    cap_vre_dict = complete_vre_data.set_index('sc_gid')['capacity'].to_dict()

    # Filter the dictionary to ensure only valid keys are included
    default_capacity_value = 0.0
    filtered_cap_vre_dict = {k: cap_vre_dict.get(k, default_capacity_value) for k in block.plants_set}

    data[f'filtered_cap_{vre_type}_dict'] = filtered_cap_vre_dict
    data[f'complete_{vre_type}_data'] = complete_vre_data


def check_n_hours(n_hours: int, interval: int):
    """Validate and adjust the number of simulation hours to match budget interval.
    
    Ensures that the number of hours is a multiple of the budget aggregation interval
    (e.g., 24 for daily budgets, 730 for monthly budgets). If not, rounds up to the
    nearest multiple and logs a warning.
    
    Args:
        n_hours (int): Requested number of simulation hours.
        interval (int): Budget aggregation interval in hours (e.g., 24, 730).
    
    Returns:
        int: Validated number of hours that is a multiple of the interval. Returns
             n_hours unchanged if already valid, otherwise returns rounded-up value.
    
    Notes:
        Logs a warning when adjustment is needed, informing the user of the approximation.
    """
    if n_hours % interval == 0:
        return n_hours
    else:
        n = (n_hours // interval) + 1
        logging.warning(f"the selected number of hours ({n_hours}) is not multiple of the aggregation interval ({interval}) for the selected formulation. The number of hours will be approximated to {n*interval}.")
    return n * interval

def create_budget_set( model, 
                      block, 
                      n_hours_checked:int, 
                      budget_hours_aggregation:int ):
    """Create a Pyomo Set representing budget periods for aggregated constraints.
    
    Generates a set of budget period indices based on the aggregation interval.
    For example, with 8760 hours and 730-hour intervals (monthly), creates a set
    {1, 2, 3, ..., 12} representing 12 monthly budget periods.
    
    Args:
        model: The Pyomo ConcreteModel instance containing the hourly set (model.h).
        block: The Pyomo Block (e.g., model.hydro) where budget_set will be created.
        n_hours_checked (int): Total number of simulation hours (validated/adjusted).
        budget_hours_aggregation (int): Number of hours per budget period
            (e.g., 24 for daily, 730 for monthly).
    
    Returns:
        None
    
    Notes:
        Creates block.budget_set as a Pyomo Set indexed 1, 2, 3, ..., n_periods.
        The set is declared within=model.h to maintain consistency with hourly indices.
    """
    breakpoints  = list(range(budget_hours_aggregation, n_hours_checked+1, budget_hours_aggregation))
    indices = list(range(1, len(breakpoints) + 1))
    
    block.budget_set = Set( within=model.h, initialize = indices  )
    return

def initialize_sets( model, data, n_hours = 8760 ):
    """Initialize all Pyomo Sets for the SDOM optimization model.
    
    Creates sets for all model components including VRE plants, storage technologies,
    thermal units, and hourly time steps. Handles different hydro formulations by
    adjusting the hourly set and creating budget sets when needed.
    
    Args:
        model: The Pyomo ConcreteModel instance to initialize.
        data (dict): Dictionary containing all input data including DataFrames for
            capacity factors, CAPEX data, storage data, and formulation specifications.
        n_hours (int, optional): Number of simulation hours. Defaults to 8760 (full year).
            May be adjusted if using budget formulations requiring specific intervals.
    
    Returns:
        None
    
    Notes:
        - Initializes model.pv.plants_set and model.wind.plants_set for VRE plants
        - Creates model.storage.j (all storage techs) and model.storage.b (coupled techs)
        - Initializes model.thermal.plants_set for thermal balancing units
        - Creates model.h as the hourly RangeSet (1-based indexing)
        - For budget hydro formulations, adjusts n_hours and creates model.hydro.budget_set
        - Logs information about storage technologies being modeled
    """
    initialize_vre_sets(data, model.pv, vre_type='solar')
    initialize_vre_sets(data, model.wind, vre_type='wind')


    # Define sets

    initialize_storage_sets(model.storage, data)
    logging.info(f"Storage technologies being considered: {list(model.storage.j)}")
    logging.info(f"Storage technologies with coupled charge/discharge power: {list(model.storage.b)}")

    initialize_thermal_sets(model.thermal, data)
   
    hydro_formulation = get_formulation(data, component = 'hydro')
    if "Budget" in hydro_formulation:
        n_hours_checked= check_n_hours(n_hours, VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP[hydro_formulation])
        model.h = RangeSet(1, n_hours_checked)
        model.storage.n_steps_modeled = Param( initialize = n_hours_checked )
        create_budget_set( model, model.hydro, n_hours_checked, VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP[hydro_formulation] )
        
    else:
        model.h = RangeSet(1, n_hours)
        model.storage.n_steps_modeled = Param( initialize = n_hours )

def initialize_params(model, data):
    """Initialize all Pyomo Parameters for the SDOM optimization model.
    
    Adds parameters to the model for all components including VRE technologies,
    storage, thermal units, fixed generation sources (hydro, nuclear, other renewables),
    demand, imports/exports, and system-level scalars. Parameter initialization is
    conditional based on the selected formulations.
    
    Args:
        model: The Pyomo ConcreteModel instance to initialize. Must have Sets already
            initialized via initialize_sets().
        data (dict): Dictionary containing all input data including:
            - scalars DataFrame: discount rate (r), GenMix_Target, alpha values
            - Time-series DataFrames: load, nuclear, hydro, other renewables
            - Technology data: VRE CAPEX/FOM, storage characteristics, thermal parameters
            - Import/export data (if applicable)
    
    Returns:
        None
    
    Notes:
        - Creates Pyomo parameters model.r (discount rate) and model.GenMix_Target (carbon-free target)
        - Initializes time-series parameters for each hour in model.h
        - For budget hydro formulations, adds upper/lower bound parameters
        - Conditionally adds import/export parameters based on formulation selection
        - model.GenMix_Target is mutable to allow sensitivity analysis across runs
        - All monetary values use MW/kW conversion via MW_TO_KW constant
    """
    model.r = Param( initialize = float(data["scalars"].loc["r"].Value) )  # Discount rate

    logging.debug("--Initializing large hydro parameters...")
    add_large_hydro_parameters(model, data)
    if get_formulation(data, component="hydro") != RUN_OF_RIVER_FORMULATION:
        logging.debug("--Initializing large hydro budget parameters...")
        add_large_hydro_bound_parameters(model, data)
    
   

    logging.debug("--Initializing load parameters...")
    add_load_parameters(model, data)

    logging.debug("--Initializing nuclear parameters...")
    add_nuclear_parameters(model, data)

    logging.debug("--Initializing other renewables parameters...")
    add_other_renewables_parameters(model, data)

    logging.debug("--Initializing storage parameters...")
    add_storage_parameters(model, data)

    logging.debug("--Initializing thermal parameters...")
    add_thermal_parameters(model,data)

    logging.debug("--Initializing VRE parameters...")
    add_vre_parameters(model, data)

    if get_formulation(data, component="Imports") != IMPORTS_EXPORTS_NOT_MODEL:
        logging.debug("--Initializing Imports parameters...")
        add_imports_parameters(model, data)

    if get_formulation(data, component="Exports") != IMPORTS_EXPORTS_NOT_MODEL:
        logging.debug("--Initializing Exports parameters...")
        add_exports_parameters(model, data)
        

    # GenMix_Target, mutable to change across multiple runs
    model.GenMix_Target = Param( initialize = float(data["scalars"].loc["GenMix_Target"].Value), mutable=True)
    
    logging.debug("--Initializing resiliency parameters...")
    add_resiliency_parameters(model, data)
    #model.CRF.display()