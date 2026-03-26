# Parametric & Sensitivity Analysis

SDOM's `ParametricStudy` class lets you run a multi-dimensional sensitivity
study with a single Python script.  You define which parameters to vary and
over what values, and SDOM automatically generates every combination
(Cartesian product), solves each one in a separate worker process, and
writes per-case CSV outputs plus a consolidated summary.

---

## When to use parametric analysis

| Use case | Recommended approach |
|---|---|
| Single scenario | `run_solver()` directly |
| Sweep one parameter (e.g. `GenMix_Target`) | `ParametricStudy` with one `add_scalar_sweep` |
| Full sensitivity across multiple parameters | `ParametricStudy` with multiple sweep calls |
| 2050 projections at different load growth rates | `ParametricStudy` with `add_ts_sweep` on `load_data` |

---

## Quick-start example

```python
import sdom
from sdom.parametric import ParametricStudy

# 1 ── Load base data
data = sdom.load_data("./Data/no_exchange_hydro_daily_budget_multiple_balancing_p95")

# 2 ── Configure solver
solver_cfg = sdom.get_default_solver_config_dict(solver_name="highs")

# 3 ── Build the study
study = ParametricStudy(
    base_data=data,
    solver_config=solver_cfg,
    n_hours=8760,
    output_dir="./results_pyomo/parametric/",
    n_cores=4,          # capped automatically at cpu_count - 1
)

# Scalar sweep: replace data["scalars"].loc["GenMix_Target", "Value"]
study.add_scalar_sweep("scalars", "GenMix_Target", [0.70, 0.80, 0.90, 1.00])

# Storage factor sweep: multiply data["storage_data"].loc["P_Capex"] (all techs)
study.add_storage_factor_sweep("P_Capex", [0.7, 0.8, 1.0])

# Time-series sweep: multiply the "Load" column of data["load_data"]
study.add_ts_sweep("load_data", [0.95, 1.00, 1.05])

# 4 ── Run — 4 × 3 × 3 = 36 cases
all_results = study.run()

# 5 ── Inspect
for res in all_results:
    if res.is_optimal:
        print(f"{res.gen_mix_target:.2f}  cost={res.total_cost:,.0f}")
```

---

## Sweep types

### Scalar sweep — `add_scalar_sweep(data_key, param_name, values)`

Replaces a single entry in a row-indexed DataFrame with discrete absolute values.

```python
# data["scalars"].loc["GenMix_Target", "Value"] → 0.7, 0.8, …
study.add_scalar_sweep("scalars", "GenMix_Target", [0.7, 0.8, 0.9, 1.0])
```

### Storage factor sweep — `add_storage_factor_sweep(param_name, factors)`

Multiplies the entire `data["storage_data"].loc[param_name]` row (all
storage technologies) by each factor uniformly.

```python
# data["storage_data"].loc["P_Capex"] *= 0.7  /  *= 0.8  /  *= 1.0
study.add_storage_factor_sweep("P_Capex", [0.7, 0.8, 1.0])
```

### Time-series sweep — `add_ts_sweep(ts_key, factors)`

Multiplies the numeric column of a time-series DataFrame by each factor.
The column name is resolved automatically:

| `ts_key` | Column scaled |
|---|---|
| `"load_data"` | `"Load"` |
| `"large_hydro_data"` | `"LargeHydro"` |
| `"large_hydro_max"` | `"LargeHydro_max"` |
| `"large_hydro_min"` | `"LargeHydro_min"` |
| `"cap_imports"` | `"Imports"` |
| `"price_imports"` | `"Imports_price"` |
| `"cap_exports"` | `"Exports"` |
| `"price_exports"` | `"Exports_price"` |

```python
study.add_ts_sweep("load_data", [0.9, 1.0, 1.1])
study.add_ts_sweep("large_hydro_max", [0.8, 1.0])
```

---

## Cartesian product and case naming

Every combination of all registered sweeps is evaluated.  A study with
3 scalar values, 2 storage factors, and 3 load factors produces
**3 × 2 × 3 = 18 cases**.

Each case receives a deterministic, filesystem-safe name derived from its
parameter values, for example:

```
GenMix_Target=0.90_P_Capexx0.8_load_datax1.05
```

This name is used as the `case_name` in `run_solver` and as the
sub-directory name under `output_dir`.

```{note}
If two combinations happen to produce the same safe name after character
substitution (e.g. both `1.0/2` and `1.0_2` collapse to `1.0_2`), SDOM
automatically appends the case's Cartesian-product index as a suffix
(`<name>_<index>`) so every case directory is always unique.
```

---

## Output structure

```
output_dir/
├── GenMix_Target=0.70_P_Capexx0.7_load_datax0.95/
│   ├── OutputGeneration_<case_name>.csv
│   ├── OutputStorage_<case_name>.csv
│   ├── OutputSummary_<case_name>.csv
│   └── OutputThermalGeneration_<case_name>.csv   # only if >1 thermal plant
├── GenMix_Target=0.70_P_Capexx0.7_load_datax1.00/
│   └── ...
└── parametric_summary.csv
```

`parametric_summary.csv` has one row per case and always includes:

| Column | Description |
|---|---|
| `case_name` | Unique identifier |
| `<data_key>.<param_name>` | Value used for each scalar sweep |
| `storage_data.<param>_factor` | Factor used for each storage sweep |
| `<ts_key>_factor` | Factor used for each ts sweep |
| `is_optimal` | `True` if the solver found an optimal solution |
| `total_cost` | Objective value (USD) |
| `solver_status` | Solver status string |
| `termination_condition` | Solver termination condition |

---

## Real-world example — 2050 projections

```python
import sdom
from sdom.parametric import ParametricStudy

SCALING_2050 = 1.49   # projected load growth relative to base year

data = sdom.load_data("./data/case_2050_WY2023")
solver_cfg = sdom.get_default_solver_config_dict(solver_name="highs")

study = ParametricStudy(
    base_data=data,
    solver_config=solver_cfg,
    n_hours=8760,
    output_dir="./results/case_2050_WY2023",
    n_cores=None,         # use all available cores minus one
)

study.add_scalar_sweep("scalars", "GenMix_Target", [0.0, 0.8, 0.9, 1.0])
study.add_storage_factor_sweep("P_Capex", [1.0, 0.8, 0.7])
study.add_ts_sweep(
    "load_data",
    [0.9 * SCALING_2050, 1.0 * SCALING_2050, 1.1 * SCALING_2050],
)

# 4 × 3 × 3 = 36 cases
results = study.run()

# Quick summary
optimal = [r for r in results if r.is_optimal]
print(f"{len(optimal)}/{len(results)} cases solved optimally")
```

---

## Performance guidance

- **`n_cores`** — Each worker process builds its own Pyomo model and runs
  the solver independently.  Memory consumption scales roughly linearly with
  the number of *concurrent* workers — not with the total sweep size — because
  each worker deep-copies the base data **inside its own process** (lazy copy),
  so the parent process holds only one copy of the data at all times.
  A safe starting point is 4 workers; increase only if memory usage is comfortable.
  Pass `n_cores=None` to use all available cores minus one.

- **Large sweeps** — For 50+ cases, consider whether `output_dir` is on a
  fast local disk; solver log files (HiGHS/CBC) are written per process and
  may create I/O contention on networked drives.

- **`n_hours=72` for debugging** — Use a short horizon to verify sweep
  logic and case naming before committing to a full 8760-hour run.

- **Failed cases** — `ParametricStudy.run()` never raises on individual case
  failures.  Inspect `result.is_optimal` and `result.termination_condition`
  per result, and check `parametric_summary.csv` for a consolidated view.
  Failed cases have `total_cost=NaN` in the summary so they are
  distinguishable from valid zero-cost results.

---

## Visualising parametric results

After calling `study.run()`, use `plot_parametric_results()` from the
`analytic_tools` sub-package to automatically produce:

- **Per-case plots** — capacity donut, generation donut, and hourly dispatch
  heatmaps for every optimal case, saved under
  `<output_dir>/<case_name>/plots/`.
- **Cross-case comparison plots** — grouped stacked-bar charts for installed
  capacity and total generation, and a curtailment bar chart, saved under
  `<output_dir>/sensitivity_plots/`.

### Grouping strategy

Use the `group_by`, `hue_by`, and `facet_by` parameters to control how cases
are arranged on the comparison plots.  Pass the same parameter name that was
registered with the sweep methods.

| Parameter | Role |
|---|---|
| `group_by` | X-axis clusters (required) |
| `hue_by` | Bars within each cluster (optional) |
| `facet_by` | One complete figure per value of this dimension (optional) |

### Quick-start example

```python
import sdom
from sdom.parametric import ParametricStudy
from sdom.analytic_tools import plot_parametric_results

data       = sdom.load_data("./Data/no_exchange_run_of_river/")
solver_cfg = sdom.get_default_solver_config_dict(solver_name="highs", executable_path="")

study = ParametricStudy(
    base_data=data,
    solver_config=solver_cfg,
    n_hours=8760,
    output_dir="./results_pyomo/parametric/",
    n_cores=4,
)

study.add_scalar_sweep("scalars", "GenMix_Target", [0.70, 0.80, 0.90, 1.00])
study.add_storage_factor_sweep("P_Capex", [0.7, 0.8, 1.0])

# 4 × 3 = 12 cases
results = study.run()

# Plot: GenMix_Target on x-axis, P_Capex factor as the hue
plot_parametric_results(
    study,
    results,
    group_by="GenMix_Target",
    hue_by="P_Capex",
)
```

### Three-dimensional sweep with faceting

```python
study.add_scalar_sweep("scalars",  "GenMix_Target", [0.80, 0.90, 1.00])
study.add_storage_factor_sweep("P_Capex",           [0.7, 1.0])
study.add_ts_sweep("load_data",                     [0.95, 1.00, 1.05])

# 3 × 2 × 3 = 18 cases
results = study.run()

# One figure per load factor, GenMix_Target on x-axis, P_Capex as hue
plot_parametric_results(
    study,
    results,
    group_by="GenMix_Target",
    hue_by="P_Capex",
    facet_by="load_data",
)
```

Faceted output under `<output_dir>/sensitivity_plots/`:

```
sensitivity_plots/
├── capacity_by_technology_load_data=0.95.png
├── capacity_by_technology_load_data=1.0.png
├── capacity_by_technology_load_data=1.05.png
├── generation_by_technology_load_data=0.95.png
├── ...
└── curtailment_load_data=1.05.png
```

### Skipping per-case plots

For large sweeps (50+ cases) the per-case donut and heatmap generation can be
slow.  Disable it with `plot_per_case=False`:

```python
plot_parametric_results(
    study,
    results,
    group_by="GenMix_Target",
    hue_by="P_Capex",
    plot_per_case=False,   # only generate cross-case comparison plots
)
```

### Controlling the output directory

By default, `plot_parametric_results()` writes to `study.output_dir`.  Pass
`output_dir` explicitly to override:

```python
plot_parametric_results(
    study, results,
    group_by="GenMix_Target",
    output_dir="./my_custom_output_dir/",
)
```

### Handling large sweeps

When the number of x-axis clusters multiplied by the number of hues exceeds
`max_cases_per_figure` (default `24`), the plot is automatically split into
multiple figures:

```
sensitivity_plots/
├── capacity_by_technology_part1.png
├── capacity_by_technology_part2.png
└── ...
```

Adjust the threshold with the `max_cases_per_figure` parameter:

```python
plot_parametric_results(
    study, results,
    group_by="GenMix_Target",
    max_cases_per_figure=12,   # split more aggressively
)
```

### Complete workflow example

```python
import sdom
from sdom.parametric import ParametricStudy
from sdom.analytic_tools import plot_parametric_results

OUTPUT_DIR = "./results_pyomo/sensitivity_2050/"

data       = sdom.load_data("./Data/no_exchange_run_of_river/")
solver_cfg = sdom.get_default_solver_config_dict(solver_name="highs", executable_path="")

study = ParametricStudy(
    base_data=data,
    solver_config=solver_cfg,
    n_hours=8760,
    output_dir=OUTPUT_DIR,
    n_cores=4,
)

study.add_scalar_sweep("scalars",  "GenMix_Target", [0.0, 0.8, 0.9, 1.0])
study.add_storage_factor_sweep("P_Capex",           [1.0, 0.8])
study.add_ts_sweep("load_data",                     [0.9, 1.0, 1.1])

# 4 × 2 × 3 = 24 cases
results = study.run()

# Summary statistics
optimal = [r for r in results if r.is_optimal]
print(f"{len(optimal)}/{len(results)} cases solved optimally")

# Cross-case comparison plots + per-case individual plots
plot_parametric_results(
    study,
    results,
    group_by="GenMix_Target",
    hue_by="P_Capex",
    facet_by="load_data",
)
```

```{tip}
Dimension names passed to `group_by`, `hue_by`, and `facet_by` must match
exactly the parameter names registered with `add_scalar_sweep` (the
`param_name` argument), `add_storage_factor_sweep` (the `param_name`
argument), or `add_ts_sweep` (the `ts_key` argument).  Use
`study.case_metadata[0].keys()` to inspect the available names after a run.
```

