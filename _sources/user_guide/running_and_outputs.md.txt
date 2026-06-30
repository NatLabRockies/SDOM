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
Currently SDOM python package has been tested with the following solvers:

### CBC Solver (Open-Source)
This solver does not have a python package to make the interface, so you need to download the executable and indicate the path of such file:

```python
solver_config = get_default_solver_config_dict(
    solver_name="cbc",
    executable_path="./Solver/bin/cbc.exe"  # Windows
    # executable_path="./Solver/bin/cbc"     # Unix/MacOS
)

# Customize solver options
solver_config["options"]["ratioGap"] = 0.01  # 1% MIP gap
solver_config["solve_keywords"]["timelimit"] = 3600  # 1 hour limit
```

### HiGHS Solver (Open-Source)

```python
solver_config = get_default_solver_config_dict(
    solver_name="highs",
    executable_path=""  # Does not require the path if you import the python package highspy
)
```

### Xpress Solver (Commercial)

FICO Xpress is a high-performance commercial solver. Requires a valid license.

**Installation:**
```bash
# Install xpress package (license required)
pip install xpress
```

**Configuration:**
```python
solver_config = get_default_solver_config_dict(
    solver_name="xpress",
    mip_gap=0.002,      # MIP relative gap (0.2%)
    time_limit=3600,    # Time limit in seconds
)
```

**Xpress-specific options:**
```python
# The configuration automatically uses Xpress control names:
# - miprelstop: MIP relative gap tolerance
# - maxtime: Maximum solve time (seconds)
# - outputlog: Solver output (0=off, 1=on)

# Additional Xpress controls can be added:
solver_config["options"]["threads"] = 4  # Number of threads
solver_config["options"]["presolve"] = 1  # Enable presolve
```

```{note}
Xpress requires a valid license. The license file (xpauth.xpr) should be in your 
Xpress installation directory or specified via environment variables.
```

### Solver Option Reference

| Solver | MIP Gap Option | Time Limit | Notes |
|--------|---------------|------------|-------|
| CBC | `ratioGap` | via `solve_keywords["timelimit"]` | Requires executable path |
| HiGHS | `mip_rel_gap` | via `solve_keywords["timelimit"]` | Uses `appsi_highs` interface |
| Xpress | `miprelstop` | `maxtime` | Uses `xpress_direct` interface |


## Outputs/Results

In the path specified by "output_dir", sdom will writhe the following output csv files:

| File name                          | Description                                              |
|-------------------------------------|----------------------------------------------------------|
| OutputGeneration_CASENAME.csv      | Hourly generation results aggregated by technology, curtailment, imports/exports and Load.      |
| OutputStorage_CASENAME.csv         | Hourly storage operation results (charging/discharging and SOC). |
| OutputSummary_CASENAME.csv         | Summary of key simulation results and statistics.        |
| OutputThermalGeneration_CASENAME.csv | Hourly results for thermal generation plants.           |
| OutputInstalledPowerPlants_CASENAME.csv | Installed capacity for each individual power plant (Solar PV, Wind, Thermal). |
| OutputInterregionalExchanges_CASENAME.csv | Zonal-only line flows (`line_id`, `from_area`, `to_area`, `hour`, signed and directional flows, directional capacity and utilization). |

## Zonal Results Access

When using `Network=AreaTransportationModelNetwork`, `run_solver` populates zonal fields in `OptimizationResults`:

- `results.is_zonal`
- `results.areas`, `results.lines`
- `results.area_generation_df`, `results.area_storage_df`, `results.area_thermal_generation_df`, `results.area_installed_plants_df`, `results.area_summary_df`
- `results.interregional_exchanges_df`

`results.summary_df` is intentionally empty in the zonal path; use `results.area_summary_df` for per-area summary tables.

## Troubleshooting
### Solver Performance

For large problems:
- Increase MIP gap: `solver_config["options"]["mip_rel_gap"] = 0.01`
- Set time limit: `solver_config["solve_keywords"]["timelimit"] = 7200`

### Infeasible Solutions

... in progress...

---

## Visualising Results

After running a single optimisation, use `plot_results()` from the
`analytic_tools` sub-package to generate a standard set of publication-ready
figures in one call.

### Generated figures

| File | Description |
|---|---|
| `capacity_donut.png` | Installed capacity by technology (donut chart) |
| `capacity_generation_donuts.png` | Side-by-side capacity and total generation donuts |
| `heatmap_<column>.png` | One 365×24 hourly dispatch heatmap per generation technology |

### Basic usage

```python
from sdom import load_data, initialize_model, run_solver, get_default_solver_config_dict
from sdom.analytic_tools import plot_results

data = load_data("./Data/no_exchange_run_of_river/")
model = initialize_model(data, n_hours=8760)
solver_config = get_default_solver_config_dict(solver_name="highs", executable_path="")
results = run_solver(model, solver_config)

if results.is_optimal:
    # Save all plots to ./results_pyomo/my_scenario/plots/
    plot_results(results, output_dir="./results_pyomo/my_scenario/")
```

Plots are saved to `<output_dir>/plots/`.  To override the plots directory
explicitly, use the `plots_dir` parameter instead:

```python
plot_results(results, plots_dir="./my_output_dir/figures/")
```

```{note}
`plot_results()` silently skips the run and logs a warning if the result is
not optimal — it never raises on infeasible solutions.
```

### Controlling the output directory

| Parameter | Behaviour |
|---|---|
| `output_dir="./results/"` | Plots saved to `./results/plots/` |
| `plots_dir="./figures/"` | Plots saved directly to `./figures/` |

Both parameters are optional but at least one must be provided, otherwise a
`ValueError` is raised.

### Full workflow example

```python
from sdom import (
    load_data, initialize_model, run_solver,
    export_results, get_default_solver_config_dict,
)
from sdom.analytic_tools import plot_results

OUTPUT_DIR = "./results_pyomo/base_scenario/"

data        = load_data("./Data/no_exchange_run_of_river/")
model       = initialize_model(data, n_hours=8760)
solver_cfg  = get_default_solver_config_dict(solver_name="highs", executable_path="")
results     = run_solver(model, solver_cfg)

if results.is_optimal:
    # Export CSV tables
    export_results(results, case="base_scenario", output_dir=OUTPUT_DIR)

    # Generate plots alongside the CSV outputs
    plot_results(results, output_dir=OUTPUT_DIR)

    print(f"Total cost : ${results.total_cost:,.0f}")
    print(f"Solar PV   : {results.total_cap_pv:.1f} MW")
    print(f"Wind       : {results.total_cap_wind:.1f} MW")
```

---

## Running Parametric & Sensitivity Studies

To run multi-dimensional parameter sweeps in parallel (e.g., sweeping `GenMix_Target`, storage CAPEX, or load growth factors), use the built-in `ParametricStudy` API.

See the dedicated guide: [Parametric & Sensitivity Analysis](parametric_analysis.md)

## Next Steps

- [Explore the Pyomo model structure](exploring_model.md)
- [Parametric & Sensitivity Analysis](parametric_analysis.md)
- [View API reference](../api/index.md)
