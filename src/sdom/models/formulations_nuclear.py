from pyomo.environ import Param
from .models_utils import add_alpha_and_ts_parameters

####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|

def add_nuclear_parameters(host, data: dict):
    add_alpha_and_ts_parameters(host.nuclear, host.h, data, "AlphaNuclear", "nuclear_data", "Nuclear")
    