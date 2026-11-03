"""Build legacy aggregate load-shedding limits, not the outage evaluator."""

from pyomo.core import Var, Constraint
from pyomo.environ import Param, NonNegativeReals
from ..constants import CRITICAL_LOAD_PERCENTAGE, PCLS_TARGET

####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|
def add_resiliency_parameters(host, data):
    """Add the mutable aggregate unserved-energy limit in MWh.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area receiving ``EUE_max``.
    data : dict
        Loaded inputs with the numeric ``scalars`` entry ``EUE_max``.
    """
    host.EUE_max = Param( initialize = float(data["scalars"].loc["EUE_max"].Value), mutable=True )  # Maximum EUE (in MWh) - Maximum unserved Energy


####################################################################################|
# ------------------------------------ Variables -----------------------------------|
####################################################################################|

def add_resiliency_variables( host ):
    """Add nonnegative hourly load-shedding variables in MW.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with the modeled-hour set ``h``.

    Notes
    -----
    This function only declares ``LoadShed``; it does not add a demand upper
    bound or connect shedding to the system supply balance.
    """
    # Define variables related to system resiliency
    host.LoadShed = Var( host.h, domain=NonNegativeReals, initialize = 0 )

####################################################################################|
# ----------------------------------- Constraints ----------------------------------|
####################################################################################|
def pcls_constraint_rule( model ):
    r"""Return the aggregate served-load requirement.

    Parameters
    ----------
    model : pyomo.core.base.block.BlockData
        Host with hourly demand and ``LoadShed`` variables.

    Returns
    -------
    pyomo.core.expr.relational_expr.InequalityExpression
        Lower bound on served energy over the modeled hours.

    Notes
    -----
    .. math::

       \sum_{h\in\mathcal H}(d_h-L_h)
       \ge p^{target}c^{crit}\sum_{h\in\mathcal H}d_h.

    :math:`d_h` is demand and :math:`L_h` is ``LoadShed[h]`` in MW.
    :math:`p^{target}` and :math:`c^{crit}` are the dimensionless constants
    ``PCLS_TARGET`` and ``CRITICAL_LOAD_PERCENTAGE``. One-hour steps make
    the sums MWh. This is an aggregate limit, not an hourly service guarantee.
    """
    return sum( model.demand.ts_parameter[h] - model.LoadShed[h] for h in model.h ) \
        >= PCLS_TARGET * sum( model.demand.ts_parameter[h] for h in model.h ) * CRITICAL_LOAD_PERCENTAGE

# EUE - Expected Unserved Energy - Constraint : Resilience
def max_eue_constraint_rule( model ):
    r"""Return the aggregate unserved-energy upper bound.

    Parameters
    ----------
    model : pyomo.core.base.block.BlockData
        Host with ``LoadShed``, modeled hours ``h``, and ``EUE_max``.

    Returns
    -------
    pyomo.core.expr.relational_expr.InequalityExpression
        Upper bound on total load shedding.

    Notes
    -----
    .. math::

       \sum_{h\in\mathcal H}L_h \le EUE^{max}.

    :math:`L_h` is ``LoadShed[h]`` (MW); the implicit one-hour interval makes
    the sum MWh, matching ``EUE_max``. No scenario probabilities are applied.
    """
    return sum( model.LoadShed[h] for h in model.h ) <= model.EUE_max

def add_resiliency_constraints( host ):
    """Add the aggregate served-load and unserved-energy constraints.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with initialized demand, ``LoadShed``, and ``EUE_max``.

    See Also
    --------
    pcls_constraint_rule : Aggregate served-load lower bound.
    max_eue_constraint_rule : Aggregate unserved-energy upper bound.

    Notes
    -----
    Creates ``PCLS_Constraint`` and ``MaxEUE_Constraint``. These legacy
    constraints do not implement the separate outage-evaluation workflow.
    """
    host.PCLS_Constraint = Constraint( rule = pcls_constraint_rule )
    host.MaxEUE_Constraint = Constraint( rule = max_eue_constraint_rule )