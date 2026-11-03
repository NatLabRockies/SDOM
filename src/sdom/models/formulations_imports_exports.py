"""Build external trade capacities, price terms, and optional net-load coupling."""

from pyomo.core import Constraint, Expression, Var
from pyomo.environ import *

from ..constants import (
    IMPORTS_EXPORTS_NOT_MODEL,
    IMPORTS_EXPORTS_WITHOUT_NET_LOAD_CONSTRAINTS,
)
from ..io.formulations import get_formulation
from .models_utils import get_filtered_ts_parameter_dict

####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|

def add_import_export_ts_parameters( block, 
                                hourly_set, 
                                data: dict, 
                                key_ts: str,
                                key_col: str):
    """Add an hourly external-trade capacity or price parameter.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Imports or exports block.
    hourly_set : iterable
        Modeled hour indices.
    data : dict
        Loaded inputs containing the selected table with ``*Hour``.
    key_ts : str
        ``cap_imports`` / ``cap_exports`` creates ``ts_capacity_parameter``
        (MW); ``price_imports`` / ``price_exports`` creates
        ``ts_price_parameter`` (USD/MWh).
    key_col : str
        Value column in the selected table.

    Notes
    -----
    Other table keys are read but do not create a parameter. Missing hours
    are not filled. This builder does not scale or validate the input values.
    """
    # Time-series parameter data initialization
    filtered_selected_data = get_filtered_ts_parameter_dict(hourly_set, data, key_ts, key_col)
    if key_ts in ["cap_imports", "cap_exports"]:
        block.ts_capacity_parameter = Param( hourly_set, initialize = filtered_selected_data)
    elif key_ts in ["price_imports", "price_exports"]:
        block.ts_price_parameter = Param( hourly_set, initialize = filtered_selected_data)
    return


def add_imports_parameters(host, data: dict):
    """Add hourly import capacity (MW) and price (USD/MWh) parameters.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System host with ``h`` and an ``imports`` block.
    data : dict
        Loaded ``cap_imports`` / ``price_imports`` tables with value columns
        ``Imports`` / ``Imports_price``.
    """
    add_import_export_ts_parameters( host.imports, host.h, data, "cap_imports", "Imports")
    add_import_export_ts_parameters( host.imports, host.h, data, "price_imports", "Imports_price")
    return

def add_exports_parameters(host, data: dict):
    """Add hourly export capacity (MW) and price (USD/MWh) parameters.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System host with ``h`` and an ``exports`` block.
    data : dict
        Loaded ``cap_exports`` / ``price_exports`` tables with value columns
        ``Exports`` / ``Exports_price``.
    """
    add_import_export_ts_parameters( host.exports, host.h, data, "cap_exports", "Exports")
    add_import_export_ts_parameters( host.exports, host.h, data, "price_exports", "Exports_price")
    return



####################################################################################|
# ------------------------------------ Variables -----------------------------------|
####################################################################################|
def _add_generic_import_export_variables(block, *sets, domain=NonNegativeReals, initialize=0):
    """Add a trade variable indexed by the supplied sets in their given order.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Trade block receiving ``variable`` (normally MW).
    *sets : iterable
        Pyomo index sets, normally the hourly set.
    domain : pyomo.core.base.set.Set, optional
        Variable domain; default is ``NonNegativeReals``.
    initialize : float, optional
        Initial value at each index; default is zero.
    """
    block.variable = Var(*sets, domain=domain, initialize=initialize)
    return

def add_imports_variables(host):
    """Add nonnegative hourly external-import variables in MW.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System host with ``h`` and an ``imports`` block.
    """
    _add_generic_import_export_variables(host.imports, host.h, domain=NonNegativeReals, initialize=0)
    return


def add_exports_variables(host):
    """Add nonnegative hourly external-export variables in MW.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System host with ``h`` and an ``exports`` block.
    """
    _add_generic_import_export_variables(host.exports, host.h, domain=NonNegativeReals, initialize=0)
    return

####################################################################################|
# ----------------------------------- Expressions ----------------------------------|
####################################################################################|
def _add_imports_exports_cost_expressions(block, hourly_set, data: dict, component: str):
    r"""Attach a trade block's price-times-volume total or a disabled zero.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Imports or exports block with prices and enabled trade variables.
    hourly_set : iterable
        Modeled one-hour indices.
    data : dict
        Loaded inputs containing formulation selections.
    component : str
        ``"Imports"`` or ``"Exports"``.

    Notes
    -----
    .. math::

       Z^x=\begin{cases}
       \sum_{h\in\mathcal H}c^x_h x_h&\text{if enabled},\\
       0&\text{if NotModel}.
       \end{cases}

    :math:`x_h` is ``variable[h]`` (MW), and :math:`c^x_h` is
    ``ts_price_parameter[h]`` (USD/MWh). ``total_cost_expr`` is USD over
    the horizon. Export revenue is stored with this same algebraic sign;
    subtraction happens in :func:`add_imports_exports_cost`.
    """
    if get_formulation(data, component=component) != IMPORTS_EXPORTS_NOT_MODEL:
        block.total_cost_expr = Expression( rule = sum(block.ts_price_parameter[h] * block.variable[h] for h in hourly_set) )
    else:
        block.total_cost_expr = Expression( rule = 0 )
    return

def add_imports_exports_cost_expressions(host, data: dict):
    """Attach separate import expenditure and export revenue expressions.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System host with initialized imports/exports blocks.
    data : dict
        Loaded inputs containing trade formulation selections.

    Notes
    -----
    Each enabled block sums hourly price times traded MW for one-hour
    steps (USD). Disabled blocks receive a zero expression. Export revenue
    is not negated here; :func:`add_imports_exports_cost` subtracts it.
    """
    _add_imports_exports_cost_expressions(host.imports, host.h, data, 'Imports')
    _add_imports_exports_cost_expressions(host.exports, host.h, data, 'Exports')
    return


####################################################################################|
# ----------------------------------- Constraints ----------------------------------|
####################################################################################|
def _add_imports_exports_capacity_constraint(block, hourly_set):
    r"""Add an hourly capacity upper bound to one external-trade block.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Trade block with ``variable`` and ``ts_capacity_parameter``.
    hourly_set : iterable
        Modeled hour indices.

    Notes
    -----
    .. math::

       x_h\le\bar x_h\qquad(h\in\mathcal H).

    :math:`x_h` is ``variable[h]`` and :math:`\bar x_h` is
    ``ts_capacity_parameter[h]``, both in MW. Nonnegativity is supplied by
    the default trade variable domain, not by this upper-bound constraint.
    """
    block.capacity_constraint = Constraint(hourly_set, rule=lambda m,h: m.variable[h] <= m.ts_capacity_parameter[h] )
    return

def add_import_export_binary_variable(host, big_m_constant):
    r"""Add the shared net-load sign binary and its big-M constraints once.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System host with ``h`` and ``net_load[h]``.
    big_m_constant : float
        Big-M power bound in MW.

    Notes
    -----
    .. math::

       n_h\le Mz_h,\qquad -n_h+\varepsilon\le M(1-z_h),
       \qquad z_h\in\{0,1\},\quad\varepsilon=10^{-6}\ \mathrm{MW}.

    :math:`n_h` is ``net_load[h]`` (MW); :math:`z_h` is
    ``aux_imp_exp_binary_variable[h]``. Mode zero permits
    :math:`\varepsilon-M\le n_h\le0`; mode one requires
    :math:`\varepsilon\le n_h\le M`. Thus the small positive interval
    :math:`0<n_h<\varepsilon` is excluded. If the binary already exists,
    no variables or constraints are added or refreshed.
    """
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
    r"""Add import capacity limits and, when selected, net-load sign coupling.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System host with import variables/capacities, demand, and net load.
    data : dict
        Loaded inputs containing the Imports formulation selection.

    Notes
    -----
    The net-load-coupled path enforces

    .. math::

       0\le\iota_h\le\bar\iota_h,\qquad \iota_h\le z_h d_h.

    :math:`\iota_h` is ``imports.variable[h]``, :math:`\bar\iota_h` is
    import capacity, and :math:`d_h` is gross demand, all MW.
    :math:`z_h` is the net-load binary created by
    :func:`add_import_export_binary_variable` with :math:`M=10^6` MW.
    This gates imports by sign and gross demand, not net-load magnitude.
    ``WithoutNetLoadConstraints`` adds only the hourly capacity bound.
    """
    formulation = get_formulation(data, component='Imports')
    if formulation == IMPORTS_EXPORTS_WITHOUT_NET_LOAD_CONSTRAINTS:
        add_imports_constraints_without_net_load(host, data)
        return
    big_m_constant = 1e6 #TODO make a logic to get Big M constant from input data/parameters
    _add_imports_exports_capacity_constraint(host.imports, host.h)
    add_import_export_binary_variable(host, big_m_constant)
    

    # TODO: readability cleanup — use `m.demand.ts_parameter[h]` (instead of
    # `host.demand.ts_parameter[h]`) inside this lambda for naming consistency.
    host.imp_net_load_constraint = Constraint(
        host.h,
        rule=lambda m, h: m.imports.variable[h] <= m.aux_imp_exp_binary_variable[h] * host.demand.ts_parameter[h]
    )
    return


def add_exports_constraints( host, data: dict ):
    r"""Add export capacity limits and, when selected, net-load sign coupling.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System host with export variables/capacities and net load.
    data : dict
        Loaded inputs containing the Exports formulation selection.

    Notes
    -----
    The net-load-coupled path enforces

    .. math::

       0\le\xi_h\le\bar\xi_h,\qquad
       \xi_h\le(1-z_h)\max_{t\in\mathcal H}\bar\xi_t.

    :math:`\xi_h` is ``exports.variable[h]`` and :math:`\bar\xi_h` is
    hourly export capacity (MW). :math:`z_h` is the shared net-load binary
    created with :math:`M=10^6` MW. This gates exports by sign, not by
    surplus magnitude. ``WithoutNetLoadConstraints`` adds capacity bounds
    only, with no binary. The coupled path requires a nonempty horizon.
    """
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
    r"""Add import capacity bounds without net-load coupling or new binaries.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System host with ``h`` and initialized import variables/capacities.
    data : dict
        Loaded SDOM data dict (unused here, kept for dispatcher symmetry).

    Notes
    -----
    .. math::

       \iota_h\le\bar\iota_h\qquad(h\in\mathcal H).

    :math:`\iota_h` is ``imports.variable[h]`` and :math:`\bar\iota_h`
    is ``imports.ts_capacity_parameter[h]``, both MW. Variable domains
    provide nonnegativity. This builder does not prevent simultaneous
    imports and exports. Costs are attached separately.
    """
    _add_imports_exports_capacity_constraint(host.imports, host.h)
    return


def add_exports_constraints_without_net_load(host, data: dict):
    r"""Add export capacity bounds without net-load coupling or new binaries.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System host with ``h`` and initialized export variables/capacities.
    data : dict
        Loaded SDOM data dict (unused here, kept for dispatcher symmetry).

    Notes
    -----
    .. math::

       \xi_h\le\bar\xi_h\qquad(h\in\mathcal H).

    :math:`\xi_h` is ``exports.variable[h]`` and :math:`\bar\xi_h` is
    ``exports.ts_capacity_parameter[h]``, both MW. Variable domains provide
    nonnegativity. No surplus or simultaneous-trade restriction is added.
    """
    _add_imports_exports_capacity_constraint(host.exports, host.h)
    return


####################################################################################|
# -----------------------------------= Add_costs -----------------------------------|
####################################################################################|
def add_imports_exports_cost(host):
    r"""Return import expenditure less export revenue.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System host with both trade blocks' ``total_cost_expr`` expressions.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue
        Net trade cost in USD over the modeled horizon.

    Notes
    -----
    .. math::

       Z^{trade}=Z^{imp}-Z^{exp}
       =\sum_h(c^{imp}_h\iota_h-c^{exp}_h\xi_h).

    Prices are USD/MWh and trade is MW at one-hour steps. Disabled trade
    contributes zero through its existing cost expression. No annual
    scaling is applied.
    """
    return host.imports.total_cost_expr - host.exports.total_cost_expr