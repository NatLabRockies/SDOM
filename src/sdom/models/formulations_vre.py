"""Build PV and wind investment fractions, dispatch, curtailment, and costs."""

from pyomo.core import Var, Constraint, Expression
from pyomo.environ import Param, NonNegativeReals, quicksum
from ..constants import VRE_PROPERTIES_NAMES, MW_TO_KW
from .models_utils import compute_annualization_factor, generic_fixed_om_cost_expr_rule, generic_capex_cost_expr_rule, sum_installed_capacity_by_plants_set_expr_rule, add_generic_fixed_costs, add_generation_variables
import pandas as pd

####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|
def _add_vre_parameters(block, 
                      set_hours, 
                      data: dict,
                      key_filt_dict: str,
                      key_filt_min_dict: str,
                      key_comp_data: str,
                      key_cf_data: str ):
    """Add plant costs, capacity limits, and hourly VRE capacity factors.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        PV or wind block with initialized ``plants_set``.
    set_hours : iterable
        Modeled hour indices.
    data : dict
        Loaded inputs containing capacity mappings and plant/profile tables.
    key_filt_dict : str
        Key for the plant-to-maximum-capacity mapping (MW).
    key_filt_min_dict : str
        Key for the plant-to-minimum-capacity mapping (MW).
    key_comp_data : str
        Plant-property table key; identifiers are in ``sc_gid``.
    key_cf_data : str
        Capacity-factor table key; its first column contains hour indices,
        and plant columns use string identifiers.

    Notes
    -----
    Missing plant cost properties default to zero. Missing capacity-factor
    entries do not receive a default. ``CAPEX_M`` is USD/kW, ``FOM_M`` is
    USD/kW-year, and ``trans_cap_cost`` is USD/MW.
    """
    filtered_cap_solar_dict = data[key_filt_dict]
    filtered_min_cap_solar_dict = data[key_filt_min_dict]
    complete_solar_data = data[key_comp_data]
     # Initialize solar and wind parameters, with default values for missing data
    for property_name in VRE_PROPERTIES_NAMES:#['trans_cap_cost', 'CAPEX_M', 'FOM_M']:
        property_dict_solar = complete_solar_data.set_index('sc_gid')[property_name].to_dict()
        default_value = 0.0
        filtered_property_dict_solar = {k: property_dict_solar.get(k, default_value) for k in block.plants_set}
        block.add_component(f"{property_name}", Param(block.plants_set, initialize=filtered_property_dict_solar))

    block.max_capacity = Param( block.plants_set, initialize = filtered_cap_solar_dict )
    block.min_capacity = Param( block.plants_set, initialize = filtered_min_cap_solar_dict )


    # Capacity-factor initialization in one pass (no melt).
    cf_df = data[key_cf_data]
    hour_col = cf_df.columns[0]
    set_hours_list = list(set_hours)
    plants_set_list = [str(p) for p in block.plants_set]
    cf_indexed = cf_df.set_index(hour_col)
    present_cols = [c for c in plants_set_list if c in cf_indexed.columns]
    cf_filtered = cf_indexed.loc[cf_indexed.index.isin(set_hours_list), present_cols]
    cf_vre_dict = {
        (h, plant): value
        for (h, plant), value in cf_filtered.stack().items()
    }
    block.capacity_factor = Param( set_hours, block.plants_set, initialize = cf_vre_dict )


def add_vre_parameters(host, data: dict):
    r"""Add PV/wind parameters and their shared annualization factor.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with ``h`` and initialized PV/wind plant sets.
    data : dict
        Loaded solar/wind capacities, costs, and capacity factors, plus
        ``scalars`` entries ``r`` and ``LifeTimeVRE``.

    Notes
    -----
    For rate :math:`r` and shared VRE lifetime :math:`l^{vre}` in years,

    .. math::

       a^{vre}=\frac{r(1+r)^{l^{vre}}}{(1+r)^{l^{vre}}-1}.

    ``FCR_VRE`` stores :math:`a^{vre}` in inverse years.
    """
    #add solar parameters
    _add_vre_parameters(host.pv, 
                      host.h, 
                      data,
                      key_filt_dict = "filtered_cap_solar_dict",
                      key_filt_min_dict = "filtered_min_cap_solar_dict",
                      key_comp_data = "complete_solar_data",
                      key_cf_data = "cf_solar")
    
    _add_vre_parameters(host.wind, 
                      host.h, 
                      data,
                      key_filt_dict = "filtered_cap_wind_dict",
                      key_filt_min_dict = "filtered_min_cap_wind_dict",
                      key_comp_data = "complete_wind_data",
                      key_cf_data = "cf_wind")
    
    r = float(data["scalars"].loc["r"].Value)
    lifetime = float(data["scalars"].loc["LifeTimeVRE"].Value)
    fcr_vre = compute_annualization_factor(r, lifetime)
    host.FCR_VRE = Param(initialize=fcr_vre)


####################################################################################|
# ------------------------------------ Variables -----------------------------------|
####################################################################################|

def _add_vre_variables(block, set_hours):
    r"""Add VRE dispatch, curtailment, and bounded investment fractions.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        PV or wind block with plant sets and capacity-limit parameters.
    set_hours : iterable
        Modeled hour indices.

    Notes
    -----
    For generic VRE plant :math:`k` and hour :math:`h`,

    .. math::

       G_h,C_h\ge0,\qquad
       \underline F_k\le F_k\le1,\qquad
       \underline F_k=
       \begin{cases}
       \underline p_k/\bar p_k&\bar p_k>0,\\
       0&\bar p_k\le0.
       \end{cases}

    ``generation`` / ``curtailment`` are aggregate MW, not plant-indexed.
    ``capacity_fraction`` is continuous :math:`F_k`; ``min_capacity`` /
    ``max_capacity`` are :math:`\underline p_k` / :math:`\bar p_k` (MW).
    Dispatch and curtailment initialize to zero; fractions initialize to one.
    """
    add_generation_variables(block, set_hours, domain=NonNegativeReals, initialize=0)
    block.curtailment = Var(set_hours, domain=NonNegativeReals, initialize=0) # Curtailment 
    block.capacity_fraction = Var(
        block.plants_set,
        domain=NonNegativeReals,
        bounds=lambda model, plant: (
            float(model.min_capacity[plant] / model.max_capacity[plant])
            if model.max_capacity[plant] > 0
            else 0.0,
            1.0,
        ),
        initialize=1,
    ) #fraction of the maximum allowable capacity that will be installed

def add_vre_variables(host):
    """Add aggregate PV/wind dispatch, curtailment, and plant investment fractions.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized PV/wind capacity parameters and ``h``.

    Notes
    -----
    Each technology has hourly nonnegative generation and curtailment (MW).
    Plant investment is continuous between the minimum/maximum capacity
    ratio and one, with a zero lower fraction for nonpositive maxima.
    """
    _add_vre_variables(host.pv, host.h)
    _add_vre_variables(host.wind, host.h)

####################################################################################|
# ----------------------------------- Expressions ----------------------------------|
####################################################################################|


def _add_vre_expresions ( block, fcr_vre, set_hours ):
    r"""Attach installed-capacity, availability, energy, and cost expressions.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        PV or wind block with initialized parameters and variables.
    fcr_vre : float or pyomo.core.base.param.Param
        Shared capital annualization factor in inverse years.
    set_hours : iterable
        Modeled one-hour indices.

    Notes
    -----
    For generic VRE plant :math:`k`,

    .. math::

       \begin{aligned}
       P_k&=\bar p_kF_k,&P^{tot}&=\sum_kP_k,\\
       A_h&=G_h+C_h,&E^G&=\sum_hG_h,&E^C&=\sum_hC_h,\\
       Z^{cap}&=a^{vre}\sum_k(10^3\kappa_k+t_k)P_k,&
       Z^{FOM}&=\sum_k10^3\phi_kP_k.
       \end{aligned}

    ``max_capacity`` is :math:`\bar p_k` (MW), ``capacity_fraction`` is
    :math:`F_k`, and ``plant_installed_capacity`` is :math:`P_k` (MW).
    ``total_hourly_availability`` is :math:`A_h` (MW), with dispatched
    :math:`G_h` and curtailed :math:`C_h`; energy totals are MWh.
    :math:`a^{vre}` is ``fcr_vre``; ``CAPEX_M``, ``trans_cap_cost``, and
    ``FOM_M`` are :math:`\kappa_k`, :math:`t_k`, and :math:`\phi_k`
    (USD/kW, USD/MW, USD/kW-year). Cost expressions are USD/year.
    Availability equals capacity-factor-weighted capacity only once the
    separate :func:`vre_balance_rule` constraint is attached.
    """
    block.plant_installed_capacity = Expression(block.plants_set, rule=lambda block, k: block.max_capacity[k] * block.capacity_fraction[k] )
    block.total_installed_capacity = Expression( rule = sum_installed_capacity_by_plants_set_expr_rule )

    block.fixed_om_cost_expr = Expression( rule = generic_fixed_om_cost_expr_rule )
    block.capex_cost_expr = Expression (rule = lambda model: fcr_vre * generic_capex_cost_expr_rule(model) )

    block.total_hourly_availability = Expression(set_hours, rule=lambda block, h: block.generation[h] + block.curtailment[h])

    block.total_generation = Expression(rule=quicksum(block.generation[h] for h in set_hours))
    block.total_curtailment = Expression(rule=quicksum(block.curtailment[h] for h in set_hours))


def add_vre_expressions(host):
    """Attach capacity, availability, energy, and annual PV/wind cost expressions.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with ``FCR_VRE``, ``h``, and initialized PV/wind blocks.

    Notes
    -----
    Installed plant capacity is maximum capacity times investment fraction.
    Hourly availability is dispatched plus curtailed MW; annual CAPEX and
    fixed O&M use the shared VRE factor and plant-specific costs.
    """
    _add_vre_expresions(host.pv, host.FCR_VRE, host.h )
    _add_vre_expresions(host.wind, host.FCR_VRE, host.h )
    
    

####################################################################################|
# ------------------------------------ Add_costs -----------------------------------|
####################################################################################|

def add_vre_fixed_costs(host):
    r"""Return annual PV and wind capital plus fixed O&M costs.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized PV/wind cost expressions.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue
        Annual VRE fixed cost in USD/year; adds no variables.

    Notes
    -----
    .. math::

       Z^{vre,fixed}=Z^{pv,cap}+Z^{pv,FOM}
       +Z^{wind,cap}+Z^{wind,FOM}.

    Each term is an existing annual capital or fixed O&M expression.
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
    r"""Return the hourly VRE dispatch-plus-curtailment balance.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        PV or wind block with availability, capacity factors, and investments.
    h : int
        Modeled hour.

    Returns
    -------
    pyomo.core.expr.relational_expr.EqualityExpression
        Aggregate available output equal to capacity-factor-weighted investment.

    Notes
    -----
    .. math::

       G_h+C_h=\sum_{k\in\mathcal K^{vre}}a_{kh}\bar p_kF_k.

    All power terms are MW. ``total_hourly_availability[h]`` is
    :math:`G_h+C_h`; ``capacity_factor[h,k]`` is :math:`a_{kh}`;
    ``max_capacity[k]`` is :math:`\bar p_k`; and ``capacity_fraction[k]``
    is :math:`F_k`. For PV these correspond to :math:`\sigma_{ph}`,
    :math:`\bar p^{pv}_p`, :math:`F^{pv}_p`; for wind to
    :math:`\zeta_{wh}`, :math:`\bar p^{wind}_w`, :math:`F^{wind}_w`.
    """
    return block.total_hourly_availability[h] == quicksum(
        block.capacity_factor[h, k] * block.max_capacity[k] * block.capacity_fraction[k]
        for k in block.plants_set
    )


def add_vre_balance_constraints(host):
    """Add hourly PV and wind availability-balance constraints.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized PV/wind parameters and expressions.

    See Also
    --------
    vre_balance_rule : Dispatch plus curtailment equals available VRE power.
    """
    # Solar balance constraint
    host.pv.balance = Constraint(host.h, rule=vre_balance_rule)
    # Wind balance constraint
    host.wind.balance = Constraint(host.h, rule=vre_balance_rule)