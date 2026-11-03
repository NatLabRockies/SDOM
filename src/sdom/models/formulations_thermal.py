"""Build thermal balancing-unit capacity, dispatch, and annual cost terms."""

import logging

from pyomo.core import Constraint, Expression, Var
from pyomo.environ import NonNegativeReals, Param, Set, UnitInterval, quicksum

from ..constants import NO_RAMPS_MIN_DISPATCH_FORMULATION, THERMAL_PROPERTIES_NAMES
from ..io.formulations import get_formulation
from ..io.validation import validate_thermal_min_dispatch
from .models_utils import (
    add_generation_variables,
    add_generic_fixed_costs,
    build_annualization_factor_map,
    different_fcr_capex_cost_expr_rule,
    generic_fixed_om_cost_expr_rule,
    sum_installed_capacity_by_plants_set_expr_rule,
)


def initialize_thermal_sets(block, data):
    """Initialize thermal plant identifiers and property names.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Thermal block receiving ``plants_set`` and ``properties_set``.
    data : dict
        Loaded inputs containing ``thermal_data`` with ``Plant_id`` values
        converted to strings. Selected units are logged at INFO level.
    """
    # Initialize THERMAL properties
    block.plants_set = Set( initialize = data['thermal_data']['Plant_id'].astype(str).tolist() )
    block.properties_set = Set( initialize = THERMAL_PROPERTIES_NAMES )
    logging.info(f"Thermal balancing units being considered: {list(block.plants_set)}")

####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|

def _add_thermal_parameters(block, df):
    """Add plant-specific thermal cost, fuel, and performance parameters.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Thermal block with initialized plant and property sets.
    df : pandas.DataFrame
        Thermal properties indexed by ``Plant_id``. ``FuelCost`` is USD/MMBtu,
        ``HeatRate`` is MMBtu/MWh, ``Capex`` is USD/kW, ``FOM`` is USD/kW-year,
        and ``VOM`` is USD/MWh.

    Notes
    -----
    Copies the full property table to ``data`` and adds dedicated cost
    parameters. ``trans_cap_cost`` is initialized to zero for every unit.
    """
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


def _add_thermal_min_dispatch_fraction_parameters(host, data, *, df):
    r"""Validate and add immutable hourly thermal minimum-dispatch fractions.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with effective hourly and thermal plant sets.
    data : dict
        Enabled hourly profile and static thermal properties.
    df : pandas.DataFrame
        Thermal properties indexed by Plant_id, normalized in place to string
        identity and numeric capacity bounds before static parameter creation.

    Raises
    ------
    ValueError
        If profile identity, bounds, hours, fractions, or coverage are invalid.
        Empty thermal fleets require an hour-only input table.

    Notes
    -----
    ``min_dispatch_fraction[h,k]`` is the dimensionless coefficient
    :math:`q^{bal}_{kh}\in[0,1]`, indexed by effective hour and thermal plant.
    Full supplied coverage is validated; only modeled hours are initialized.
    """
    fractions = validate_thermal_min_dispatch(data, n_hours=len(host.h))
    df.index = df.index.astype(str)
    df[["MinCapacity", "MaxCapacity"]] = df[["MinCapacity", "MaxCapacity"]].astype(float)
    values = fractions.iloc[:len(host.h), 1:].to_numpy()
    columns = {plant: i for i, plant in enumerate(fractions.columns[1:])}
    host.thermal.min_dispatch_fraction = Param(
        host.h, host.thermal.plants_set, within=UnitInterval,
        initialize=lambda b, h, k: float(values[h - 1, columns[k]]),
    )


def add_thermal_parameters(host, data: dict):
    r"""Add thermal properties and unit-specific annualization factors.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized thermal sets.
    data : dict
        Loaded ``thermal_data`` with plant identifiers and lifetimes, plus
        ``scalars`` containing discount rate ``r``.

    Notes
    -----
    For balancing unit :math:`k` with lifetime :math:`l_k` in years,

    .. math::

       a_k=\operatorname{CRF}(l_k)=\frac{r(1+r)^{l_k}}{(1+r)^{l_k}-1}.

    :math:`a_k` is ``thermal.FCR[k]`` in inverse years. Cost and performance
    units are described by :func:`_add_thermal_parameters`.

    Only ``NoRampsMinDispatchFormulation`` adds immutable dimensionless
    ``min_dispatch_fraction[h,k]`` (:math:`q^{bal}_{kh}\in[0,1]`), an
    hour-by-plant table covering the effective ``host.h``. Empty fleets
    require hour-only input. Invalid identity, bounds, values, or coverage
    raise ``ValueError`` before parameter construction.
    """
    df = data["thermal_data"].set_index("Plant_id")
    if get_formulation(data, "Thermal") == NO_RAMPS_MIN_DISPATCH_FORMULATION:
        _add_thermal_min_dispatch_fraction_parameters(host, data, df=df)
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
    r"""Add thermal capacity and dispatch variables with investment bounds.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized thermal sets and property parameters.

    Notes
    -----
    For unit :math:`k` and hour :math:`h`,

    .. math::

       P^{bal}_k\ge0,\qquad
       \underline p^{bal}_k\le P^{bal}_k\le\bar p^{bal}_k,\qquad
       G^{bal}_{kh}\ge0.

    :math:`P^{bal}` is ``plant_installed_capacity`` (MW),
    :math:`G^{bal}` is ``generation[h,k]`` (MW), and the capacity bounds
    are ``MinCapacity`` / ``MaxCapacity``. Hourly dispatch limits are added
    separately by :func:`add_thermal_constraints`.
    """
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
    r"""Return total thermal generation using the legacy ``GenCC`` variable.

    Parameters
    ----------
    m : pyomo.core.base.block.BlockData
        Legacy host exposing ``GenCC[h,bu]``, ``h``, and ``thermal.plants_set``.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue or int
        Modeled-horizon thermal energy in MWh for one-hour steps.

    Notes
    -----
    .. math::

       E^{bal}=\sum_{h\in\mathcal H}\sum_{k\in\mathcal K}G^{CC}_{hk}.

    :math:`G^{CC}_{hk}` is ``m.GenCC[h,k]`` (MW). This legacy helper does
    not use ``thermal.generation``; current thermal expressions are built
    by :func:`add_thermal_expressions`.
    """
    return sum(m.GenCC[h, bu] for h in m.h for bu in m.thermal.plants_set)

def _add_thermal_expressions(block, set_hours):
    r"""Attach thermal energy, capacity, and annual/dispatch cost expressions.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Thermal block with initialized parameters and variables.
    set_hours : iterable
        Modeled one-hour dispatch indices.

    Notes
    -----
    .. math::

       \begin{aligned}
       E^{bal}_k&=\sum_hG^{bal}_{kh},&
       E^{bal}&=\sum_kE^{bal}_k,&P^{bal,tot}&=\sum_kP^{bal}_k,\\
       Z^{bal,FOM}&=\sum_k10^3\phi_kP^{bal}_k,&
       Z^{bal,cap}&=\sum_ka_k(10^3\kappa_k+t_k)P^{bal}_k,\\
       Z^{fuel}&=\sum_k c^{fuel}_k HR_k E^{bal}_k,&
       Z^{VOM}&=\sum_k\psi_k E^{bal}_k.
       \end{aligned}

    ``generation[h,k]`` is :math:`G^{bal}_{kh}` (MW); energy sums are MWh.
    Installed capacity :math:`P^{bal}_k` is MW. ``FOM_M`` /
    ``CAPEX_M`` are :math:`\phi_k` / :math:`\kappa_k` in USD/kW-year /
    USD/kW; ``FCR`` is :math:`a_k` in inverse years and ``trans_cap_cost``
    is :math:`t_k` in USD/MW (zero here). Fixed costs are USD/year.
    ``fuel_price`` is :math:`c^{fuel}_k` in USD/MMBtu, ``heat_rate`` is
    :math:`HR_k` in MMBtu/MWh, and ``VOM_M`` is :math:`\psi_k` in USD/MWh.
    Fuel and VOM totals are USD over the modeled horizon, without annual scaling.
    """
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
    """Attach thermal capacity, generation, and cost expressions to the host.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with ``h`` and initialized thermal parameters/variables.

    Notes
    -----
    Uses ``thermal.generation[h,k]`` for energy and fuel/VOM totals, not the
    legacy ``GenCC`` attribute used by :func:`total_thermal_expr_rule`.
    Annual capital costs use plant-specific ``thermal.FCR`` values.
    """
    _add_thermal_expressions(host.thermal, host.h)
    


####################################################################################|
# ----------------------------------- Constraints ----------------------------------|
####################################################################################|

def add_thermal_constraints( host ):
    r"""Limit hourly thermal dispatch to each unit's installed capacity.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with hourly thermal dispatch and capacity variables.

    Notes
    -----
    .. math::

       G^{bal}_{kh}\le P^{bal}_k
       \qquad(k\in\mathcal K,\ h\in\mathcal H).

    ``generation[h,k]`` and ``plant_installed_capacity[k]`` are MW.
    Nonnegativity is supplied by the variable domains. No commitment,
    ramping, or outage constraint is introduced. Also calls
    :func:`add_thermal_min_dispatch_constraints` when its validated fraction
    parameter exists, keeping both dispatch bounds within the same profiled
    build step. Legacy models have no fraction parameter and add no floor.
    """
    set_hours = host.h
    # Capacity of the backup generation
    host.thermal.capacity_generation_constraint = Constraint( set_hours, host.thermal.plants_set, rule = lambda m,h,bu: m.plant_installed_capacity[bu] >= m.generation[h,bu]  )
    add_thermal_min_dispatch_constraints(host)


def add_thermal_min_dispatch_constraints(host):
    r"""Add hourly must-run floors only for NoRampsMinDispatchFormulation.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with thermal parameters, capacity and dispatch variables.

    Notes
    -----
    .. math::

       G^{bal}_{kh}\ge q^{bal}_{kh}P^{bal}_k,\quad q^{bal}_{kh}\in[0,1]
       \qquad(k\in\mathcal K,\ h\in\mathcal H).

    ``generation[h,k]`` is :math:`G^{bal}_{kh}` (MW);
    ``plant_installed_capacity[k]`` is total optimized :math:`P^{bal}_k`
    (MW), including expansion. ``min_dispatch_fraction[h,k]`` is the
    dimensionless input :math:`q^{bal}_{kh}`. These local symbols apply on
    each area host as well. Constant coefficients keep the constraint linear;
    no commitment or ramping is introduced. Zero capacity implies zero output;
    zero coefficients skip redundant rows. Empty fleets add no inequalities.
    The validated fraction parameter, created only for the enabled formulation,
    controls activation. Legacy dispatch creates no floor component.

    For a feasible solution with positive capacity, the modeled-horizon
    capacity factor satisfies
    :math:`CF^{bal}_k=\sum_hG^{bal}_{kh}/(|\mathcal H|P^{bal}_k)
    \ge\sum_hq^{bal}_{kh}/|\mathcal H|`.
    This neither mandates investment nor guarantees an unmodeled annual factor.
    """
    if not hasattr(host.thermal, "min_dispatch_fraction"):
        return

    def floor(b, h, k):
        q = b.min_dispatch_fraction[h, k]
        return b.generation[h, k] >= q * b.plant_installed_capacity[k] if q > 0 else Constraint.Skip

    host.thermal.min_dispatch_constraint = Constraint(host.h, host.thermal.plants_set, rule=floor)


####################################################################################|
# -----------------------------------= Add_costs -----------------------------------|
####################################################################################|
def add_thermal_fixed_costs(host):
    r"""Return thermal annual capital and fixed O&M costs.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized thermal cost expressions.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue
        Annual fixed cost in USD/year; adds no variables.

    Notes
    -----
    .. math::

       Z^{bal,fixed}=Z^{bal,cap}+Z^{bal,FOM}.

    The terms are the existing ``capex_cost_expr`` and ``fixed_om_cost_expr``.
    """
    return (
        add_generic_fixed_costs(host.thermal)
    )

def add_thermal_variable_costs(host):
    r"""Return modeled-horizon thermal fuel and variable O&M costs.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized thermal fuel and VOM expressions.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue
        Modeled-horizon variable cost in USD.

    Notes
    -----
    .. math::

       Z^{bal,var}=\sum_k(c^{fuel}_kHR_k+\psi_k)\sum_hG^{bal}_{kh}.

    Fuel price is USD/MMBtu, heat rate is MMBtu/MWh, VOM is USD/MWh,
    and dispatch is MW at one-hour steps. No annual scaling is applied.
    """
    return (
        host.thermal.total_fuel_cost_expr + host.thermal.total_vom_cost_expr
    )
