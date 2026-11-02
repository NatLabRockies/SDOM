"""Build storage investment, cyclic hourly operation, and cost expressions."""

from pyomo.core import Var, Constraint, Expression
from pyomo.environ import Set, Param, Binary, NonNegativeReals, sqrt, quicksum
from ..constants import STORAGE_PROPERTIES_NAMES, MW_TO_KW
from .models_utils import build_annualization_factor_map

def initialize_storage_sets(block, data: dict):
    """Initialize storage technology, coupled-technology, and property sets.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Storage block receiving ``j``, ``b``, and ``properties_set``.
    data : dict
        Loaded inputs containing ``STORAGE_SET_J_TECHS`` and its coupled
        subset ``STORAGE_SET_B_TECHS``.
    """
    block.j = Set( initialize = data['STORAGE_SET_J_TECHS'] )
    block.b = Set( within=block.j, initialize = data['STORAGE_SET_B_TECHS'] )
    
    # Initialize storage properties
    block.properties_set = Set( initialize = STORAGE_PROPERTIES_NAMES )
####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|

def add_storage_parameters(host, data: dict):
    r"""Add storage properties and technology-specific capital-recovery factors.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized storage sets.
    data : dict
        Loaded ``storage_data`` indexed by property with technology columns,
        and ``scalars`` containing discount rate ``r``.

    Notes
    -----
    For technology :math:`j` with lifetime :math:`l_j` in years,

    .. math::

       a_j=\operatorname{CRF}(l_j)=\frac{r(1+r)^{l_j}}{(1+r)^{l_j}-1}.

    :math:`a_j` is ``storage.CRF[j]`` in inverse years. ``MaxCycles`` stores
    lifetime cycles; ``data[Eff, j]`` stores roundtrip efficiency.
    """
    # Battery life and cycling
    max_cycles_dict = data['storage_data'].loc['MaxCycles'].to_dict()

    host.storage.MaxCycles = Param( host.storage.j,  initialize = max_cycles_dict )
    # Storage data initialization
    storage_dict = data["storage_data"].stack().to_dict()
    storage_tuple_dict = {(prop, tech): storage_dict[(prop, tech)] for prop in STORAGE_PROPERTIES_NAMES for tech in host.storage.j}
    host.storage.data = Param( host.storage.properties_set, host.storage.j, initialize = storage_tuple_dict )

    r = float(data["scalars"].loc["r"].Value)
    host.storage.r = Param(initialize=r)  # Interest rate
    lifetimes_by_tech = {
        tech: data["storage_data"].loc["Lifetime", tech]
        for tech in host.storage.j
    }
    crf_values = build_annualization_factor_map(r, lifetimes_by_tech)
    host.storage.CRF = Param(host.storage.j, initialize=crf_values)  # Capital Recovery Factor - STORAGE

####################################################################################|
# ------------------------------------ Variables -----------------------------------|
####################################################################################|
def add_storage_variables(host):
    """Add storage power, energy, dispatch, and operating-mode variables.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with ``h`` and initialized storage technology set ``j``.

    Notes
    -----
    ``PC[h,j]`` and ``PD[h,j]`` are nonnegative charging/discharging MW;
    ``SOC[h,j]`` is end-of-hour MWh. ``Pcha[j]`` and ``Pdis[j]`` are installed
    MW, and ``Ecap[j]`` is installed MWh. Binary ``capacity_fraction[j,h]``
    selects charging (one) versus discharging (zero). All initialize to zero.
    """
    # Charging power for storage technology j in hour h
    host.storage.PC = Var(host.h, host.storage.j, domain=NonNegativeReals, initialize=0)
    # Discharging power for storage technology j in hour h
    host.storage.PD = Var(host.h, host.storage.j, domain=NonNegativeReals, initialize=0)
    # State-of-charge for storage technology j in hour h
    host.storage.SOC = Var(host.h, host.storage.j, domain=NonNegativeReals, initialize=0)
    # Charging capacity for storage technology j
    host.storage.Pcha = Var(host.storage.j, domain=NonNegativeReals, initialize=0)
    # Discharging capacity for storage technology j
    host.storage.Pdis = Var(host.storage.j, domain=NonNegativeReals, initialize=0)
    # Energy capacity for storage technology j
    host.storage.Ecap = Var(host.storage.j, domain=NonNegativeReals, initialize=0)

    host.storage.capacity_fraction = Var(host.storage.j, host.h, domain=Binary, initialize=0)


####################################################################################|
# ----------------------------------- Expressions ----------------------------------|
####################################################################################|

def storage_power_capex_cost_expr_rule(block, j):
     r"""Return annualized storage power capital cost for one technology.

     Parameters
     ----------
     block : pyomo.core.base.block.BlockData
         Storage block with cost parameters, CRF, and installed power.
     j : hashable
         Storage technology identifier.

     Returns
     -------
     pyomo.core.expr.numeric_expr.NumericValue
         Annual power capital cost in USD/year.

     Notes
     -----
     .. math::

        Z^{P,cap}_j=a_j10^3\kappa^P_j
        [\alpha_jP^{ch}_j+(1-\alpha_j)P^{dis}_j].

     :math:`a_j` is ``CRF[j]``, :math:`\kappa^P_j` is ``P_Capex`` in
     USD/kW, and :math:`\alpha_j` is ``CostRatio``. ``Pcha`` and ``Pdis``
     are installed MW; ``MW_TO_KW`` supplies the :math:`10^3` conversion.
     """
     return (   block.CRF[j] * (
                    MW_TO_KW * block.data['CostRatio', j] * block.data['P_Capex', j]*block.Pcha[j]
                    + MW_TO_KW * (1 - block.data['CostRatio', j]) * block.data['P_Capex', j]*block.Pdis[j]
                    )
                )

def storage_energy_capex_cost_expr_rule(block, j):
     r"""Return annualized storage energy capital cost for one technology.

     Parameters
     ----------
     block : pyomo.core.base.block.BlockData
         Storage block with CRF, energy CAPEX, and installed energy.
     j : hashable
         Storage technology identifier.

     Returns
     -------
     pyomo.core.expr.numeric_expr.NumericValue
         Annual energy capital cost in USD/year.

     Notes
     -----
     .. math::

        Z^{E,cap}_j=a_j10^3\kappa^E_j E_j.

     :math:`a_j` is ``CRF[j]``, :math:`\kappa^E_j` is ``E_Capex``
     (USD/kWh), and :math:`E_j` is ``Ecap[j]`` (MWh). The numeric
     ``MW_TO_KW`` factor also converts MWh to kWh here.
     """
     return ( block.CRF[j] * ( MW_TO_KW *block.data['E_Capex', j]*block.Ecap[j] ) )

def storage_fixed_om_cost_expr_rule(block, j):
     r"""Return annual fixed storage O&M cost for one technology.

     Parameters
     ----------
     block : pyomo.core.base.block.BlockData
         Storage block with FOM, cost ratio, and installed power.
     j : hashable
         Storage technology identifier.

     Returns
     -------
     pyomo.core.expr.numeric_expr.NumericValue
         Annual fixed O&M cost in USD/year.

     Notes
     -----
     .. math::

        Z^{FOM}_j=10^3\phi_j
        [\alpha_jP^{ch}_j+(1-\alpha_j)P^{dis}_j].

     :math:`\phi_j` is ``FOM`` (USD/kW-year), :math:`\alpha_j` is
     ``CostRatio``, and ``Pcha`` / ``Pdis`` are installed MW.
     """
     return (    MW_TO_KW * block.data['CostRatio', j] * block.data['FOM', j]*block.Pcha[j]
                + MW_TO_KW * (1 - block.data['CostRatio', j]) * block.data['FOM', j]*block.Pdis[j]
                )

def _add_storage_expressions(block):
    r"""Attach technology-level and total annual storage cost expressions.

    Parameters
    ----------
    block : pyomo.core.base.block.BlockData
        Storage block with initialized parameters and investment variables.

    Notes
    -----
    .. math::

       Z^{cap}_j=Z^{P,cap}_j+Z^{E,cap}_j,\qquad
       Z^{cap}=\sum_j Z^{cap}_j,\qquad Z^{FOM}=\sum_j Z^{FOM}_j.

    All terms are USD/year. The power, energy, and FOM rule functions
    define each technology-level term.
    """
    block.power_capex_cost_expr = Expression(block.j, rule = storage_power_capex_cost_expr_rule )
    block.energy_capex_cost_expr = Expression(block.j, rule = storage_energy_capex_cost_expr_rule )
    block.capex_cost_expr = Expression(block.j,  rule = lambda m,j: m.power_capex_cost_expr[j] + m.energy_capex_cost_expr[j] )

    block.fixed_om_cost_expr = Expression(block.j,  rule = storage_fixed_om_cost_expr_rule )

    block.total_capex_cost = Expression(rule=quicksum(block.capex_cost_expr[j] for j in block.j))
    block.total_fixed_om_cost = Expression(rule=quicksum(block.fixed_om_cost_expr[j] for j in block.j))


def add_storage_expressions(host):
    """Attach annual storage cost expressions to the host's storage block.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized storage parameters and variables.

    See Also
    --------
    storage_power_capex_cost_expr_rule : Annual power CAPEX.
    storage_energy_capex_cost_expr_rule : Annual energy CAPEX.
    storage_fixed_om_cost_expr_rule : Annual fixed O&M.
    """
    _add_storage_expressions(host.storage)
     


####################################################################################|
# ----------------------------------- Add_costs -----------------------------------|
####################################################################################|
def add_storage_fixed_costs(host):
    r"""Return total annual storage capital and fixed O&M costs.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized storage cost expressions.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue
        Annual fixed storage cost in USD/year; adds no variables.

    Notes
    -----
    .. math::

       Z^{stor,fixed}=\sum_j(Z^{P,cap}_j+Z^{E,cap}_j+Z^{FOM}_j).

    The terms are annual power CAPEX, energy CAPEX, and fixed O&M,
    respectively, as defined by the storage cost rule functions.
    """
    return ( # Storage Capex and Fixed O&M
            host.storage.total_capex_cost  + host.storage.total_fixed_om_cost 
            )

def add_storage_variable_costs(host):
    r"""Return storage variable O&M costs on discharged energy only.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with storage ``VOM`` and hourly ``PD``.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue or int
        Modeled-horizon variable cost in USD; zero for no technologies.

    Notes
    -----
    .. math::

       Z^{stor,var}=\sum_{j\in\mathcal J}\psi_j
       \sum_{h\in\mathcal H}D^{dis}_{jh}.

    :math:`\psi_j` is ``VOM`` (USD/MWh), and :math:`D^{dis}_{jh}` is
    ``PD[h,j]`` (MW). Steps are implicitly one hour. Charging is not charged
    VOM, and partial-horizon totals are not scaled to a full year.
    """
    return quicksum(
        host.storage.data['VOM', j] * quicksum(host.storage.PD[h, j] for h in host.h)
        for j in host.storage.j
    )

####################################################################################|
# ----------------------------------- Constraints ----------------------------------|
####################################################################################|

# State-Of-Charge Balance -
def soc_balance_rule(model, h, j):
    r"""Return the cyclic end-of-hour storage energy balance.

    Parameters
    ----------
    model : pyomo.core.base.block.BlockData
        System or area with ``storage`` and contiguous one-based hours ``h``.
    h : int
        Modeled hour.
    j : hashable
        Storage technology identifier.

    Returns
    -------
    pyomo.core.expr.relational_expr.EqualityExpression
        State-of-charge balance for one technology and hour.

    Notes
    -----
    .. math::

       S_{jh}=S_{j,h^-}+\sqrt{\eta_j}D^{ch}_{jh}
       -\frac{D^{dis}_{jh}}{\sqrt{\eta_j}},\qquad
       h^-=\begin{cases}h-1&h>1,\\\max(\mathcal H)&h=1.\end{cases}

    :math:`S` is ``SOC`` (MWh), :math:`D^{ch}` / :math:`D^{dis}` are
    ``PC`` / ``PD`` (MW), and :math:`\eta_j` is roundtrip ``Eff``.
    Charge and discharge efficiencies both equal :math:`\sqrt{\eta_j}`;
    the implicit interval is one hour. First-hour SOC wraps to final-hour
    SOC rather than using a fixed initial state.
    """
    if h > 1: 
        return model.storage.SOC[h, j] == model.storage.SOC[h-1, j] \
            + sqrt(model.storage.data['Eff', j]) * model.storage.PC[h, j] \
            - model.storage.PD[h, j] / sqrt(model.storage.data['Eff', j])
    else:
        # cyclical or initial condition
        return model.storage.SOC[h, j] == model.storage.SOC[max(model.h), j] \
            + sqrt(model.storage.data['Eff', j]) * model.storage.PC[h, j] \
            - model.storage.PD[h, j] / sqrt(model.storage.data['Eff', j])

# Max cycle year
def max_cycle_year_rule(model, j): #TODO check here this hardcoded Li-Ion
    r"""Return the annualized lifetime-cycle throughput limit.

    Parameters
    ----------
    model : pyomo.core.base.block.BlockData
        Storage block with ``n_steps_modeled``, ``PD``, ``MaxCycles``,
        ``data``, and ``Ecap``.
    j : hashable
        Storage technology identifier.

    Returns
    -------
    pyomo.core.expr.relational_expr.InequalityExpression
        Upper bound on total discharged energy.

    Notes
    -----
    .. math::

       \sum_{h=1}^{N}D^{dis}_{jh}
       \le \frac{\kappa^{cyc}_j}{l_j}E_j.

    :math:`N` is ``n_steps_modeled``, :math:`\kappa^{cyc}_j` is lifetime
    ``MaxCycles[j]``, :math:`l_j` is ``Lifetime`` in years, and :math:`E_j`
    is ``Ecap[j]`` in MWh. One-hour discharge steps give MWh. The RHS is
    a one-year cycle allowance, not prorated for a shorter modeled horizon.
    No efficiency factor is included in this throughput limit.
    """
    n_steps = model.n_steps_modeled
    iterate = range(1, n_steps + 1)
    return sum(model.PD[h, j] for h in iterate) <= (model.MaxCycles[j] / model.data['Lifetime', j]) * model.Ecap[j]

def add_storage_constraints( host ):
    r"""Add storage operating, capacity, duration, and throughput constraints.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized storage sets, parameters, variables,
        and ``storage.n_steps_modeled``.

    Notes
    -----
    For storage :math:`j`, hour :math:`h`, and binary mode :math:`u_{jh}`,

    .. math::

       \begin{aligned}
       0\le D^{ch}_{jh}&\le\bar p^{stor}_j u_{jh},
       &D^{ch}_{jh}&\le P^{ch}_j,\\
       0\le D^{dis}_{jh}&\le\bar p^{stor}_j(1-u_{jh}),
       &D^{dis}_{jh}&\le P^{dis}_j,\\
       0\le S_{jh}&\le E_j,
       &P^{ch}_j,\ P^{dis}_j&\le\bar p^{stor}_j,\\
       P^{ch}_j&=P^{dis}_j &&(j\in\mathcal J^c),\\
       \frac{\underline\delta_jP^{dis}_j}{\sqrt{\eta_j}}
       &\le E_j\le
       \frac{\overline\delta_jP^{dis}_j}{\sqrt{\eta_j}}.
       \end{aligned}

    ``PC`` / ``PD`` are :math:`D^{ch}` / :math:`D^{dis}` (MW);
    ``Pcha`` / ``Pdis`` are installed power (MW); ``SOC`` / ``Ecap`` are
    :math:`S` / :math:`E` (MWh). ``capacity_fraction[j,h]`` is :math:`u`,
    ``Max_P`` is :math:`\bar p^{stor}`, ``Eff`` is :math:`\eta`, and
    ``Min_Duration`` / ``Max_Duration`` are :math:`\underline\delta` /
    :math:`\overline\delta` (hours). ``storage.b`` is the coupled subset
    :math:`\mathcal J^c`. Nonnegativity comes from variable domains.

    Also attaches :func:`soc_balance_rule` on the host and
    :func:`max_cycle_year_rule` on the storage block.
    """
    # Ensure that the charging and discharging power do not exceed storage limits
    host.storage.ChargSt= Constraint(host.h, host.storage.j, rule=lambda m, h, j: m.PC[h, j] <= m.data['Max_P', j] * m.capacity_fraction[j, h])
    host.storage.DischargeSt = Constraint(host.h, host.storage.j, rule=lambda m, h, j: m.PD[h, j] <= m.data['Max_P', j] * (1 - m.capacity_fraction[j, h]))

    # Hourly capacity bounds
    host.storage.MaxHourlyCharging = Constraint(host.h, host.storage.j, rule= lambda m,h,j: m.PC[h, j] <= m.Pcha[j])
    host.storage.MaxHourlyDischarging = Constraint(host.h, host.storage.j, rule= lambda m,h,j: m.PD[h, j] <= m.Pdis[j])

    # Limit state of charge of storage by its capacity
    host.storage.MaxSOC = Constraint(host.h, host.storage.j, rule=lambda m, h, j: m.SOC[h,j]<= m.Ecap[j])
    # SOC Balance Constraint
    host.SOCBalance = Constraint(host.h, host.storage.j, rule=soc_balance_rule)

    # - Constraints on the maximum charging (Pcha) and discharging (Pdis) power for each technology
    host.storage.MaxPcha = Constraint( host.storage.j, rule=lambda m, j: m.Pcha[j] <= m.data['Max_P', j] )
    host.storage.MaxPdis = Constraint( host.storage.j, rule=lambda m, j: m.Pdis[j] <= m.data['Max_P', j] )

    # Charge and discharge rates are equal -
    host.storage.PchaPdis = Constraint( host.storage.b, rule=lambda m, j: m.Pcha[j] == m.Pdis[j] )

    # Max and min energy capacity constraints (handle uninitialized variables)
    host.storage.MinEcap = Constraint(host.storage.j, rule= lambda m,j: m.Ecap[j] >= m.data['Min_Duration', j] * m.Pdis[j] / sqrt(m.data['Eff', j]))
    host.storage.MaxEcap = Constraint(host.storage.j, rule= lambda m,j: m.Ecap[j] <= m.data['Max_Duration', j] * m.Pdis[j] / sqrt(m.data['Eff', j]))


    host.storage.MaxCycleYear_constraint = Constraint( host.storage.j, rule=max_cycle_year_rule)