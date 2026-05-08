from pyexpat import model
from pyomo.environ import Set, Param, value, NonNegativeReals
from .models_utils import add_generation_variables, add_alpha_and_ts_parameters, add_budget_parameter, add_upper_bound_paramenters, add_lower_bound_paramenters, generic_budget_rule
from pyomo.core import Var, Constraint, Expression

from ..constants import VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP, MONTHLY_BUDGET_HOURS_AGGREGATION, DAILY_BUDGET_HOURS_AGGREGATION
from ..io_manager import get_formulation


####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|

def add_large_hydro_parameters(host, data: dict):
    add_alpha_and_ts_parameters(host.hydro, host.h, data, "AlphaLargHy", "large_hydro_data", "LargeHydro")
    formulation = get_formulation(data, component='hydro')
    add_budget_parameter(host.hydro, formulation, VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP)


def add_large_hydro_bound_parameters(host, data: dict):
    # Time-series parameter data initialization
    add_upper_bound_paramenters(host.hydro, host.h, data, "large_hydro_max", "LargeHydro")
    add_lower_bound_paramenters(host.hydro, host.h, data, "large_hydro_min", "LargeHydro")



####################################################################################|
# ------------------------------------ Variables -----------------------------------|
####################################################################################|

def add_hydro_variables(host):
    add_generation_variables(host.hydro, host.h, domain=NonNegativeReals, initialize=0)

####################################################################################|
# ----------------------------------- Constraints ----------------------------------|
####################################################################################|

def add_hydro_run_of_river_constraints(host, data: dict):
    host.hydro.run_of_river_constraint = Constraint(host.h, rule=lambda m,h: m.generation[h] == m.alpha * m.ts_parameter[h] )
    return


def add_hydro_budget_constraints(host, data: dict):
    
    host.hydro.upper_bound_ts_constraint = Constraint(host.h, rule=lambda m,h: m.generation[h] <= m.alpha * m.ts_parameter_upper_bound[h] )
    host.hydro.lower_bound_ts_constraint = Constraint(host.h, rule=lambda m,h: m.generation[h] >= m.alpha * m.ts_parameter_lower_bound[h] )

    host.hydro.budget_constraint = Constraint(host.hydro.budget_set, rule = generic_budget_rule )
    
    return
