"""Initialize the fixed other-renewables profile and activation scalar."""

from pyomo.environ import Param
from .models_utils import add_alpha_and_ts_parameters

####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|

def add_other_renewables_parameters(host, data: dict):
    r"""Add parameters for scaled, nondispatchable other renewables.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with ``h`` and an ``other_renewables`` block.
    data : dict
        Loaded ``other_renewables_data`` table (``*Hour``, ``OtherRenewables``
        in MW) and ``scalars`` entry ``AlphaOtheRe``.

    Notes
    -----
    Downstream system rules use the fixed injection

    .. math::

       G^{oth}_h = \alpha^{oth}\omega_h.

    :math:`\alpha^{oth}` is ``other_renewables.alpha`` and :math:`\omega_h`
    is ``other_renewables.ts_parameter[h]`` in MW. This builder adds
    parameters only, not a generation variable or constraint.
    """
    add_alpha_and_ts_parameters(host.other_renewables, host.h, data, "AlphaOtheRe", "other_renewables_data", "OtherRenewables")
    