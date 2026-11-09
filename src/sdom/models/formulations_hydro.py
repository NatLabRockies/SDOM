"""Build hourly hydropower dispatch with profile or energy-budget constraints."""

from pyexpat import model

from pyomo.core import Constraint, Expression, Var
from pyomo.environ import NonNegativeReals, Param, Set, value

from ..constants import (
    DAILY_BUDGET_HOURS_AGGREGATION,
    HYDRO_FORMULATION_METADATA,
    MONTHLY_BUDGET_HOURS_AGGREGATION,
    VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP,
)
from ..io.formulations import get_formulation
from .models_utils import (
    add_alpha_and_ts_parameters,
    add_budget_parameter,
    add_generation_variables,
    add_lower_bound_paramenters,
    add_upper_bound_paramenters,
    generic_budget_rule,
)

####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|

def add_large_hydro_parameters(host, data: dict):
    """Add the hydro profile, activation scalar, and budget-period length.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with ``h`` and a ``hydro`` block.
    data : dict
        Loaded inputs containing ``AlphaLargHy``, the ``large_hydro_data``
        profile (MW), and the hydro formulation selection.

    Notes
    -----
    ``hydro.alpha`` scales hourly profile/bound constraints. The energy-budget
    relation uses the unscaled profile; see :func:`add_hydro_budget_constraints`.
    """
    add_alpha_and_ts_parameters(host.hydro, host.h, data, "AlphaLargHy", "large_hydro_data", "LargeHydro")
    formulation = get_formulation(data, component='hydro')
    add_budget_parameter(host.hydro, formulation, VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP)


def add_large_hydro_bound_parameters(host, data: dict):
    """Add hourly minimum and maximum hydro dispatch parameters in MW.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with ``h`` and a ``hydro`` block.
    data : dict
        Loaded ``large_hydro_min`` and ``large_hydro_max`` tables with
        ``*Hour`` and ``LargeHydro`` columns.
    """
    # Time-series parameter data initialization
    add_upper_bound_paramenters(host.hydro, host.h, data, "large_hydro_max", "LargeHydro")
    add_lower_bound_paramenters(host.hydro, host.h, data, "large_hydro_min", "LargeHydro")



####################################################################################|
# ------------------------------------ Variables -----------------------------------|
####################################################################################|

def add_hydro_variables(host):
    """Add nonnegative hourly hydro generation variables in MW.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with ``h`` and a ``hydro`` block.
    """
    add_generation_variables(host.hydro, host.h, domain=NonNegativeReals, initialize=0)

####################################################################################|
# ----------------------------------- Constraints ----------------------------------|
####################################################################################|

def add_hydro_run_of_river_constraints(host, data: dict):
    r"""Fix hydro generation to the scaled run-of-river profile.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized hydro generation and parameters.
    data : dict
        Loaded inputs; unused by this builder.

    Notes
    -----
    For each modeled hour :math:`h`,

    .. math::

       G^{hyd}_h = \alpha^{hyd}\rho_h.

    :math:`G^{hyd}_h` is ``hydro.generation[h]`` (MW), :math:`\rho_h` is
    ``hydro.ts_parameter[h]`` (MW), and :math:`\alpha^{hyd}` is ``hydro.alpha``.
    """
    host.hydro.run_of_river_constraint = Constraint(host.h, rule=lambda m,h: m.generation[h] == m.alpha * m.ts_parameter[h] )
    return


def add_hydro_budget_constraints(host, data: dict):
    r"""Bound hourly hydro dispatch and enforce the selected energy budget.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized hydro bounds, generation, and
        ``hydro.budget_set``.
    data : dict
        Loaded inputs; unused by this builder.

    Notes
    -----
    For hour :math:`h` and budget period :math:`b`,

    .. math::

       \alpha^{hyd}\underline g^{hyd}_h \le G^{hyd}_h
       \le \alpha^{hyd}\overline g^{hyd}_h,\qquad
       \sum_{h\in\mathcal H_b}G^{hyd}_h
       \mathrel{\{=,\le\}} \sum_{h\in\mathcal H_b}\rho_h.

    The hourly bounds and dispatch are in MW. With implicit one-hour steps,
    each sum is energy in MWh. The budget profile :math:`\rho_h` is
    ``hydro.ts_parameter[h]`` and is **not** multiplied by ``hydro.alpha``.
    Existing daily/monthly names enforce equality. Explicit ``UpperBound``
    names allow unused energy, without carryover into subsequent periods.
    :func:`~sdom.models.models_utils.generic_budget_rule` defines the
    contiguous, fixed-length hour set :math:`\mathcal H_b`.
    """
    host.hydro.upper_bound_ts_constraint = Constraint(host.h, rule=lambda m,h: m.generation[h] <= m.alpha * m.ts_parameter_upper_bound[h] )
    host.hydro.lower_bound_ts_constraint = Constraint(host.h, rule=lambda m,h: m.generation[h] >= m.alpha * m.ts_parameter_lower_bound[h] )

    formulation = HYDRO_FORMULATION_METADATA[get_formulation(data, component="hydro")]
    equality = formulation.budget_sense == "equality"
    host.hydro.budget_constraint = Constraint(
        host.hydro.budget_set,
        rule=lambda block, period: generic_budget_rule(
            block, period, equality=equality
        ),
    )
    
    return
