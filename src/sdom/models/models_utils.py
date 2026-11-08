"""Provide shared parameter builders, cost expressions, and budget rules."""

from pyomo.environ import Param, NonNegativeReals
from pyomo.core import Var
from ..constants import MW_TO_KW


def compute_annualization_factor(rate: float, lifetime: float) -> float:
    r"""Compute the fixed-charge/capital-recovery factor as a float.

    Parameters
    ----------
    rate : float
        Discount/interest rate.
    lifetime : float
        Asset lifetime in years.

    Returns
    -------
    float
        Annualization factor in inverse years.

    Raises
    ------
    ZeroDivisionError
        If the denominator is zero, including zero rate or zero lifetime.

    Notes
    -----
    For dimensionless rate :math:`r` and lifetime :math:`l` in years,

    .. math::

       \operatorname{CRF}(l)=\frac{r(1+r)^l}{(1+r)^l-1}.

    Evaluates the expression directly without domain validation or a
    special case for the zero-rate limit.
    """
    return (rate * (1 + rate) ** lifetime) / ((1 + rate) ** lifetime - 1)


def build_annualization_factor_map(rate: float, lifetimes_by_key: dict) -> dict:
    r"""Build annualization factors for a keyed lifetime mapping.

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

    Raises
    ------
    TypeError, ValueError
        If a lifetime cannot be converted to a float.
    ZeroDivisionError
        If an annualization-factor denominator is zero.

    Notes
    -----
    For each key :math:`k` with lifetime :math:`l_k` in years,

    .. math::

       a_k=\operatorname{CRF}(l_k)=\frac{r(1+r)^{l_k}}{(1+r)^{l_k}-1}.

    The dimensionless rate :math:`r` is shared. Factors have inverse-year units.
    """
    return {
        key: compute_annualization_factor(rate, float(lifetime))
        for key, lifetime in lifetimes_by_key.items()
    }


####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|
def get_filtered_ts_parameter_dict( hourly_set, data: dict, key_ts: str, key_col: str):
    """Extract time-series values for available modeled hours.

    Parameters
    ----------
    hourly_set : iterable
        Modeled hour indices.
    data : dict
        Loaded inputs containing the selected DataFrame.
    key_ts : str
        DataFrame key, such as ``load_data``.
    key_col : str
        Value column, such as ``Load``.

    Returns
    -------
    dict
        Hour-to-value mapping for the intersection of modeled hours and the
        table's ``*Hour`` column. Missing hours are omitted, not filled.

    Raises
    ------
    KeyError
        If the table, ``*Hour`` column, or requested value column is absent.
    """
    selected_data          = data[key_ts].set_index('*Hour')[key_col].to_dict()
    filtered_selected_data = {h: selected_data[h] for h in hourly_set if h in selected_data}
    return filtered_selected_data

def add_alpha_parameter(block, data, key_scalars: str):
    """Add an activation scalar unless already present or unrequested.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Block receiving ``alpha``.
    data : dict
        Loaded inputs containing the ``scalars`` DataFrame.
    key_scalars : str
        Scalar row to convert to float. An empty string skips creation.

    Notes
    -----
    Existing ``alpha`` attributes are preserved. Values are typically zero
    or one, but this helper does not enforce a binary domain.
    """
    if not hasattr(block, "alpha") and key_scalars != "":
        block.alpha = Param( initialize = float(data["scalars"].loc[key_scalars].Value) )

def add_alpha_and_ts_parameters( block, 
                                hourly_set, 
                                data: dict, 
                                key_scalars: str, 
                                key_ts: str,
                                key_col: str):
    """Add a time-series parameter and, when requested, an activation scalar.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Block receiving ``ts_parameter`` and optionally ``alpha``.
    hourly_set : iterable
        Modeled hour indices.
    data : dict
        Loaded inputs containing the time-series and scalar tables.
    key_scalars : str
        Activation-scalar row; an empty string skips ``alpha`` creation.
    key_ts : str
        Time-series DataFrame key.
    key_col : str
        Value column in the time-series table.

    Notes
    -----
    Stores the unscaled profile. Consumers apply ``alpha`` where applicable.
    """
    # Control parameter to activate certain device.
    add_alpha_parameter(block, data, key_scalars)

    # Time-series parameter data initialization
    filtered_selected_data = get_filtered_ts_parameter_dict(hourly_set, data, key_ts, key_col)
    block.ts_parameter = Param( hourly_set, initialize = filtered_selected_data)


def add_budget_parameter(block, formulation, valid_formulation_to_budget_map: dict):
    """Add the selected fixed budget-period length unless already present.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Block receiving ``budget_scalar``.
    formulation : str
        Formulation key in the supplied mapping.
    valid_formulation_to_budget_map : dict
        Formulation-to-length mapping in one-hour steps.

    Raises
    ------
    KeyError
        If a new parameter is needed and the formulation is absent.

    Notes
    -----
    Preserves existing ``budget_scalar`` attributes. Period lengths are
    fixed, not derived from calendar-month boundaries.
    """
    if not hasattr(block, "budget_scalar"):
        block.budget_scalar = Param( initialize = valid_formulation_to_budget_map[formulation])

def add_upper_bound_paramenters(block, 
                                hourly_set, 
                                data, 
                                key_ts: str = "large_hydro_max", 
                                key_col: str = "LargeHydro"):
    """Add the unscaled hourly upper-bound parameter.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Block receiving ``ts_parameter_upper_bound``.
    hourly_set : iterable
        Modeled hour indices.
    data : dict
        Loaded inputs containing the selected DataFrame with ``*Hour``.
    key_ts : str, optional
        Upper-bound table key; default is ``"large_hydro_max"``.
    key_col : str, optional
        Value column; default is ``"LargeHydro"`` (MW).

    Notes
    -----
    Missing hours are omitted from initialization. Declares parameters
    only, not constraints on generation.
    """
    selected_data          = data[key_ts].set_index('*Hour')[key_col].to_dict()
    filtered_selected_data = {h: selected_data[h] for h in hourly_set if h in selected_data}
    block.ts_parameter_upper_bound = Param( hourly_set, initialize = filtered_selected_data)

def add_lower_bound_paramenters(block, 
                                hourly_set, 
                                data: dict, 
                                key_ts: str = "large_hydro_min", 
                                key_col: str = "LargeHydro"):
    """Add the unscaled hourly lower-bound parameter.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Block receiving ``ts_parameter_lower_bound``.
    hourly_set : iterable
        Modeled hour indices.
    data : dict
        Loaded inputs containing the selected DataFrame with ``*Hour``.
    key_ts : str, optional
        Lower-bound table key; default is ``"large_hydro_min"``.
    key_col : str, optional
        Value column; default is ``"LargeHydro"`` (MW).

    Notes
    -----
    Missing hours are omitted from initialization. Declares parameters
    only, not constraints on generation.
    """
    selected_data          = data[key_ts].set_index('*Hour')[key_col].to_dict()
    filtered_selected_data = {h: selected_data[h] for h in hourly_set if h in selected_data}
    block.ts_parameter_lower_bound = Param( hourly_set, initialize = filtered_selected_data)

####################################################################################|
# ------------------------------------ Variables -----------------------------------|
####################################################################################|
def add_generation_variables(block, *sets, domain=NonNegativeReals, initialize=0):
    """Add generation variables indexed by the supplied sets in their given order.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Block receiving ``generation`` (normally MW).
    *sets : iterable
        Index sets, such as hours or hours followed by plant identifiers.
    domain : pyomo.core.base.set.Set, optional
        Variable domain; default is ``NonNegativeReals``.
    initialize : float, optional
        Initial value at every index; default is zero.

    Examples
    --------
    >>> from pyomo.environ import ConcreteModel, Set
    >>> block = ConcreteModel()
    >>> block.h = Set(initialize=[1, 2])
    >>> add_generation_variables(block, block.h)
    >>> list(block.generation)
    [1, 2]
    """
    block.generation = Var(*sets, domain=domain, initialize=initialize)

# def add_generation_variables(block, set_hours, initialize=0):
#     block.generation = Var(set_hours, domain=NonNegativeReals, initialize=initialize)



####################################################################################|
# ----------------------------------- Expressions ----------------------------------|
####################################################################################|

def sum_installed_capacity_by_plants_set_expr_rule( block ):
    r"""Return total installed capacity across the block's plants.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Block with ``plants_set`` and ``plant_installed_capacity``.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue or int
        Total installed MW; zero for an empty plant set.

    Notes
    -----
    .. math::

       P^{tot}=\sum_{k\in\mathcal K}P_k.

    :math:`\mathcal K` is ``plants_set`` and :math:`P_k` is
    ``plant_installed_capacity[k]`` in MW, a variable or expression.
    """
    return sum( block.plant_installed_capacity[plant] for plant in block.plants_set )
 

def generic_fixed_om_cost_expr_rule( block ):
    r"""Return total annual fixed operation and maintenance costs.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Block with ``FOM_M``, ``plant_installed_capacity``, and ``plants_set``.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue or int
        Annual fixed O&M in USD/year; zero for an empty plant set.

    Notes
    -----
    .. math::

       Z^{FOM}=\sum_{k\in\mathcal K}10^3\phi_k P_k.

    :math:`P_k` is installed MW and :math:`\phi_k` is ``FOM_M[k]`` in
    USD/kW-year. ``MW_TO_KW`` supplies the :math:`10^3` conversion.
    """
    return sum( ( MW_TO_KW * block.FOM_M[k]) * block.plant_installed_capacity[k] for k in block.plants_set )


def generic_capex_cost_expr_rule( block ):
    r"""Return capital costs before applying an annualization factor.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Block with ``CAPEX_M``, ``trans_cap_cost``,
        ``plant_installed_capacity``, and ``plants_set``.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue or int
        Unannualized capital cost in USD; zero for an empty plant set.

    Notes
    -----
    .. math::

       C^{cap}=\sum_{k\in\mathcal K}(10^3\kappa_k+t_k)P_k.

    :math:`\kappa_k` is ``CAPEX_M[k]`` (USD/kW), :math:`t_k` is
    ``trans_cap_cost[k]`` (USD/MW), and :math:`P_k` is installed MW.
    No FCR is applied here; the VRE caller supplies a shared factor.
    """
    return sum( ( (MW_TO_KW * block.CAPEX_M[k] + block.trans_cap_cost[k]))\
                                         * block.plant_installed_capacity[k] for k in block.plants_set )


def different_fcr_capex_cost_expr_rule( block ):
    r"""Return annualized capital costs using plant-specific fixed-charge rates.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Block with ``FCR``, ``CAPEX_M``, ``trans_cap_cost``,
        ``plant_installed_capacity``, and ``plants_set``.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue or int
        Annual capital cost in USD/year; zero for an empty plant set.

    Notes
    -----
    .. math::

       Z^{cap}=\sum_{k\in\mathcal K}a_k(10^3\kappa_k+t_k)P_k.

    :math:`a_k` is ``FCR[k]`` (inverse years), :math:`\kappa_k` is
    ``CAPEX_M[k]`` (USD/kW), :math:`t_k` is ``trans_cap_cost[k]``
    (USD/MW), and :math:`P_k` is installed MW.
    """
    return sum( ( block.FCR[k] * (MW_TO_KW * block.CAPEX_M[k] + block.trans_cap_cost[k]))\
                                         * block.plant_installed_capacity[k] for k in block.plants_set )


####################################################################################|
# ----------------------------------- Constraints ----------------------------------|
####################################################################################|

def generic_budget_rule(block, hhh):
    r"""Return an energy-budget upper bound for a fixed-length period.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Block with ``generation``, ``ts_parameter``, and integer-valued
        ``budget_scalar`` (number of one-hour steps per period).
    hhh : int
        One-based period index.

    Returns
    -------
    pyomo.core.expr.relational_expr.InequalityExpression
        Generation bounded by the unscaled reference energy for the period.

    Notes
    -----
    For period :math:`b=\mathtt{hhh}` and length :math:`B`,

    .. math::

       \mathcal H_b=\{(b-1)B+1,\ldots,bB\},\qquad
    \sum_{h\in\mathcal H_b}G_h\le\sum_{h\in\mathcal H_b}\rho_h.

    :math:`G_h` is ``generation[h]`` and :math:`\rho_h` is
    ``ts_parameter[h]``, both in MW; one-hour sums are MWh. No activation
    scalar is applied. All hours of the period must exist; partial periods
    are not clipped and calendar-month boundaries are not used.
    """
    budget_n_hours = block.budget_scalar
    start = ( (hhh - 1) * budget_n_hours ) + 1
    end = hhh * budget_n_hours + 1
    list_budget = list(range(start, end))
    return sum(block.generation[h] for h in list_budget) <= sum(block.ts_parameter[h] for h in list_budget)

####################################################################################|
# -----------------------------------= Add_costs -----------------------------------|
####################################################################################|

def add_generic_fixed_costs(block):
    r"""Return the sum of an existing block's annual fixed-cost expressions.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Block with annualized ``capex_cost_expr`` and ``fixed_om_cost_expr``.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue
        Annual capital plus fixed O&M cost in USD/year.

    Notes
    -----
    .. math::

       Z^{fixed}=Z^{cap}+Z^{FOM}.

    These are existing expressions, not newly declared variables.
    Annualization must already be included in ``capex_cost_expr``.
    """
    return block.capex_cost_expr + block.fixed_om_cost_expr