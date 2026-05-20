from pyomo.environ import Param, NonNegativeReals
from pyomo.core import Var
from ..constants import MW_TO_KW


def compute_annualization_factor(rate: float, lifetime: float) -> float:
    """Compute the fixed-charge/capital-recovery factor as a float.

    Parameters
    ----------
    rate : float
        Discount/interest rate.
    lifetime : float
        Asset lifetime in years.

    Returns
    -------
    float
        Annualization factor ``r(1+r)^n / ((1+r)^n - 1)``.
    """
    return (rate * (1 + rate) ** lifetime) / ((1 + rate) ** lifetime - 1)


def build_annualization_factor_map(rate: float, lifetimes_by_key: dict) -> dict:
    """Build annualization factors for a keyed lifetime mapping.

    Parameters
    ----------
    rate : float
        Discount/interest rate.
    lifetimes_by_key : dict
        Mapping from item key to lifetime value.

    Returns
    -------
    dict
        Mapping from the same keys to annualization factors.
    """
    return {
        key: compute_annualization_factor(rate, float(lifetime))
        for key, lifetime in lifetimes_by_key.items()
    }


####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|
def get_filtered_ts_parameter_dict( hourly_set, data: dict, key_ts: str, key_col: str):
    """Extract and filter time-series parameter data for a specific hourly set.
    
    Retrieves time-series data from a DataFrame and filters it to include only
    the hours present in the model's hourly set. Used to initialize Pyomo Param
    objects with time-indexed data.
    
    Args:
        hourly_set: The Pyomo Set containing hour indices for the model (e.g., model.h).
        data (dict): Dictionary containing all input data DataFrames.
        key_ts (str): Key to access the time-series DataFrame in the data dict
            (e.g., 'load_data', 'nuclear_data').
        key_col (str): Column name in the DataFrame to extract values from
            (e.g., 'Load', 'Nuclear').
    
    Returns:
        dict: Dictionary mapping hour indices to parameter values, filtered to
              only include hours in hourly_set.
    
    Notes:
        Expects DataFrame to have a '*Hour' column for indexing.
    """
    selected_data          = data[key_ts].set_index('*Hour')[key_col].to_dict()
    filtered_selected_data = {h: selected_data[h] for h in hourly_set if h in selected_data}
    return filtered_selected_data

def add_alpha_parameter(block, data, key_scalars: str):
    """Add a control parameter (alpha) to a Pyomo block to enable/disable a component.
    
    Creates a scalar Pyomo Param named 'alpha' on the block if it doesn't already exist.
    The alpha parameter acts as an activation flag (typically 0 or 1) for controlling
    whether a technology or component is included in the model.
    
    Args:
        block: The Pyomo Block where the parameter will be added.
        data (dict): Dictionary containing the 'scalars' DataFrame with parameter values.
        key_scalars (str): Index key to look up the alpha value in the scalars DataFrame.
            If empty string, no parameter is added.
    
    Returns:
        None
    
    Notes:
        Only adds the parameter if the block doesn't already have an 'alpha' attribute.
    """
    if not hasattr(block, "alpha") and key_scalars != "":
        block.alpha = Param( initialize = float(data["scalars"].loc[key_scalars].Value) )

def add_alpha_and_ts_parameters( block, 
                                hourly_set, 
                                data: dict, 
                                key_scalars: str, 
                                key_ts: str,
                                key_col: str):
    """Add both control parameter (alpha) and time-series parameter to a block.
    
    Convenience function that adds an activation control parameter and a time-indexed
    parameter to a Pyomo block. Commonly used for fixed generation sources like
    nuclear, hydro, or other renewables.
    
    Args:
        block: The Pyomo Block where parameters will be added.
        hourly_set: The Pyomo Set containing hour indices (e.g., model.h).
        data (dict): Dictionary containing input DataFrames.
        key_scalars (str): Index key for the alpha control parameter in scalars DataFrame.
        key_ts (str): Key to access the time-series DataFrame (e.g., 'nuclear_data').
        key_col (str): Column name in the time-series DataFrame to extract.
    
    Returns:
        None
    
    Notes:
        Creates block.alpha as a scalar Param and block.ts_parameter as time-indexed Param.
    """
    # Control parameter to activate certain device.
    add_alpha_parameter(block, data, key_scalars)

    # Time-series parameter data initialization
    filtered_selected_data = get_filtered_ts_parameter_dict(hourly_set, data, key_ts, key_col)
    block.ts_parameter = Param( hourly_set, initialize = filtered_selected_data)


def add_budget_parameter(block, formulation, valid_formulation_to_budget_map: dict):
    """Add a budget aggregation parameter to a block based on the selected formulation.
    
    Creates a scalar Pyomo Param indicating the number of hours in each budget period
    (i.e., the budget period interval in hours, e.g., 730 for monthly, 24 for daily
    budgets). Used primarily for hydropower budget formulations.
    
    Args:
        block: The Pyomo Block where the parameter will be added.
        formulation (str): The selected formulation name (e.g., 'MonthlyBudgetFormulation').
        valid_formulation_to_budget_map (dict): Mapping from formulation names to
        budget period intervals in hours.
    
    Returns:
        None
    
    Notes:
        Only adds block.budget_scalar if it doesn't already exist on the block.
    """
    if not hasattr(block, "budget_scalar"):
        block.budget_scalar = Param( initialize = valid_formulation_to_budget_map[formulation])

def add_upper_bound_paramenters(block, 
                                hourly_set, 
                                data, 
                                key_ts: str = "large_hydro_max", 
                                key_col: str = "LargeHydro"):
    """Add time-series upper bound parameters to a block.
    
    Extracts maximum capacity or generation limits from time-series data and adds
    them as a time-indexed Pyomo Param to the block. Used for technologies with
    hourly-varying upper bounds (e.g., hydro max generation).
    
    Args:
        block: The Pyomo Block where the parameter will be added.
        hourly_set: The Pyomo Set containing hour indices.
        data (dict): Dictionary containing input DataFrames.
        key_ts (str, optional): Key to access the DataFrame with upper bound data.
            Defaults to 'large_hydro_max'.
        key_col (str, optional): Column name to extract from the DataFrame.
            Defaults to 'LargeHydro'.
    
    Returns:
        None
    
    Notes:
        Creates block.ts_parameter_upper_bound as a time-indexed Param.
    """
    
    selected_data          = data[key_ts].set_index('*Hour')[key_col].to_dict()
    filtered_selected_data = {h: selected_data[h] for h in hourly_set if h in selected_data}
    block.ts_parameter_upper_bound = Param( hourly_set, initialize = filtered_selected_data)

def add_lower_bound_paramenters(block, 
                                hourly_set, 
                                data: dict, 
                                key_ts: str = "large_hydro_min", 
                                key_col: str = "LargeHydro"):
    """Add time-series lower bound parameters to a block.
    
    Extracts minimum capacity or generation requirements from time-series data and
    adds them as a time-indexed Pyomo Param to the block. Used for technologies
    with hourly-varying lower bounds (e.g., hydro minimum flow requirements).
    
    Args:
        block: The Pyomo Block where the parameter will be added.
        hourly_set: The Pyomo Set containing hour indices.
        data (dict): Dictionary containing input DataFrames.
        key_ts (str, optional): Key to access the DataFrame with lower bound data.
            Defaults to 'large_hydro_min'.
        key_col (str, optional): Column name to extract from the DataFrame.
            Defaults to 'LargeHydro'.
    
    Returns:
        None
    
    Notes:
        Creates block.ts_parameter_lower_bound as a time-indexed Param.
    """
    
    selected_data          = data[key_ts].set_index('*Hour')[key_col].to_dict()
    filtered_selected_data = {h: selected_data[h] for h in hourly_set if h in selected_data}
    block.ts_parameter_lower_bound = Param( hourly_set, initialize = filtered_selected_data)

####################################################################################|
# ------------------------------------ Variables -----------------------------------|
####################################################################################|
def add_generation_variables(block, *sets, domain=NonNegativeReals, initialize=0):
    """Add a generation variable to a Pyomo block indexed over arbitrary sets.
    
    Creates a Pyomo Var named 'generation' on the block, indexed over the provided
    sets. Supports flexible indexing (e.g., by hour only, or by plant and hour).
    
    Args:
        block: The Pyomo Block to which the variable will be added.
        *sets: Variable number of Pyomo Sets to use as indices. Can be single set
            (e.g., hours) or multiple sets (e.g., plants, hours).
        domain (pyomo.core.base.set, optional): Domain constraint for the variable.
            Defaults to NonNegativeReals.
        initialize (float, optional): Initial value for all variable indices.
            Defaults to 0.
    
    Returns:
        None
    
    Examples:
        >>> add_generation_variables(block, model.h)  # Indexed by hours
        >>> add_generation_variables(block, model.plants_set, model.h)  # By plant and hour
    
    Notes:
        Creates block.generation as a Var. Commonly used for hourly generation dispatch.
    """
    block.generation = Var(*sets, domain=domain, initialize=initialize)

# def add_generation_variables(block, set_hours, initialize=0):
#     block.generation = Var(set_hours, domain=NonNegativeReals, initialize=initialize)



####################################################################################|
# ----------------------------------- Expressions ----------------------------------|
####################################################################################|

def sum_installed_capacity_by_plants_set_expr_rule( block ):
    """Create a Pyomo expression for total installed capacity across all plants in a block.
    
    Sums the plant_installed_capacity variable over all plants in block.plants_set.
    This expression is used to aggregate individual plant capacities into a total
    capacity metric for a technology (e.g., total PV capacity, total wind capacity).
    
    Args:
        block: The Pyomo Block containing plant_installed_capacity Var and plants_set Set.
    
    Returns:
        Pyomo expression: A Pyomo expression representing the sum of
            installed capacities.
    
    Notes:
        Expects block.plant_installed_capacity to be indexed by block.plants_set.
        Used as a rule function for creating Pyomo Expression objects.
    """
    return sum( block.plant_installed_capacity[plant] for plant in block.plants_set )
 

def generic_fixed_om_cost_expr_rule( block ):
    """Create a Pyomo expression for total fixed O&M costs across all plants.
    
    Calculates the annual fixed operation and maintenance costs for all plants
    in a technology block. Cost is based on fixed O&M rate ($/kW-yr) times
    installed capacity (MW).
    
    Args:
        block: The Pyomo Block containing FOM_M Param, plant_installed_capacity Var,
            and plants_set Set.
    
    Returns:
        pyomo.core.expr.numeric_expr: Pyomo expression for total annual fixed O&M costs.
    
    Notes:
        Formula: sum over plants of (FOM_M[k] * MW_TO_KW * capacity[k])
        FOM_M is in $/kW-yr, capacity is in MW, so MW_TO_KW converts units.
    """
    return sum( ( MW_TO_KW * block.FOM_M[k]) * block.plant_installed_capacity[k] for k in block.plants_set )


def generic_capex_cost_expr_rule( block ):
    """Create a Pyomo expression for total CAPEX costs with uniform FCR across plants.
    
    Calculates the annualized capital expenditures for all plants in a technology
    block when all plants share the same fixed charge rate (FCR). Includes both
    technology CAPEX and transmission/interconnection costs.
    
    Args:
        block: The Pyomo Block containing CAPEX_M Param, trans_cap_cost Param,
            plant_installed_capacity Var, and plants_set Set.
    
    Returns:
        Pyomo Expression: Pyomo expression for total annualized CAPEX.
    
    Notes:
        Formula: sum over plants of [(CAPEX_M[k]*MW_TO_KW + trans_cap_cost[k]) * capacity[k]].
        CAPEX_M is in $/kW, trans_cap_cost in $, capacity in MW.
    """
    return sum( ( (MW_TO_KW * block.CAPEX_M[k] + block.trans_cap_cost[k]))\
                                         * block.plant_installed_capacity[k] for k in block.plants_set )


def different_fcr_capex_cost_expr_rule( block ):
    """Create a Pyomo expression for total annualized CAPEX with plant-specific FCRs.
    
    Calculates the annualized capital expenditures when each plant has its own
    fixed charge rate based on technology-specific lifetime. The FCR is applied
    within this expression for each plant individually.
    
    Args:
        block: The Pyomo Block containing FCR Param, CAPEX_M Param, trans_cap_cost Param,
            plant_installed_capacity Var, and plants_set Set.
    
    Returns:
        pyomo.core.expr.numeric_expr: Pyomo expression for total annualized CAPEX.
    
    Notes:
        Formula: sum over plants of [FCR[k] * (CAPEX_M[k]*MW_TO_KW + trans_cap_cost[k]) * capacity[k]]
        Used when plants have different lifetimes, requiring plant-specific FCRs.
    """
    return sum( ( block.FCR[k] * (MW_TO_KW * block.CAPEX_M[k] + block.trans_cap_cost[k]))\
                                         * block.plant_installed_capacity[k] for k in block.plants_set )


####################################################################################|
# ----------------------------------- Constraints ----------------------------------|
####################################################################################|

def generic_budget_rule(block, hhh):
    """Create a budget constraint ensuring generation matches fixed time-series over an interval.
    
    Constraint rule that ensures total generation over a budget period (e.g., month, day)
    equals the sum of the time-series parameter over that same period. Used for
    technologies with energy budgets like hydropower with monthly/daily constraints.
    
    Args:
        block: The Pyomo Block containing generation Var, ts_parameter Param, and
            budget_scalar Param.
        hhh: Index for the budget period (e.g., 1 for first month, 2 for second month).
    
    Returns:
        pyomo.core.expr.relational_expr: Constraint expression enforcing budget equality.
    
    Notes:
        Calculates start/end hours based on: start = (hhh-1)*budget_scalar + 1,
        end = hhh*budget_scalar.
        Constraint: sum(generation[h]) == sum(ts_parameter[h]) over budget period.
    """
    budget_n_hours = block.budget_scalar
    start = ( (hhh - 1) * budget_n_hours ) + 1
    end = hhh * budget_n_hours + 1
    list_budget = list(range(start, end))
    return sum(block.generation[h] for h in list_budget) == sum(block.ts_parameter[h] for h in list_budget)

####################################################################################|
# -----------------------------------= Add_costs -----------------------------------|
####################################################################################|

def add_generic_fixed_costs(block):
    """Calculate total fixed annual costs (CAPEX + FOM) for a technology block.
    
    Aggregates annualized capital expenditures and fixed operation & maintenance
    costs for a technology. This function is used in objective function formulation
    to sum up the fixed cost components.
    
    Args:
        block: The Pyomo Block that must have capex_cost_expr and fixed_om_cost_expr
            Expression attributes already defined.
    
    Returns:
        pyomo.core.expr.numeric_expr: Sum of CAPEX and FOM expressions representing
            total annual fixed costs.
    
    Notes:
        Requires block.capex_cost_expr and block.fixed_om_cost_expr to be defined
        before calling this function.
        Returns the sum that can be used directly in objective function or cost expressions.
    """
    return block.capex_cost_expr + block.fixed_om_cost_expr