from pyomo.core import Var, Expression, Constraint
from pyomo.environ import *
from .models_utils import get_filtered_ts_parameter_dict
from ..io_manager import get_formulation
from ..constants import (
    IMPORTS_EXPORTS_NOT_MODEL,
    IMPORTS_EXPORTS_WITHOUT_NET_LOAD_CONSTRAINTS,
)

####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|

def add_import_export_ts_parameters( block, 
                                hourly_set, 
                                data: dict, 
                                key_ts: str,
                                key_col: str):
    # Time-series parameter data initialization
    filtered_selected_data = get_filtered_ts_parameter_dict(hourly_set, data, key_ts, key_col)
    if key_ts in ["cap_imports", "cap_exports"]:
        block.ts_capacity_parameter = Param( hourly_set, initialize = filtered_selected_data)
    elif key_ts in ["price_imports", "price_exports"]:
        block.ts_price_parameter = Param( hourly_set, initialize = filtered_selected_data)
    return


def add_imports_parameters(host, data: dict):
    add_import_export_ts_parameters( host.imports, host.h, data, "cap_imports", "Imports")
    add_import_export_ts_parameters( host.imports, host.h, data, "price_imports", "Imports_price")
    return

def add_exports_parameters(host, data: dict):
    add_import_export_ts_parameters( host.exports, host.h, data, "cap_exports", "Exports")
    add_import_export_ts_parameters( host.exports, host.h, data, "price_exports", "Exports_price")
    return



####################################################################################|
# ------------------------------------ Variables -----------------------------------|
####################################################################################|
def _add_generic_import_export_variables(block, *sets, domain=NonNegativeReals, initialize=0):
    block.variable = Var(*sets, domain=domain, initialize=initialize)
    return

def add_imports_variables(host):
    _add_generic_import_export_variables(host.imports, host.h, domain=NonNegativeReals, initialize=0)
    return


def add_exports_variables(host):
    _add_generic_import_export_variables(host.exports, host.h, domain=NonNegativeReals, initialize=0)
    return

####################################################################################|
# ----------------------------------- Expressions ----------------------------------|
####################################################################################|
def _add_imports_exports_cost_expressions(block, hourly_set, data: dict, component: str):
    if get_formulation(data, component=component) != IMPORTS_EXPORTS_NOT_MODEL:
        block.total_cost_expr = Expression( rule = sum(block.ts_price_parameter[h] * block.variable[h] for h in hourly_set) )
    else:
        block.total_cost_expr = Expression( rule = 0 )
    return

def add_imports_exports_cost_expressions(host, data: dict):
   
    _add_imports_exports_cost_expressions(host.imports, host.h, data, 'Imports')
    _add_imports_exports_cost_expressions(host.exports, host.h, data, 'Exports')
    return


####################################################################################|
# ----------------------------------- Constraints ----------------------------------|
####################################################################################|
def _add_imports_exports_capacity_constraint(block, hourly_set):
    block.capacity_constraint = Constraint(hourly_set, rule=lambda m,h: m.variable[h] <= m.ts_capacity_parameter[h] )
    return

def add_import_export_binary_variable(host, big_m_constant):

    if hasattr(host, 'aux_imp_exp_binary_variable'):
        return
    
    host.aux_imp_exp_binary_variable = Var(host.h, domain=Binary, initialize=0)
    
    host.imp_exp_aux_bigM_constraint_positive = Constraint(
        host.h,
        rule=lambda m, h: m.net_load[h] <= big_m_constant * m.aux_imp_exp_binary_variable[h]
    )
    host.imp_exp_aux_bigM_constraint_negative = Constraint(
        host.h,
        rule=lambda m, h: - m.net_load[h] + 1e-6 <= big_m_constant * (1 - m.aux_imp_exp_binary_variable[h])
    )
    return

 
def add_imports_constraints( host, data: dict ):
    formulation = get_formulation(data, component='Imports')
    if formulation == IMPORTS_EXPORTS_WITHOUT_NET_LOAD_CONSTRAINTS:
        add_imports_constraints_without_net_load(host, data)
        return
    big_m_constant = 1e6 #TODO make a logic to get Big M constant from input data/parameters
    _add_imports_exports_capacity_constraint(host.imports, host.h)
    add_import_export_binary_variable(host, big_m_constant)
    

    host.imp_net_load_constraint = Constraint(
        host.h,
        rule=lambda m, h: m.imports.variable[h] <= m.aux_imp_exp_binary_variable[h] * host.demand.ts_parameter[h]
    )
    return


def add_exports_constraints( host, data: dict ):
    formulation = get_formulation(data, component='Exports')
    if formulation == IMPORTS_EXPORTS_WITHOUT_NET_LOAD_CONSTRAINTS:
        add_exports_constraints_without_net_load(host, data)
        return
    big_m_constant = 1e6 #TODO make a logic to get Big M constant from input data/parameters
    _add_imports_exports_capacity_constraint(host.exports, host.h)

    add_import_export_binary_variable(host, big_m_constant)
    max_capacity_exports = max( host.exports.ts_capacity_parameter[h] for h in host.h )
    host.exp_net_load_constraint = Constraint(
        host.h,
        rule=lambda m, h: m.exports.variable[h] <= ( 1 - m.aux_imp_exp_binary_variable[h] ) * max_capacity_exports
    )
    return


def add_imports_constraints_without_net_load(host, data: dict):
    """Pure-LP imports formulation: capacity bound only, no net-load coupling.

    Adds the hourly capacity inequality ``Pimp[t] <= cap[t]`` to
    ``model.imports`` and skips the big-M / binary auxiliary coupling used
    by ``CapacityPriceNetLoadFormulation``. The hourly cost contribution
    is provided by :func:`add_imports_exports_cost_expressions`.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Host model with ``model.h`` and ``model.imports`` already created.
    data : dict
        Loaded SDOM data dict (unused here, kept for dispatcher symmetry).
    """
    _add_imports_exports_capacity_constraint(host.imports, host.h)
    return


def add_exports_constraints_without_net_load(host, data: dict):
    """Pure-LP exports formulation: capacity bound only, no net-load coupling.

    Mirrors :func:`add_imports_constraints_without_net_load` for exports.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Host model with ``model.h`` and ``model.exports`` already created.
    data : dict
        Loaded SDOM data dict (unused here, kept for dispatcher symmetry).
    """
    _add_imports_exports_capacity_constraint(host.exports, host.h)
    return


####################################################################################|
# -----------------------------------= Add_costs -----------------------------------|
####################################################################################|
def add_imports_exports_cost(host):
    return host.imports.total_cost_expr - host.exports.total_cost_expr