from pyomo.core import Var, Expression, Constraint
from pyomo.environ import *
from .models_utils import get_filtered_ts_parameter_dict
from ..io_manager import get_formulation

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


def add_imports_parameters(model, data: dict):
    add_import_export_ts_parameters( model.imports, model.h, data, "cap_imports", "Imports")
    add_import_export_ts_parameters( model.imports, model.h, data, "price_imports", "Imports_price")
    return

def add_exports_parameters(model, data: dict):
    add_import_export_ts_parameters( model.exports, model.h, data, "cap_exports", "Exports")
    add_import_export_ts_parameters( model.exports, model.h, data, "price_exports", "Exports_price")
    return



####################################################################################|
# ------------------------------------ Variables -----------------------------------|
####################################################################################|
def _add_generic_import_export_variables(block, *sets, domain=NonNegativeReals, initialize=0):
    block.variable = Var(*sets, domain=domain, initialize=initialize)
    return

def add_imports_variables(model):
    _add_generic_import_export_variables(model.imports, model.h, domain=NonNegativeReals, initialize=0)
    return


def add_exports_variables(model):
    _add_generic_import_export_variables(model.exports, model.h, domain=NonNegativeReals, initialize=0)
    return

####################################################################################|
# ----------------------------------- Expressions ----------------------------------|
####################################################################################|
def _add_imports_exports_cost_expressions(block, hourly_set, data: dict, component: str):
    if get_formulation(data, component=component) != "NotModel":
        block.total_cost_expr = Expression( rule = sum(block.ts_price_parameter[h] * block.variable[h] for h in hourly_set) )
    else:
        block.total_cost_expr = Expression( rule = 0 )
    return

def add_imports_exports_cost_expressions(model, data: dict):
   
    _add_imports_exports_cost_expressions(model.imports, model.h, data, 'Imports')
    _add_imports_exports_cost_expressions(model.exports, model.h, data, 'Exports')
    return


####################################################################################|
# ----------------------------------- Constraints ----------------------------------|
####################################################################################|
def _add_imports_exports_capacity_constraint(block, hourly_set):
    block.capacity_constraint = Constraint(hourly_set, rule=lambda m,h: m.variable[h] <= m.ts_capacity_parameter[h] )
    return

def add_import_export_binary_variable(model, big_m_constant):

    if hasattr(model, 'aux_imp_exp_binary_variable'):
        return
    
    model.aux_imp_exp_binary_variable = Var(model.h, domain=Binary, initialize=0)
    
    model.imp_exp_aux_bigM_constraint_positive = Constraint(
        model.h,
        rule=lambda m, h: m.net_load[h] <= big_m_constant * m.aux_imp_exp_binary_variable[h]
    )
    model.imp_exp_aux_bigM_constraint_negative = Constraint(
        model.h,
        rule=lambda m, h: - m.net_load[h] + 1e-6 <= big_m_constant * (1 - m.aux_imp_exp_binary_variable[h])
    )
    return

 
def add_imports_constraints( model, data: dict ):
    formulation = get_formulation(data, component='Imports')
    if formulation == "WithoutNetLoadConstraints":
        add_imports_constraints_without_net_load(model, data)
        return
    big_m_constant = 1e6 #TODO make a logic to get Big M constant from input data/parameters
    _add_imports_exports_capacity_constraint(model.imports, model.h)
    add_import_export_binary_variable(model, big_m_constant)
    

    model.imp_net_load_constraint = Constraint(
        model.h,
        rule=lambda m, h: m.imports.variable[h] <= m.aux_imp_exp_binary_variable[h] * model.demand.ts_parameter[h]
    )
    return


def add_exports_constraints( model, data: dict ):
    formulation = get_formulation(data, component='Exports')
    if formulation == "WithoutNetLoadConstraints":
        add_exports_constraints_without_net_load(model, data)
        return
    big_m_constant = 1e6 #TODO make a logic to get Big M constant from input data/parameters
    _add_imports_exports_capacity_constraint(model.exports, model.h)

    add_import_export_binary_variable(model, big_m_constant)
    max_capacity_exports = max( model.exports.ts_capacity_parameter[h] for h in model.h )
    model.exp_net_load_constraint = Constraint(
        model.h,
        rule=lambda m, h: m.exports.variable[h] <= ( 1 - m.aux_imp_exp_binary_variable[h] ) * max_capacity_exports
    )
    return


def add_imports_constraints_without_net_load(model, data: dict):
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
    _add_imports_exports_capacity_constraint(model.imports, model.h)
    return


def add_exports_constraints_without_net_load(model, data: dict):
    """Pure-LP exports formulation: capacity bound only, no net-load coupling.

    Mirrors :func:`add_imports_constraints_without_net_load` for exports.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Host model with ``model.h`` and ``model.exports`` already created.
    data : dict
        Loaded SDOM data dict (unused here, kept for dispatcher symmetry).
    """
    _add_imports_exports_capacity_constraint(model.exports, model.h)
    return


####################################################################################|
# -----------------------------------= Add_costs -----------------------------------|
####################################################################################|
def add_imports_exports_cost(model):
    return model.imports.total_cost_expr - model.exports.total_cost_expr