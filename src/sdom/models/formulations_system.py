"""Build copperplate system costs, net load, and energy-share constraints."""

from pyomo.core import Constraint, Expression
from pyomo.environ import quicksum

from ..common.utilities import parse_finite_float
from ..constants import HYDRO_FORMULATION_METADATA
from ..io.formulations import get_formulation
from .formulations_imports_exports import add_imports_exports_cost
from .formulations_storage import add_storage_fixed_costs, add_storage_variable_costs
from .formulations_thermal import add_thermal_fixed_costs, add_thermal_variable_costs
from .formulations_vre import add_vre_fixed_costs

####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|



####################################################################################|
# ------------------------------- Objective Function -------------------------------|
####################################################################################|

def _curtailment_rate(scalars, parameter: str) -> float:
    """Read an optional finite rate, rejecting duplicate or malformed entries."""
    entries = scalars.loc[scalars.index == parameter, "Value"]
    if entries.empty:
        return 0.0
    if len(entries) != 1:
        raise ValueError(f"{parameter} must appear at most once in scalars.")
    return parse_finite_float(
        entries.iloc[0], error_message=f"{parameter} must be numeric and finite."
    )


def add_curtailment_cost_expressions(host, data) -> None:
    """Attach signed modeled-horizon curtailment costs to each technology.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized VRE expressions and hydro dispatch.
    data : dict
        Inputs with optional global scalar rates in USD/MWh and hydro metadata.

    Raises
    ------
    ValueError
        If a supplied rate is duplicate, nonnumeric, or nonfinite.

    Notes
    -----
    Missing/zero rates omit the decision-dependent term. Inactive contributions
    are constant zero expressions. Negative rates reward curtailment.
    Upper-bound hydro uses the unscaled budget profile over the complete
    effective horizon, retaining its constant availability term. One-hour MW
    sums are MWh; no annualization, alpha scaling, or reporting tolerance applies.
    """
    solar, wind, hydro = (
        _curtailment_rate(data["scalars"], parameter)
        for parameter in ("SolarCurtailmentCost", "WindCurtailmentCost", "HydroCurtailmentCost")
    )
    for block, rate in ((host.pv, solar), (host.wind, wind)):
        block.curtailment_cost_expr = Expression(
            expr=rate * block.total_curtailment if rate != 0 and len(block.plants_set) else 0.0
        )
    metadata = HYDRO_FORMULATION_METADATA[get_formulation(data, component="hydro")]
    host.hydro.curtailment_cost_expr = Expression(
        expr=hydro * quicksum(
            host.hydro.ts_parameter[h] - host.hydro.generation[h] for h in host.h
        ) if hydro != 0 and metadata.budget_sense == "upper_bound" else 0.0
    )


def curtailment_cost_rule(host):
    """Return the sum of the three existing technology cost expressions.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with curtailment cost expressions.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue
        Signed curtailment cost in USD over the effective modeled horizon.
    """
    return (
        host.pv.curtailment_cost_expr
        + host.wind.curtailment_cost_expr
        + host.hydro.curtailment_cost_expr
    )


def objective_rule(model):
    r"""Return the copperplate investment-and-dispatch objective expression.

    Parameters
    ----------
    model : pyomo.core.base.block.BlockData
        Host with initialized VRE, storage, thermal, and trade cost expressions.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue
        Cost expression used by the minimizing objective.

    Notes
    -----
    .. math::

       Z=Z^{vre,fixed}+Z^{stor,fixed}+Z^{bal,fixed}
       +Z^{bal,var}+Z^{stor,var}
       +\sum_{h\in\mathcal H}
       (c^{imp}_h\iota_h-c^{exp}_h\xi_h)
       +Z^{curt,pv}+Z^{curt,wind}+Z^{curt,hyd}.

    Fixed terms include annualized CAPEX and annual fixed O&M (USD/year).
    Variable terms are modeled-horizon fuel and O&M costs (USD), with
    one-hour steps. :math:`\iota_h` / :math:`\xi_h` are imports / exports
    in MW; prices :math:`c^{imp}_h` / :math:`c^{exp}_h` are USD/MWh.
    Export revenue is subtracted. Variable costs are not rescaled for short
    horizons, so the total represents annual cost only for a full-year run.
    Optional technology-specific curtailment costs are modeled-horizon USD
    contributions, including unused upper-bound hydro budgets. No nuclear,
    other-renewables, or reserve operating cost is added.
    """
    # Annual Fixed Costs
    fixed_costs = (
        add_vre_fixed_costs(model)
        +
        add_storage_fixed_costs(model)
        +
        add_thermal_fixed_costs(model)
    )

    # Variable Costs (Gas CC Fuel & VOM, Storage VOM)
    variable_costs = (
        add_thermal_variable_costs(model)
        + 
        add_storage_variable_costs(model)
    )

    imports_exports_costs = add_imports_exports_cost(model)

    return fixed_costs + variable_costs + imports_exports_costs + curtailment_cost_rule(model)


####################################################################################|
# ----------------------------------- Expressions ----------------------------------|
####################################################################################|
def net_load_rule(model, h):
    r"""Return demand net of available VRE and fixed or scheduled generation.

    Parameters
    ----------
    model : pyomo.core.base.block.BlockData
        Host with initialized demand and resource expressions.
    h : int
        Modeled hour.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue
        Net load in MW, before storage, thermal dispatch, and trade.

    Notes
    -----
    .. math::

       n_h=d_h-(G^{pv}_h+C^{pv}_h)-(G^{wind}_h+C^{wind}_h)
       -\alpha^{nuc}\nu_h-\alpha^{oth}\omega_h-G^{hyd}_h.

    :math:`d_h` is demand; :math:`G` / :math:`C` denote dispatched /
    curtailed VRE, whose sum is ``total_hourly_availability``. Nuclear
    :math:`\nu_h` and other-renewables :math:`\omega_h` profiles are scaled
    by their ``alpha`` parameters. Hydro uses scheduled ``generation[h]``.
    All power terms are MW. This is not residual demand after VRE curtailment.
    """
    return ( model.demand.ts_parameter[h] 
            - model.pv.total_hourly_availability[h] - model.wind.total_hourly_availability[h] 
            - model.nuclear.alpha * model.nuclear.ts_parameter[h] - model.other_renewables.alpha * model.other_renewables.ts_parameter[h]
            - model.hydro.generation[h] )

def add_system_expressions(host):
    """Attach the hourly net-load expression used by net-load-coupled trade.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized demand and resource expressions.

    See Also
    --------
    net_load_rule : Definition of ``net_load[h]`` in MW.
    """
    host.net_load = Expression(host.h, rule=net_load_rule)
    return



####################################################################################|
# ----------------------------------- Constraints ----------------------------------|
####################################################################################|
# Energy supply demand

def create_supply_balance_rule(has_imports, has_exports):
    r"""Create a copperplate supply-balance rule with optional external trade.

    Parameters
    ----------
    has_imports : bool
        Whether imports are included in the model.
    has_exports : bool
        Whether exports are included in the model.

    Returns
    -------
    function
        Rule accepting a host and hour and returning a balance equality.

    Notes
    -----
    At each hour :math:`h`, the returned rule enforces

    .. math::

       \begin{aligned}
       d_h+\sum_j D^{ch}_{jh}+\xi_h
       ={}&\sum_j D^{dis}_{jh}+\alpha^{nuc}\nu_h+G^{hyd}_h
       +\alpha^{oth}\omega_h\\
       &+G^{pv}_h+G^{wind}_h+\sum_kG^{bal}_{kh}+\iota_h.
       \end{aligned}

    All terms are MW. :math:`d` is demand, :math:`D^{ch}` / :math:`D^{dis}`
    are storage ``PC`` / ``PD``, and :math:`G` is dispatched generation
    (not VRE availability). :math:`\nu` / :math:`\omega` are nuclear /
    other-renewables profiles with their activation scalars.
    :math:`\iota` / :math:`\xi` are imports / exports, omitted when disabled.
    This rule includes neither load shedding nor zonal line flows.
    """
    def supply_balance_rule(model, h):
        r"""Return the hourly copperplate power-balance equality.

        Parameters
        ----------
        model : pyomo.core.base.block.BlockData
            Host with initialized demand, dispatch, and enabled trade variables.
        h : int
            Modeled hour.

        Returns
        -------
        pyomo.core.expr.relational_expr.EqualityExpression
            Supply equal to demand plus charging and enabled exports.

        Notes
        -----
        Using the resource symbols defined in the enclosing factory,

        .. math::

           d_h+\sum_j(D^{ch}_{jh}-D^{dis}_{jh})
           -\alpha^{nuc}\nu_h-G^{hyd}_h-\alpha^{oth}\omega_h
           -G^{pv}_h-G^{wind}_h-\sum_kG^{bal}_{kh}
           -\iota_h+\xi_h=0.

        Terms are MW; disabled import/export terms are omitted.
        """
        # Base supply balance expression
        balance = (
            model.demand.ts_parameter[h]
            + quicksum(model.storage.PC[h, j] for j in model.storage.j)
            - quicksum(model.storage.PD[h, j] for j in model.storage.j)
            - model.nuclear.alpha * model.nuclear.ts_parameter[h]
            - model.hydro.generation[h]
            - model.other_renewables.alpha * model.other_renewables.ts_parameter[h]
            - model.pv.generation[h]
            - model.wind.generation[h]
            - quicksum(model.thermal.generation[h, bu] for bu in model.thermal.plants_set)
        )

        # Conditionally add imports (imports reduce the need for other generation)
        if has_imports:
            balance = balance - model.imports.variable[h]

        # Conditionally add exports (exports increase the need for generation)
        if has_exports:
            balance = balance + model.exports.variable[h]

        return balance == 0

    return supply_balance_rule

# Generation mix target
# Limit on generation from thermal generation and imports
def genmix_share_rule(model):
    r"""Return the modeled-horizon clean-generation-share constraint.

    Parameters
    ----------
    model : pyomo.core.base.block.BlockData
        Host with thermal generation, demand, storage, ``GenMix_Target``,
        and an imports block.

    Returns
    -------
    pyomo.core.expr.relational_expr.InequalityExpression
        The constraint expression for the generation mix target.

    Notes
    -----
    .. math::

       \sum_{h\in\mathcal H}\sum_{k\in\mathcal K}G^{bal}_{kh}
       +\sum_{h\in\mathcal H}\iota_h
       \le(1-\tau)\sum_{h\in\mathcal H}
       \left[d_h+\sum_j(D^{ch}_{jh}-D^{dis}_{jh})\right].

    :math:`\tau` is ``GenMix_Target``, :math:`d` is demand, and storage
    charging/discharging are ``PC`` / ``PD``. All power terms are MW;
    implicit one-hour sums are MWh. Imports count as non-clean and are
    omitted if ``imports.variable`` is absent. Exports are not subtracted
    from adjusted demand. The constraint is aggregate, not hourly.
    """
    imports_total = (
        quicksum(model.imports.variable[h] for h in model.h)
        if hasattr(model.imports, "variable")
        else 0
    )
    adjusted_demand = quicksum(
        model.demand.ts_parameter[h]
        + quicksum(model.storage.PC[h, j] for j in model.storage.j)
        - quicksum(model.storage.PD[h, j] for j in model.storage.j)
        for h in model.h
    )
    return (model.thermal.total_generation + imports_total) <= (
        (1 - model.GenMix_Target) * adjusted_demand
    )

def add_system_constraints(host, data):
    """Add copperplate supply balance and the clean-generation-share limit.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System host with initialized demand, generation, storage, and trade.
    data : dict
        Dictionary containing formulation configuration data.

    See Also
    --------
    create_supply_balance_rule : Hourly supply-demand equality.
    genmix_share_rule : Modeled-horizon non-clean-generation upper bound.

    Notes
    -----
    Trade is included unless its formulation is exactly ``"NotModel"``.
    Zonal line-flow balances and the system-wide zonal clean-share constraint
    are constructed separately by the optimization initializer.
    """
    # Check which components are enabled
    has_imports = get_formulation(data, component="Imports") != "NotModel"
    has_exports = get_formulation(data, component="Exports") != "NotModel"

    # Create and add supply balance constraint with appropriate terms
    supply_balance_rule = create_supply_balance_rule(has_imports, has_exports)
    host.SupplyBalance = Constraint(host.h, rule=supply_balance_rule)

    # Generation mix share constraint
    host.GenMix_Share = Constraint(rule=genmix_share_rule)