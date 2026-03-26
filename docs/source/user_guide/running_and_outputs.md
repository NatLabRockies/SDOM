# Running SDOM and Understanding Outputs

This guide covers how to run SDOM optimizations and the outputs/results it provides.

## Running an Optimization

### Basic Workflow

```python
from sdom import (
    configure_logging,
    load_data, 
    initialize_model, 
    run_solver,
    get_default_solver_config_dict,
    export_results
)
import logging

# 1. Configure logging (optional but recommended)
configure_logging(level=logging.INFO)

# 2. Load input data
data = load_data('./Data/my_scenario/')

# 3. Initialize the optimization model
model = initialize_model(
    data=data,
    n_hours=8760,  # Full year
    with_resilience_constraints=False,
    model_name="SDOM_MyScenario"
)

# 4. Configure solver
solver_config = get_default_solver_config_dict(
    solver_name="cbc",  # or "highs"
    executable_path="./Solver/bin/cbc.exe"
)

# 5. Run optimization - returns an OptimizationResults object
results = run_solver(model, solver_config)

# 6. Check results and export
if results.is_optimal:
    export_results(results, case="scenario_1", output_dir="./results_pyomo/")
    
    # 7. Access results directly from the OptimizationResults object
    print(f"Optimization Status: {results.termination_condition}")
    print(f"Total System Cost: ${results.total_cost:,.2f}")
    print(f"Total Wind Capacity: {results.total_cap_wind:.2f} MW")
    print(f"Total Solar Capacity: {results.total_cap_pv:.2f} MW")
    
    # Access detailed DataFrames
    generation_df = results.generation_df
    storage_df = results.storage_df
    summary_df = results.summary_df
else:
    print(f"Optimization failed: {results.termination_condition}")
```

```{tip}
The `OptimizationResults` object provides convenient properties like `is_optimal`, 
`total_cost`, `total_cap_wind`, `total_cap_pv`, and dictionaries for storage capacities.
See the [Results API Reference](../api/results.md) for full documentation.
```

### Shorter Time Horizons

For testing or sensitivity analysis, you can run shorter simulations:

```python
# 24-hour test run
model = initialize_model(data, n_hours=24)

# One week (168 hours)
model = initialize_model(data, n_hours=168)

# One month (~730 hours)
model = initialize_model(data, n_hours=730)
```

```{warning}
Budget formulations (monthly/daily hydro) require specific hour multiples. SDOM will automatically adjust and log a warning.
```

## Solver Configuration
Currently SDOM python package has been tested with the following open-source solvers:

### CBC Solver (Open-Source)
This solver does not have a python package to make the interface, so you need to download the executable and indicate the path of such file:

```python
solver_config = get_default_solver_config_dict(
    solver_name="cbc",
    executable_path="./Solver/bin/cbc.exe"  # Windows
    # executable_path="./Solver/bin/cbc"     # Unix/MacOS
)

# Customize solver options
solver_config["options"]["mip_rel_gap"] = 0.01  # 1% MIP gap
solver_config["solve_keywords"]["timelimit"] = 3600  # 1 hour limit
```

### HiGHS Solver (Open-Source)

```python
solver_config = get_default_solver_config_dict(
    solver_name="highs",
    executable_path=""  # Does not require the path if you import the python package highspy
)
```


## Outputs/Results

In the path specified by "output_dir", sdom will writhe the following output csv files:

| File name                          | Description                                              |
|-------------------------------------|----------------------------------------------------------|
| OutputGeneration_CASENAME.csv      | Hourly generation results aggregated by technology, curtailment, imports/exports and Load.      |
| OutputStorage_CASENAME.csv         | Hourly storage operation results (charging/discharging and SOC). |
| OutputSummary_CASENAME.csv         | Summary of key simulation results and statistics.        |
| OutputThermalGeneration_CASENAME.csv | Hourly results for thermal generation plants.           |
| OutputInstalledPowerPlants_CASENAME.csv | Installed capacity for each individual power plant (Solar PV, Wind, Thermal). |

## Troubleshooting
### Solver Performance

For large problems:
- Increase MIP gap: `solver_config["options"]["mip_rel_gap"] = 0.01`
- Set time limit: `solver_config["solve_keywords"]["timelimit"] = 7200`

### Infeasible Solutions

... in progress...


## Running Parametric & Sensitivity Studies

To run multi-dimensional parameter sweeps in parallel (e.g., sweeping `GenMix_Target`, storage CAPEX, or load growth factors), use the built-in `ParametricStudy` API.

See the dedicated guide: [Parametric & Sensitivity Analysis](parametric_analysis.md)

## Next Steps

- [Explore the Pyomo model structure](exploring_model.md)
- [Parametric & Sensitivity Analysis](parametric_analysis.md)
- [View API reference](../api/index.md)
