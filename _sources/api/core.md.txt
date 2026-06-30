# Core Optimization Functions

Main functions for running SDOM optimizations.

## Model Initialization

```{eval-rst}
.. autofunction:: sdom.optimization_main.initialize_model
```

## Solver Configuration

```{eval-rst}
.. autofunction:: sdom.optimization_main.get_default_solver_config_dict

.. autofunction:: sdom.optimization_main.configure_solver
```

## Running Optimization

```{eval-rst}
.. autofunction:: sdom.optimization_main.run_solver
```

## Configuration

```{eval-rst}
.. autofunction:: sdom.config_sdom.configure_logging

.. autoclass:: sdom.config_sdom.ColorFormatter
   :members:
   :special-members: __init__
```

## Example Usage

```python
from sdom import (
    load_data,
    initialize_model, 
    get_default_solver_config_dict,
    run_solver,
    export_results
)

# Load data
data = load_data('./Data/scenario/')

# Initialize model
model = initialize_model(
    data=data,
    n_hours=8760,
    with_resilience_constraints=False
)

# Configure solver
solver_config = get_default_solver_config_dict(
    solver_name="cbc",
    executable_path="./Solver/bin/cbc.exe"
)

# Run optimization - returns OptimizationResults object
results = run_solver(model, solver_config)

# Check if solution is optimal
if results.is_optimal:
    print(f"Total Cost: ${results.total_cost:,.2f}")
    print(f"Wind Capacity: {results.total_cap_wind:.2f} MW")
    print(f"Solar Capacity: {results.total_cap_pv:.2f} MW")
    
    # Access storage capacities
    for tech, cap in results.total_cap_storage_charge.items():
        print(f"{tech} Capacity: {cap:.2f} MW")
    
    # Export results to CSV files
    export_results(results, case="scenario_1")
else:
    print(f"Optimization failed: {results.termination_condition}")
```

## See Also

- {doc}`results` - Full documentation of the `OptimizationResults` class
- {doc}`io_manager` - Data loading and result export functions
