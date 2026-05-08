from pyomo.environ import Param
from .models_utils import add_alpha_and_ts_parameters

####################################################################################|
# ----------------------------------- Parameters -----------------------------------|
####################################################################################|

def add_other_renewables_parameters(host, data: dict):

    add_alpha_and_ts_parameters(host.other_renewables, host.h, data, "AlphaOtheRe", "other_renewables_data", "OtherRenewables")
    