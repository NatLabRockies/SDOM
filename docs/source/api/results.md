# Results Module

The results module provides structured data classes for storing and accessing optimization results.

## OptimizationResults Class

The `OptimizationResults` dataclass is the primary container for all optimization results returned by `run_solver()`.

```{eval-rst}
.. autoclass:: sdom.results.OptimizationResults
   :members:
   :special-members: __init__
   :undoc-members:
```

## Result Collection Function

```{eval-rst}
.. autofunction:: sdom.results.collect_results_from_model
```

## Example Usage

### Basic Result Access

```python
from sdom import load_data, initialize_model, run_solver, get_default_solver_config_dict

# Load and solve model
data = load_data('./Data/scenario/')
model = initialize_model(data, n_hours=168)
solver_config = get_default_solver_config_dict(solver_name="highs")

# Run optimization - returns OptimizationResults
results = run_solver(model, solver_config)

# Check solution status
if results.is_optimal:
    print(f"Optimization successful!")
    print(f"Total Cost: ${results.total_cost:,.2f}")
else:
    print(f"Solver terminated with: {results.termination_condition}")
```

### Accessing Capacities

```python
# Generation capacities
print(f"Solar PV Capacity: {results.total_cap_pv:.2f} MW")
print(f"Wind Capacity: {results.total_cap_wind:.2f} MW")
print(f"Thermal Capacity: {results.total_cap_thermal:.2f} MW")

# Storage capacities by technology
for tech, cap in results.total_cap_storage_charge.items():
    print(f"{tech} Charge Capacity: {cap:.2f} MW")

for tech, energy in results.total_cap_storage_energy.items():
    print(f"{tech} Energy Capacity: {energy:.2f} MWh")
```

### Accessing DataFrames

```python
# Get hourly generation dispatch
gen_df = results.get_generation_dataframe()
print(gen_df.head())

# Get storage operation details
storage_df = results.get_storage_dataframe()

# Get summary metrics
summary_df = results.get_summary_dataframe()

# Get disaggregated thermal generation (if multiple plants)
thermal_df = results.get_thermal_generation_dataframe()
```

### Accessing Cost Breakdown

```python
# CAPEX by technology
capex = results.cost_breakdown["capex"]
print(f"Solar CAPEX: ${capex['Solar PV']:,.2f}")
print(f"Wind CAPEX: ${capex['Wind']:,.2f}")

# Storage costs
power_capex = results.cost_breakdown["power_capex"]
energy_capex = results.cost_breakdown["energy_capex"]

# Operating costs
fom = results.cost_breakdown["fom"]
vom = results.cost_breakdown["vom"]

# Import/export costs
print(f"Import Cost: ${results.cost_breakdown['imports_cost']:,.2f}")
print(f"Export Revenue: ${results.cost_breakdown['exports_revenue']:,.2f}")
```

### Accessing Problem Information

```python
# Solver problem statistics
problem_info = results.get_problem_info()
print(f"Constraints: {problem_info['Number of constraints']}")
print(f"Variables: {problem_info['Number of variables']}")
print(f"Binary Variables: {problem_info['Number of binary variables']}")
```

## OptimizationResults Attributes

### Solver Information
| Attribute | Type | Description |
|-----------|------|-------------|
| `termination_condition` | str | Solver termination status (e.g., 'optimal', 'infeasible') |
| `solver_status` | str | Overall solver status (e.g., 'ok', 'warning') |
| `is_optimal` | bool | Property: True if solution is optimal |

### Core Results
| Attribute | Type | Description |
|-----------|------|-------------|
| `total_cost` | float | Total objective value ($) |
| `gen_mix_target` | float | Generation mix target used |

### Capacity Results
| Attribute | Type | Description |
|-----------|------|-------------|
| `capacity` | dict | Generation capacities by technology (MW) |
| `storage_capacity` | dict | Nested dict with 'charge', 'discharge', 'energy' by technology |
| `total_cap_pv` | float | Property: Solar PV capacity (MW) |
| `total_cap_wind` | float | Property: Wind capacity (MW) |
| `total_cap_thermal` | float | Property: Thermal capacity (MW) |
| `total_cap_storage_charge` | dict | Property: Storage charge capacity by tech (MW) |
| `total_cap_storage_discharge` | dict | Property: Storage discharge capacity by tech (MW) |
| `total_cap_storage_energy` | dict | Property: Storage energy capacity by tech (MWh) |

### Generation Results
| Attribute | Type | Description |
|-----------|------|-------------|
| `generation_totals` | dict | Total generation by technology (MWh) |
| `total_gen_pv` | float | Property: Total PV generation (MWh) |
| `total_gen_wind` | float | Property: Total wind generation (MWh) |
| `total_gen_thermal` | float | Property: Total thermal generation (MWh) |

### Cost Breakdown
| Attribute | Type | Description |
|-----------|------|-------------|
| `cost_breakdown` | dict | Nested dict with 'capex', 'power_capex', 'energy_capex', 'fom', 'vom', 'fuel_cost', 'imports_cost', 'exports_revenue' |

### DataFrames
| Attribute | Type | Description |
|-----------|------|-------------|
| `generation_df` | pd.DataFrame | Hourly generation dispatch |
| `storage_df` | pd.DataFrame | Hourly storage operation |
| `thermal_generation_df` | pd.DataFrame | Disaggregated thermal generation |
| `summary_df` | pd.DataFrame | Summary metrics |

### Zonal Fields
| Attribute | Type | Description |
|-----------|------|-------------|
| `is_zonal` | bool | True when collected from a zonal model (`model.A` and `model.area` present). |
| `areas` | list | Area IDs in the solved zonal model. |
| `lines` | list | Line metadata (`line_id`, `from_area`, `to_area`). |
| `area_capacity` | dict | Per-area installed capacities. |
| `area_storage_capacity` | dict | Per-area storage capacities (`charge`, `discharge`, `energy`). |
| `area_generation_totals` | dict | Per-area generation totals. |
| `area_cost_breakdown` | dict | Per-area cost breakdown. |
| `area_generation_df` | dict[str, pd.DataFrame] | Hourly generation by area. |
| `area_storage_df` | dict[str, pd.DataFrame] | Hourly storage operation by area. |
| `area_thermal_generation_df` | dict[str, pd.DataFrame] | Thermal generation by area. |
| `area_installed_plants_df` | dict[str, pd.DataFrame] | Installed plants by area. |
| `area_summary_df` | dict[str, pd.DataFrame] | Per-area summary DataFrames. |
| `interregional_exchanges_df` | pd.DataFrame | Per-line/per-hour flow, directional capacity, and utilization. |

Collector dispatch behavior:

- `collect_results_from_model(...)` uses the zonal collector when both `model.A` and `model.area` exist.
- In zonal mode, `summary_df` is intentionally left empty and replaced by `area_summary_df`.
