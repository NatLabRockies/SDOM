from pyomo.environ import Param
from .models_utils import add_alpha_and_ts_parameters
####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|

def add_load_parameters(host, data: dict):

    add_alpha_and_ts_parameters(host.demand, host.h, data, "", "load_data", "Load")
