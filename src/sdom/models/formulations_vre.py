from pyomo.core import Var, Constraint, Expression
from pyomo.core import Var, Constraint, Expression
from pyomo.environ import Param, NonNegativeReals
from ..constants import VRE_PROPERTIES_NAMES, MW_TO_KW
from .models_utils import fcr_rule, generic_fixed_om_cost_expr_rule, generic_capex_cost_expr_rule, sum_installed_capacity_by_plants_set_expr_rule, add_generic_fixed_costs, add_generation_variables
import pandas as pd

####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|
def _add_vre_parameters(block, 
                      set_hours, 
                      data: dict,
                      key_filt_dict: str,
                      key_comp_data: str,
                      key_cf_data: str ):
    
    filtered_cap_solar_dict = data[key_filt_dict]
    complete_solar_data = data[key_comp_data]
     # Initialize solar and wind parameters, with default values for missing data
    for property_name in VRE_PROPERTIES_NAMES:#['trans_cap_cost', 'CAPEX_M', 'FOM_M']:
        property_dict_solar = complete_solar_data.set_index('sc_gid')[property_name].to_dict()
        default_value = 0.0
        filtered_property_dict_solar = {k: property_dict_solar.get(k, default_value) for k in block.plants_set}
        block.add_component(f"{property_name}", Param(block.plants_set, initialize=filtered_property_dict_solar))

    block.max_capacity = Param( block.plants_set, initialize = filtered_cap_solar_dict )


    # Solar capacity factor initialization
    cf_vre_melted = data[key_cf_data].melt(id_vars='Hour', var_name='plant', value_name='CF')
    cf_vre_filtered = cf_vre_melted[(cf_vre_melted['plant'].isin(block.plants_set)) & (cf_vre_melted['Hour'].isin(set_hours))]
    cf_vre_dict = cf_vre_filtered.set_index(['Hour', 'plant'])['CF'].to_dict()
    block.capacity_factor = Param( set_hours, block.plants_set, initialize = cf_vre_dict )


def add_vre_parameters(host, data: dict):
    #add solar parameters
    _add_vre_parameters(host.pv, 
                      host.h, 
                      data,
                      key_filt_dict = "filtered_cap_solar_dict",
                      key_comp_data = "complete_solar_data",
                      key_cf_data = "cf_solar")
    
    _add_vre_parameters(host.wind, 
                      host.h, 
                      data,
                      key_filt_dict = "filtered_cap_wind_dict",
                      key_comp_data = "complete_wind_data",
                      key_cf_data = "cf_wind")
    
    host.FCR_VRE = Param( initialize = fcr_rule( host, float(data["scalars"].loc["LifeTimeVRE"].Value) ) )


####################################################################################|
# ------------------------------------ Variables -----------------------------------|
####################################################################################|

def _add_vre_variables(block, set_hours):
    add_generation_variables(block, set_hours, domain=NonNegativeReals, initialize=0)
    block.curtailment = Var(set_hours, domain=NonNegativeReals, initialize=0) # Curtailment 
    block.capacity_fraction = Var(block.plants_set, domain=NonNegativeReals, bounds=(0, 1), initialize=1) #fraction of the maximum allowable capacity that will be installed

def add_vre_variables(host):
    """
    Add variables related to variable renewable energy (VRE) to the model.
    
    Parameters:
    model: The optimization model to which VRE variables will be added.
    
    Returns:
    None
    """
    _add_vre_variables(host.pv, host.h)
    _add_vre_variables(host.wind, host.h)

####################################################################################|
# ----------------------------------- Expressions ----------------------------------|
####################################################################################|


def _add_vre_expresions ( block, fcr_vre, set_hours ):

    block.plant_installed_capacity = Expression(block.plants_set, rule=lambda block, k: block.max_capacity[k] * block.capacity_fraction[k] )
    block.total_installed_capacity = Expression( rule = sum_installed_capacity_by_plants_set_expr_rule )

    block.fixed_om_cost_expr = Expression( rule = generic_fixed_om_cost_expr_rule )
    block.capex_cost_expr = Expression (rule = lambda model: fcr_vre * generic_capex_cost_expr_rule(model) )

    block.total_hourly_availability = Expression(set_hours, rule=lambda block, h: block.generation[h] + block.curtailment[h])
    block.total_hourly_plant_availability = Expression(set_hours, block.plants_set, rule=lambda block, h, k: block.capacity_factor[h, k] * block.max_capacity[k] * block.capacity_fraction[k])

    block.total_generation = Expression( rule = sum(block.generation[h] for h in set_hours) )
    block.total_curtailment = Expression( rule = sum(block.curtailment[h] for h in set_hours) )


def add_vre_expressions(host):
    _add_vre_expresions(host.pv, host.FCR_VRE, host.h )
    _add_vre_expresions(host.wind, host.FCR_VRE, host.h )
    
    

####################################################################################|
# ------------------------------------ Add_costs -----------------------------------|
####################################################################################|

def add_vre_fixed_costs(host):
    """
    Add cost-related variables for variable renewable energy (VRE) to the model.
    
    Parameters:
    model: The optimization model to which VRE cost variables will be added.
    
    Returns:
    Costs sum for solar PV and wind energy, including capital and fixed O&M costs.
    """
    # Solar PV Capex and Fixed O&M
    return ( 
        add_generic_fixed_costs(host.pv) + add_generic_fixed_costs(host.wind)
    )

####################################################################################|
# ----------------------------------- Constraints ----------------------------------|
####################################################################################|
# - Solar balance : generation + curtailed generation = capacity factor * capacity
def vre_balance_rule(block, h):
    return block.total_hourly_availability[h] == sum(block.total_hourly_plant_availability[h, k] for k in block.plants_set)


def add_vre_balance_constraints(host):
    """
    Add constraints related to variable renewable energy (VRE) to the model.
    
    Parameters:
    model: The optimization model to which VRE constraints will be added.
    
    Returns:
    None
    """
    # Solar balance constraint
    host.pv.balance = Constraint(host.h, rule=vre_balance_rule)
    # Wind balance constraint
    host.wind.balance = Constraint(host.h, rule=vre_balance_rule)