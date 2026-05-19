# Exploring the Pyomo Model

This guide explains the internal structure of the SDOM Pyomo model for advanced users and developers.

## Model Architecture
SDOM uses [pyomo](https://pyomo.readthedocs.io/en/stable/index.html) to write the optimization model.

When you run

    ```python
    model = initialize_model(
        data,
        n_hours=n_steps,
        with_resilience_constraints=with_resilience_constraints
    )
    ```

the function `initialize_model()` returns the pyomo instance of the optimization model, which in this case is stores in the variable `model`. 

SDOM leverages on pyomo blocks to separate in different blocks the variables, parameters, expressions, constraints, etc of diferent model components. In this way, in that pyomo instance, SDOM creates the following blocks:

- Core optimization Blocks (Blocks that include variables, sets and parameters)
  - thermal 
  - pv 
  - wind 
  - hydro
  - storage
- Blocks containing only parameters (Do not include any decision variables)
  - demand
  - nuclear
  - other_renewables
- Optional blocks (These are created depending on the configuration provided by the user)
  - imports
  - exports
  - resiliency

Using `pprint()` function, you'll be able to explore model objects in a simple way. If you run:

```python
from sdom import load_data, initialize_model

data = load_data('./Data/scenario/')
model = initialize_model(data, n_hours=8760)

# Access model blocks
model.pv.pprint()          # Solar PV block
model.wind.pprint()         # Wind block
model.storage.pprint()      # Storage block
model.thermal.pprint()      # Thermal block
model.hydro.pprint()        # Hydropower block
model.nuclear.pprint()      # Nuclear block (parameters only)
model.demand.pprint()       # Demand block (parameters only)
```
for example, if you run:

    ```python
    model.thermal.heat_rate.pprint()
    ```

You can obtain:

    ```python
    heat_rate : Size=13, Index=thermal.plants_set, Domain=Any, Default=None, Mutable=False
    Key  : Value
    106c :   1.0
    147c :   1.0
    162c :   1.0
    163c :   1.0
    167c :   1.0
    170c :   1.0
    221c :   1.0
    223c :   1.0
    224c :   1.0
    235c :   1.0
    241c :   1.0
     83c :   1.0
     98c :   1.0
    ```

## Zonal Model Structure (`AreaTransportationModelNetwork`)

When `formulations.csv` includes:

```csv
Component,Formulation
Network,AreaTransportationModelNetwork
```

`initialize_model(...)` builds a zonal model with top-level network objects and per-area blocks.

Top-level zonal objects:

- `model.A`: set of area IDs.
- `model.area[a]`: area Block for each `a in model.A`.
- `model.L`: set of interconnections (`line_id`).
- `model.line_from[l]`, `model.line_to[l]`: line endpoints.
- `model.LineCap_FT[l,h]`, `model.LineCap_TF[l,h]`: directional hourly capacities.
- `model.f[l,h]`: signed interregional flow.
- `model.f_upper[l,h]`, `model.f_lower[l,h]`: directional capacity constraints.
- `model.L_in[a]`, `model.L_out[a]`: incoming and outgoing lines by area.

Accessing per-area blocks:

```python
# Example: inspect all area blocks
for a in model.A:
    print(f"Area: {a}")
    model.area[a].pprint()

# Example: inspect area-specific demand and thermal generation
a0 = list(model.A)[0]
print(model.area[a0].demand.ts_parameter[1])
print(model.area[a0].thermal.total_generation)
```

Accessing network objects:

```python
# Example: inspect one line and one hour
l0 = list(model.L)[0]
h0 = list(model.h)[0]

print(model.line_from[l0], model.line_to[l0])
print(model.LineCap_FT[l0, h0], model.LineCap_TF[l0, h0])
print(model.f[l0, h0])
print(model.f_upper[l0, h0].expr)
print(model.f_lower[l0, h0].expr)
```

Zonal supply balance constraints live on each area block:

- `model.area[a].SupplyBalance[h]`

System-wide clean-generation share is top-level:

- `model.GenMix_Share`

## Model Components

### Sets

Key model sets:

```python
# Hourly time set (1-based indexing)
print(len(model.h))  # e.g., 8760

# VRE plant sets
print(list(model.pv.plants_set))    # ['101', '202', '303', ...]
print(list(model.wind.plants_set))  # ['501', '602', ...]

# Storage technology sets
print(list(model.storage.j))  # All storage techs: ['Li-Ion', 'CAES', 'PHS', 'H2']
print(list(model.storage.b))  # Coupled techs: ['Li-Ion', 'PHS']

# Thermal unit set
print(list(model.thermal.plants_set))  # ['GasCC_1', ...]

# Budget set (if using budget formulation)
if hasattr(model.hydro, 'budget_set'):
    print(list(model.hydro.budget_set))  # [1, 2, ..., 12] for monthly
```

### Parameters

Access model parameters:

```python
# System-level parameters
print(f"Discount rate: {model.r.value}")
print(f"Carbon-free target: {model.GenMix_Target.value}")

# Time-series parameters
print(f"Hour 1 load: {model.demand.ts_parameter[1]} MW")
print(f"Hour 1 nuclear: {model.nuclear.ts_parameter[1]} MW")

# VRE parameters
solar_plant = list(model.pv.plants_set)[0]
print(f"Solar plant {solar_plant} CAPEX: {model.pv.CAPEX_M[solar_plant]} $/kW")
print(f"Solar plant {solar_plant} capacity: {model.pv.plant_max_capacity[solar_plant]} MW")

# Storage parameters
print(f"Li-Ion efficiency: {model.storage.data['Eff', 'Li-Ion']}")
print(f"Li-Ion E_Capex: {model.storage.data['E_Capex', 'Li-Ion']} $/kWh")
```

### Variables

Model decision variables:

```python
from sdom.common.utilities import safe_pyomo_value

# VRE installed capacity (continuous variables)
for plant in model.pv.plants_set:
    capacity = safe_pyomo_value(model.pv.plant_installed_capacity[plant])
    print(f"Solar plant {plant}: {capacity:.2f} MW")

# VRE generation (continuous, hourly)
gen_h1 = safe_pyomo_value(model.pv.generation[1])
print(f"Solar generation hour 1: {gen_h1:.2f} MW")

# Storage variables
for tech in model.storage.j:
    pcha = safe_pyomo_value(model.storage.Pcha[tech])
    pdis = safe_pyomo_value(model.storage.Pdis[tech])
    ecap = safe_pyomo_value(model.storage.Ecap[tech])
    print(f"{tech}: Pcha={pcha:.2f} MW, Pdis={pdis:.2f} MW, Ecap={ecap:.2f} MWh")

# Storage state of charge (hourly)
soc_h100 = safe_pyomo_value(model.storage.SOC[100, 'Li-Ion'])
print(f"Li-Ion SOC at hour 100: {soc_h100:.2f} MWh")

# Thermal capacity and generation
thermal_cap = safe_pyomo_value(model.thermal.total_installed_capacity)
thermal_gen_h1 = safe_pyomo_value(model.thermal.generation[1, 'GasCC_1'])
print(f"Thermal capacity: {thermal_cap:.2f} MW")
print(f"Thermal gen hour 1: {thermal_gen_h1:.2f} MW")
```

### Expressions

Computed expressions (not variables):

```python
# Total installed capacity expressions
total_solar = safe_pyomo_value(model.pv.total_installed_capacity)
total_wind = safe_pyomo_value(model.wind.total_installed_capacity)
print(f"Total solar: {total_solar:.2f} MW")
print(f"Total wind: {total_wind:.2f} MW")

# Cost expressions
solar_capex = safe_pyomo_value(model.pv.capex_cost_expr)
solar_fom = safe_pyomo_value(model.pv.fixed_om_cost_expr)
print(f"Solar CAPEX: ${solar_capex:,.2f}")
print(f"Solar FOM: ${solar_fom:,.2f}")

# Total generation expressions
total_solar_gen = safe_pyomo_value(model.pv.total_generation)
print(f"Total solar generation: {total_solar_gen:.2f} MWh")
```

### Constraints

Model constraints are organized by block:

```python
# List all constraints
for constraint in model.component_objects(pyo.Constraint, active=True):
    print(f"Constraint: {constraint.name}")
    if constraint.is_indexed():
        print(f"  Indices: {len(constraint)} constraints")
    else:
        print(f"  Single constraint")
```

Key constraint types:

- **Energy Balance** (`system_energy_balance_rule`): Supply = Demand every hour
- **Carbon Target** (`GenMix_constraint`): Clean energy ≥ target × total generation
- **VRE Balance**: Generation ≤ CF × Capacity for each hour/plant
- **Storage Dynamics**: State of charge evolution constraints
- **Storage Bounds**: SOC within [0, Energy Capacity]
- **Thermal Bounds**: Generation within [Min, Max Capacity]
- **Hydro Budget**: Energy generation sums match budget (if applicable)

## Inspecting the Model

### Print Model Summary

```python
# Model statistics
print(f"Model name: {model.name}")
model.pprint()  # Warning: very verbose for large models!

# Constraint counts
from tests.utils_tests import get_n_eq_ineq_constraints
counts = get_n_eq_ineq_constraints(model)
print(f"Equality constraints: {counts['equality']}")
print(f"Inequality constraints: {counts['inequality']}")
```

### Examine Specific Constraints

```python
import pyomo.environ as pyo

# Energy balance constraint (one per hour)
balance_h1 = model.system_energy_balance[1]
print(f"Balance constraint hour 1: {balance_h1.expr}")

# GenMix constraint
genmix = model.GenMix_constraint
print(f"GenMix constraint: {genmix.expr}")

# Storage SOC dynamics (example for hour 1, Li-Ion)
if (1, 'Li-Ion') in model.storage.storage_charge_discharge_dynamics:
    dynamics = model.storage.storage_charge_discharge_dynamics[1, 'Li-Ion']
    print(f"Storage dynamics constraint: {dynamics.expr}")
```

### Display Variable Bounds

```python
# Check variable bounds
for tech in model.storage.j:
    var = model.storage.Pcha[tech]
    print(f"{tech} Pcha bounds: [{var.lb}, {var.ub}]")
    
for h in list(model.h)[:5]:  # First 5 hours
    var = model.pv.generation[h]
    print(f"Solar gen hour {h} bounds: [{var.lb}, {var.ub}]")
```

## Model Modifications

### Changing Parameters Between Runs

```python
# Load data and initialize model once
data = load_data('./Data/scenario/')
model = initialize_model(data, n_hours=8760)

# Change GenMix_Target (mutable parameter)
model.GenMix_Target = 0.90  # 90% clean energy
results_90 = run_solver(model, solver_config)

model.GenMix_Target = 0.95  # 95% clean energy
results_95 = run_solver(model, solver_config)

model.GenMix_Target = 0.99  # 99% clean energy
results_99 = run_solver(model, solver_config)
```

### Adding Custom Constraints

```python
import pyomo.environ as pyo

# Add minimum wind capacity constraint
def min_wind_capacity_rule(model):
    return model.wind.total_installed_capacity >= 10000  # 10 GW minimum

model.min_wind_constraint = pyo.Constraint(rule=min_wind_capacity_rule)

# Add maximum solar/wind ratio
def max_solar_wind_ratio_rule(model):
    return model.pv.total_installed_capacity <= 2 * model.wind.total_installed_capacity

model.max_ratio_constraint = pyo.Constraint(rule=max_solar_wind_ratio_rule)
```

## Debugging Model Issues

### Check for Infeasibility

```python
from pyomo.util.infeasible import log_infeasible_constraints

# After failed solve
results_list, best_result, solver_result = run_solver(model, solver_config)

if solver_result.solver.termination_condition != pyo.TerminationCondition.optimal:
    print("Model is infeasible or suboptimal")
    log_infeasible_constraints(model)
```

### Validate Model Construction

```python
# Check that variables are defined
assert hasattr(model.pv, 'generation'), "Solar generation variable missing"
assert hasattr(model.storage, 'SOC'), "Storage SOC variable missing"

# Check that sets are populated
assert len(model.pv.plants_set) > 0, "No solar plants loaded"
assert len(model.storage.j) > 0, "No storage technologies"

# Check parameter values
assert model.r.value > 0, "Discount rate must be positive"
assert 0 <= model.GenMix_Target.value <= 1, "GenMix_Target out of range"
```

## Advanced: Direct Pyomo Operations

```python
import pyomo.environ as pyo

# Write model to file
model.write('sdom_model.lp', io_options={'symbolic_solver_labels': True})

# Get solver results details
print(f"Solver status: {solver_result.solver.status}")
print(f"Termination condition: {solver_result.solver.termination_condition}")
print(f"Solve time: {solver_result.solver.time:.2f} seconds")

# Access dual values (shadow prices) if solver supports
if hasattr(solver_result, 'problem'):
    print(f"Objective value: {solver_result.problem.lower_bound}")
    print(f"Best bound: {solver_result.problem.upper_bound}")
```

## Model Formulation Files

The model formulation is split across multiple files in `src/sdom/models/`:

- `formulations_system.py`: Objective function and system constraints
- `formulations_vre.py`: Solar and wind variables/constraints
- `formulations_storage.py`: Storage variables/constraints
- `formulations_thermal.py`: Thermal unit variables/constraints
- `formulations_hydro.py`: Hydropower constraints
- `formulations_imports_exports.py`: Cross-border trade
- `models_utils.py`: Helper functions for expressions and constraints

## Next Steps

- [View API documentation](../api/index.md)
- [Explore source code on GitHub](https://github.com/Omar0902/SDOM)
