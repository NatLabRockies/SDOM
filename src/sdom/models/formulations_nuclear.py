"""Initialize the fixed nuclear profile and its activation scalar."""

from pyomo.environ import Param
from .models_utils import add_alpha_and_ts_parameters

####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|

def add_nuclear_parameters(host, data: dict):
    r"""Add parameters for scaled, nondispatchable nuclear generation.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with ``h`` and a ``nuclear`` block.
    data : dict
        Loaded ``nuclear_data`` table (``*Hour``, ``Nuclear`` in MW) and
        ``scalars`` entry ``AlphaNuclear``.

    Notes
    -----
    Downstream system rules use the fixed injection

    .. math::

       G^{nuc}_h = \alpha^{nuc}\nu_h.

    :math:`\alpha^{nuc}` is ``nuclear.alpha`` and :math:`\nu_h` is
    ``nuclear.ts_parameter[h]`` in MW. This builder adds parameters only,
    not a generation variable or constraint.
    """
    add_alpha_and_ts_parameters(host.nuclear, host.h, data, "AlphaNuclear", "nuclear_data", "Nuclear")
    