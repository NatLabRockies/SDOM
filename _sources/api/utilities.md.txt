# Utility Functions

Helper functions and utilities used throughout SDOM.

## Pyomo Utilities

```{eval-rst}
.. autofunction:: sdom.common.utilities.safe_pyomo_value
```

## File Utilities

```{eval-rst}
.. autofunction:: sdom.common.utilities.check_file_exists

.. autofunction:: sdom.common.utilities.get_complete_path

.. autofunction:: sdom.common.utilities.normalize_string
```

## Data Utilities

```{eval-rst}
.. autofunction:: sdom.common.utilities.compare_lists

.. autofunction:: sdom.common.utilities.concatenate_dataframes

.. autofunction:: sdom.common.utilities.get_dict_string_void_list_from_keys_in_list
```

## Constants

Key constants defined in `sdom.constants`:

```python
from sdom.constants import (
    MW_TO_KW,                                      # 1000.0
    INPUT_CSV_NAMES,                               # Dict of CSV filenames
    VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP,       # Hydro formulation types
    VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP,  # Trade formulations
)
```

### Unit Conversion

- `MW_TO_KW = 1000.0`: Conversion factor from MW to kW

### Input File Names

The `INPUT_CSV_NAMES` dictionary maps logical names to expected filenames:

```python
{
    'formulations': 'formulations.csv',
    'load_data': 'Load_hourly.csv',
    'nuclear_data': 'Nucl_hourly.csv',
    'large_hydro_data': 'lahy_hourly.csv',
    'cf_solar': 'CFSolar.csv',
    'cf_wind': 'CFWind.csv',
    'cap_solar': 'CapSolar.csv',
    'cap_wind': 'CapWind.csv',
    'storage_data': 'StorageData.csv',
    'thermal_data': 'Data_BalancingUnits.csv',
    'scalars': 'scalars.csv',
    # ... and more
}
```

### Hydro Formulations

```python
VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP = {
    "MonthlyBudgetFormulation": 730,   # Hours per month (approx)
    "DailyBudgetFormulation": 24,      # Hours per day
    "RunOfRiverFormulation": 1         # No aggregation
}
```

### Import/Export Formulations

```python
VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP = {
    "NotModel": "No imports/exports considered",
    "CapacityPriceNetLoadFormulation": "Price-based import/export optimization"
}
```

## Example Usage

```python
from sdom.common.utilities import safe_pyomo_value, compare_lists
from sdom.constants import MW_TO_KW

# Safely extract variable values
total_cost = safe_pyomo_value(model.Obj.expr)
wind_capacity = safe_pyomo_value(model.wind.total_installed_capacity)

# Convert units
wind_capacity_kw = wind_capacity * MW_TO_KW

# Compare plant lists
solar_cf_plants = ['101', '102', '103']
solar_capex_plants = ['101', '102', '103']
compare_lists(solar_cf_plants, solar_capex_plants, 
              text_comp='solar plants',
              list_names=['CF', 'CAPEX'])
```
