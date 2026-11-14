# Zonal Model Guide

This guide describes how to run and inspect the zonal SDOM model.

## When to Use Zonal Mode

Use zonal mode when you need:

- Multiple geographic areas with separate demand/resource profiles.
- Inter-area transfer limits.
- Area-level outputs and interregional flow outputs.

## Minimal Setup

1. Set `Network` in `formulations.csv` to `AreaTransportationModelNetwork`.
2. Provide `areas.csv`, `interconnections.csv`, `LineCap_FT.csv`, and `LineCap_TF.csv`.
3. Ensure zonal input encoding is valid (see [Zonal Inputs](zonal_inputs.md)).

## Run Example

```python
from sdom import load_data, initialize_model, run_solver, get_default_solver_config_dict

data = load_data("./Data/zonal_test/")
model = initialize_model(data, n_hours=24)
solver_cfg = get_default_solver_config_dict(solver_name="highs")
results = run_solver(model, solver_cfg)

print(results.is_zonal)
print(results.areas)
print(results.lines)
print(results.interregional_exchanges_df.head())
```

## Pyomo Object Access

Top-level zonal objects:

- `model.A`, `model.area`
- `model.L`, `model.line_from`, `model.line_to`
- `model.LineCap_FT`, `model.LineCap_TF`
- `model.f`, `model.f_upper`, `model.f_lower`, `model.f_FT`, `model.f_TF`

Per-area objects (for each `a`):

- `model.area[a].demand`
- `model.area[a].pv`, `model.area[a].wind`, `model.area[a].thermal`
- `model.area[a].storage`, `model.area[a].hydro`
- `model.area[a].nuclear`, `model.area[a].other_renewables`
- `model.area[a].SupplyBalance`

System-wide constraint:

- `model.GenMix_Share`

## Results and Outputs

Zonal-specific result fields:

- `results.is_zonal`
- `results.areas`, `results.lines`
- `results.area_generation_df`, `results.area_storage_df`, `results.area_thermal_generation_df`, `results.area_installed_plants_df`, `results.area_summary_df`
- `results.interregional_exchanges_df`

CSV export adds:

- `OutputInterregionalExchanges_<case>.csv`

## Known Limits (Current Scope)

- Resiliency with `AreaTransportationModelNetwork` is not implemented.
- Imports/exports under zonal path are currently restricted to `NotModel`.
- Transmission expansion cost is a placeholder (`Z^trans = 0`).
- Per-area parametric sweeps are deferred.
