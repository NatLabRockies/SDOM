# Data I/O Manager

Functions for loading input data and exporting results.

`sdom.io_manager` is a compatibility facade over the implementation modules in
`sdom.io`. Existing public imports and call signatures are unchanged; new
internal callers should use the owning module. See
{ref}`io-architecture` for module ownership, validation contracts, and extension
points.

## Data Loading

```{eval-rst}
.. autofunction:: sdom.io_manager.load_data
```

## Formulation Management

```{eval-rst}
.. autofunction:: sdom.io_manager.get_formulation

.. autofunction:: sdom.io_manager.get_network_formulation

.. autofunction:: sdom.io_manager.check_formulation
```

## Thermal Profile Validation

```{eval-rst}
.. autofunction:: sdom.io_manager.validate_thermal_min_dispatch
```

`NoRampsMinDispatchFormulation` conditionally requires
`Thermal_MinDispatchFraction.csv`. Raw headers are checked before parsing;
fractions and enabled thermal capacity bounds retain full precision.
Validation can also be called on an in-memory dictionary without reading files.

## Results Export

```{eval-rst}
.. autofunction:: sdom.io_manager.export_results
```

## Example: Loading Data

```python
from sdom import load_data

# Load data from directory
data = load_data('./Data/my_scenario/')

# Examine loaded data
print(f"Solar plants: {len(data['solar_plants'])}")
print(f"Wind plants: {len(data['wind_plants'])}")
print(f"Storage technologies: {data['STORAGE_SET_J_TECHS']}")

# Access formulation settings
hydro_form = data['formulations']
print(hydro_form)
```

## Example: Exporting Results

```python
from sdom import run_solver, export_results

# Run optimization
results = run_solver(model, solver_config)

# Export results using the OptimizationResults object
if results.is_optimal:
    export_results(
        results=results,
        case="scenario_95pct_clean",
        output_dir="./results_pyomo/"
    )

# This creates the standard result CSV files, including:
# - OutputGeneration_scenario_95pct_clean.csv
# - OutputStorage_scenario_95pct_clean.csv
# - OutputSummary_scenario_95pct_clean.csv
# - OutputMarginalPrices_scenario_95pct_clean.csv (fixed-decision LP hourly marginal prices)

# You can also access the DataFrames directly from results:
generation_df = results.generation_df
storage_df = results.storage_df
summary_df = results.summary_df
```

```{note}
The `export_results` function now accepts an `OptimizationResults` object as the first argument.
See {doc}`results` for details on the `OptimizationResults` class.
```

## Data Dictionary Structure

The `load_data()` function returns a dictionary with these keys:

- `formulations`: Component formulation specifications
- `solar_plants`, `wind_plants`: Lists of plant IDs
- `cf_solar`, `cf_wind`: DataFrames with capacity factors
- `cap_solar`, `cap_wind`: DataFrames with CAPEX and capacity data
- `load_data`: Hourly demand DataFrame
- `nuclear_data`: Hourly nuclear generation
- `large_hydro_data`: Hourly hydro generation
- `other_renewables_data`: Hourly other renewables
- `storage_data`: Storage technology parameters
- `STORAGE_SET_J_TECHS`: List of all storage technologies
- `STORAGE_SET_B_TECHS`: List of coupled storage technologies
- `thermal_data`: Thermal unit parameters
- `scalars`: System-level parameters
- `large_hydro_max`, `large_hydro_min` (optional): Hydro bounds for budget formulations
- `thermal_min_dispatch_fraction` (optional): Hourly fractions for `NoRampsMinDispatchFormulation`
- `cap_imports`, `cap_exports` (optional): Trade capacity limits
- `price_imports`, `price_exports` (optional): Trade prices

Area and network keys are also present for legacy single-area inputs, using
default-area views and empty topology/capacity tables where appropriate:

- `areas`: list of area descriptors
- `lines`: list of line descriptors (`line_id`, `from_area`, `to_area`)
- `line_cap_ft`, `line_cap_tf`: directional line-capacity DataFrames
- `per_area_demand`, `per_area_pv_plants`, `per_area_wind_plants`, `per_area_balancing_units`, `per_area_storage`, `per_area_hydro`
- `per_area_nuclear`, `per_area_other_renewables`, `per_area_imports`, `per_area_exports`
- `per_area_capacity_factors_pv`, `per_area_capacity_factors_wind`

`load_data()` behavior by network formulation:

- If `Network` is missing from `formulations.csv`, SDOM defaults to `CopperPlateNetwork`.
- If `Network=AreaTransportationModelNetwork`, SDOM validates and requires `interconnections.csv`, `LineCap_FT.csv`, and `LineCap_TF.csv`.
- If zonal data is present but `Network=CopperPlateNetwork`, SDOM aggregates areas into a single synthetic `default` area and drops transmission topology/capacity files.
