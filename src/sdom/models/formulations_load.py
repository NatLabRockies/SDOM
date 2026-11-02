"""Initialize the hourly demand profile used by system constraints."""

from pyomo.environ import Param
from .models_utils import add_alpha_and_ts_parameters
####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|

def add_load_parameters(host, data: dict):
    """Add the unscaled hourly demand parameter in MW.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area with ``h`` and a ``demand`` block.
    data : dict
        Loaded inputs containing ``load_data`` with ``*Hour`` and ``Load``
        columns. Only modeled hours are selected.

    Notes
    -----
    Creates ``demand.ts_parameter[h]`` without adding an activation scalar.
    Supply-balance and capacity-margin constraints use this gross demand.
    """
    add_alpha_and_ts_parameters(host.demand, host.h, data, "", "load_data", "Load")
