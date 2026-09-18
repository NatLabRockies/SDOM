from pyomo.core import Var, Constraint, Expression
from pyomo.environ import Set, Param, NonNegativeReals, quicksum
import logging
from .models_utils import build_annualization_factor_map, generic_fixed_om_cost_expr_rule, different_fcr_capex_cost_expr_rule, sum_installed_capacity_by_plants_set_expr_rule, add_generic_fixed_costs, add_generation_variables
from ..constants import MW_TO_KW, THERMAL_PROPERTIES_NAMES

def initialize_thermal_sets(block, data):
    # Initialize THERMAL properties
    block.plants_set = Set( initialize = data['thermal_data']['Plant_id'].astype(str).tolist() )
    block.properties_set = Set( initialize = THERMAL_PROPERTIES_NAMES )
    logging.info(f"Thermal balancing units being considered: {list(block.plants_set)}")

####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|

def _add_thermal_parameters(block, df):
    
    thermal_dict = df.stack().to_dict()
    thermal_tuple_dict = {( prop, name ): thermal_dict[( name, prop )] for prop in THERMAL_PROPERTIES_NAMES for name in block.plants_set}
    
    block.data = Param( block.properties_set, block.plants_set, initialize = thermal_tuple_dict )
    
    # Gas prices (US$/MMBtu)
    block.fuel_price = Param(
        block.plants_set,
        initialize={bu: block.data["FuelCost", bu] for bu in block.plants_set}
    )

    # Heat rate for gas combined cycle (MMBtu/MWh)
    block.heat_rate = Param( 
        block.plants_set, 
        initialize = {bu: block.data["HeatRate", bu] for bu in block.plants_set}
    )
#block.GasPrice, block.HR, block.FOM_GasCC, block.VOM_GasCC
    # Capex for gas combined cycle units (US$/kW)
    block.CAPEX_M = Param( 
        block.plants_set, 
        initialize ={bu: block.data["Capex", bu] for bu in block.plants_set}
    )

    # Fixed O&M for gas combined cycle (US$/kW-year)
    block.FOM_M = Param( 
        block.plants_set, 
        initialize = {bu: block.data["FOM", bu] for bu in block.plants_set}
    )

    # Variable O&M for gas combined cycle (US$/MWh)
    block.VOM_M = Param( 
        block.plants_set, 
        initialize = {bu: block.data["VOM", bu] for bu in block.plants_set} 
    )
    block.trans_cap_cost = Param(block.plants_set, initialize=0.0)


def add_thermal_parameters(host, data: dict):
    df = data["thermal_data"].set_index("Plant_id")
    _add_thermal_parameters(host.thermal, df)
    
    r = float(data["scalars"].loc["r"].Value)
    host.thermal.r = Param(initialize=r)  # Interest rate
    lifetimes_by_unit = {bu: df.loc[bu, "Lifetime"] for bu in host.thermal.plants_set}
    fcr_values = build_annualization_factor_map(r, lifetimes_by_unit)
    host.thermal.FCR = Param(host.thermal.plants_set, initialize=fcr_values)  # Capital Recovery Factor - THERMAL

####################################################################################|
# ------------------------------------ Variables -----------------------------------|
####################################################################################|

def add_thermal_variables(host):
    host.thermal.plant_installed_capacity = Var(host.thermal.plants_set, domain=NonNegativeReals, initialize=0)
    add_generation_variables(host.thermal, host.h, host.thermal.plants_set, domain=NonNegativeReals,  initialize=0)

    for bu in host.thermal.plants_set:
        host.thermal.plant_installed_capacity[bu].setlb(
            host.thermal.data["MinCapacity", bu]
        )
        host.thermal.plant_installed_capacity[bu].setub(
            host.thermal.data["MaxCapacity", bu]
        )


####################################################################################|
# ----------------------------------- Expressions ----------------------------------|
####################################################################################|
def total_thermal_expr_rule(m):
    """
    Expression to calculate the total generation from thermal units.
    
    Parameters:
    m: The optimization model instance.
    h: Time period index.
    bu: Balancing unit index.
    
    Returns:
    The sum of generation from the specified thermal unit across all time periods.
    """
    return sum(m.GenCC[h, bu] for h in m.h for bu in m.thermal.plants_set)

def _add_thermal_expressions(block, set_hours):
    block.total_plant_generation = Expression(block.plants_set, rule=lambda m, bu: quicksum(m.generation[h, bu] for h in set_hours))
    block.total_generation = Expression(rule=quicksum(block.total_plant_generation[bu] for bu in block.plants_set))
    block.total_installed_capacity = Expression( rule = sum_installed_capacity_by_plants_set_expr_rule )

    block.fixed_om_cost_expr = Expression( rule = generic_fixed_om_cost_expr_rule )
    block.capex_cost_expr = Expression( rule = different_fcr_capex_cost_expr_rule )

    block.total_fuel_cost_expr = Expression(
        rule = quicksum(
            ( block.fuel_price[bu] * block.heat_rate[bu] ) * ( block.total_plant_generation[bu] )
            for bu in block.plants_set )
            )
    
    block.total_vom_cost_expr = Expression(
        rule = quicksum(block.VOM_M[bu] * block.total_plant_generation[bu] for bu in block.plants_set)
        )

def add_thermal_expressions(host):
    _add_thermal_expressions(host.thermal, host.h)
    


####################################################################################|
# ----------------------------------- Constraints ----------------------------------|
####################################################################################|

def add_thermal_constraints( host ):
    set_hours = host.h
    # Capacity of the backup generation
    host.thermal.capacity_generation_constraint = Constraint( set_hours, host.thermal.plants_set, rule = lambda m,h,bu: m.plant_installed_capacity[bu] >= m.generation[h,bu]  )


####################################################################################|
# -----------------------------------= Add_costs -----------------------------------|
####################################################################################|
def add_thermal_fixed_costs(host):
    """
    Add cost-related variables for thermal units to the model.

    Parameters:
    model: The optimization model to which thermal cost variables will be added.

    Returns:
    Costs sum for each thermal unit, including capital and fixed O&M costs.
    """
    return (
        add_generic_fixed_costs(host.thermal)
    )

def add_thermal_variable_costs(host):
    """
    Add variable costs (Fuel cost + VOM cost) for thermal units to the model.

    Parameters:
    model: The optimization model to which thermal variable costs will be added.

    Returns:
    Variable costs sum for thermal units, including fuel costs.
    """
    return (
        host.thermal.total_fuel_cost_expr + host.thermal.total_vom_cost_expr
    )

