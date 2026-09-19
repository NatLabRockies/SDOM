# Zonal Inputs

This page documents all CSV inputs used when running SDOM with:

```csv
Component,Formulation
Network,AreaTransportationModelNetwork
```

Use this together with [Inputs](inputs.md).

## Zonal Conventions

- `@` is a reserved delimiter in wide CSV headers.
- Wide files use `<entity>@<area_id>@` columns.
- Within one file, non-key columns must be all tagged or all untagged.
- `area_id` values must be consistent across files.
- In row-oriented files (`CapSolar.csv`, `CapWind.csv`, `Data_BalancingUnits.csv`), IDs must be globally unique across areas.
- `StorageData.csv` allows repeated technology names across areas because headers are tagged (for example `Li-Ion@A1@`, `Li-Ion@A2@`).
- An area with demand and transmission connections may omit all optional technology inputs. Omit its rows from `CapSolar.csv`, `CapWind.csv`, and `Data_BalancingUnits.csv`, and omit its tagged columns from `StorageData.csv`, `lahy_hourly.csv`, `Nucl_hourly.csv`, and `otre_hourly.csv`. SDOM treats the missing technologies as empty sets and missing fixed-generation profiles as zero, so the area can be supplied through inter-area transfers.

## Network Selector

### formulations.csv

Add a `Network` row:

```csv
Component,Formulation
Network,AreaTransportationModelNetwork
```

Valid values:

- `CopperPlateNetwork`
- `AreaTransportationModelNetwork`

If `Network` is missing, SDOM defaults to `CopperPlateNetwork`.

## New Zonal Files

### areas.csv

Optional in zonal mode. When present, it declares the allowed `area_id` values.
When omitted, SDOM infers areas from tagged wide-file headers and `area_id`
columns in row-oriented files. Use `areas.csv` when you need explicit area
descriptions or validation that referenced areas are declared.

| Column | Meaning |
|---|---|
| `area_id` | Area identifier (primary key). |
| `description` | Free text description. |

Example:

```csv
area_id,description
A1,North area
A2,South area
```

### interconnections.csv

Required in zonal mode.

| Column | Meaning |
|---|---|
| `line_id` | Line identifier (unique). |
| `from_area` | Origin area ID. |
| `to_area` | Destination area ID. |

Example:

```csv
line_id,from_area,to_area
L_A1_A2,A1,A2
```

### LineCap_FT.csv

Required in zonal mode. Hourly directional capacity for `from_area -> to_area`.

### LineCap_TF.csv

Required in zonal mode. Hourly directional capacity for `to_area -> from_area`.

Both line-cap files:

- Must have the same line columns as `interconnections.csv`.
- Must have the same hour count as the run horizon (`n_hours`).
- Must be non-negative.

Example:

```csv
*Hour,L_A1_A2
1,500
2,500
```

## Modified Existing Files in Zonal Mode

### Row-oriented files with area column

- `CapSolar.csv`
- `CapWind.csv`
- `Data_BalancingUnits.csv`

Add `area_id` column.

For `CapSolar.csv` and `CapWind.csv`, `capacity` (lowercase) remains the installed-capacity upper bound in MW. The optional canonical `MinCapacity` column is the installed-capacity lower bound in MW. If the column is omitted or its value is blank or `NaN`, SDOM uses `0` MW. Provided values must be finite and satisfy `0 <= MinCapacity <= capacity`; `capacity = 0` is valid only when `MinCapacity` is omitted, blank, `NaN`, or `0`. In the Infrasys System interface, this lower bound maps to `min_active_power`.

Example:

```csv
sc_gid,area_id,capacity,MinCapacity,CAPEX_M,trans_cap_cost,FOM_M
132876,A1,430.68,100,708.55,5323.33,8.29
Nordeste,A2,1.0,,6209.28,0,94.08
```

### Wide files with tagged headers

Typical files:

- `Load_hourly.csv`
- `Nucl_hourly.csv`
- `otre_hourly.csv`
- `lahy_hourly.csv`
- `lahy_max_hourly.csv`, `lahy_min_hourly.csv` (if budget hydro)
- `Import_Cap.csv`, `Import_Prices.csv`
- `Export_Cap.csv`, `Export_Prices.csv`
- `StorageData.csv`

Example:

```csv
*Hour,Load@A1@,Load@A2@
1,800,600
2,820,590
```

### Capacity-factor files

- `CFSolar.csv`
- `CFWind.csv`

These remain plant-keyed and do not require `@area_id@` tags. Each capacity
factor column is assigned to an area through the matching `sc_gid` record in
`CapSolar.csv` or `CapWind.csv`; those capacity tables therefore require an
`area_id` column in zonal mode.

## Zonal Support Boundaries

The tagged import/export files describe the common input schema, but enabled
import/export formulations are not currently supported by
`AreaTransportationModelNetwork`. Zonal initialization also rejects resiliency
formulations. Select `NotModel` for these components in zonal runs.

## CopperPlate Aggregation Fallback

If zonal data is loaded while `Network=CopperPlateNetwork`, SDOM aggregates all areas into a single synthetic `default` area.

High-level behavior:

- Hourly demand and capacities are summed.
- Import/export prices are capacity-weighted averaged.
- Interconnection and line-cap files are ignored.
- A warning is logged.

## Validation Summary

Common validation errors in zonal mode:

- Missing required files (`interconnections.csv`, `LineCap_FT.csv`, `LineCap_TF.csv`).
- Unknown area IDs in tagged columns or topology.
- Mixed tagged and untagged columns in a single wide file.
- Duplicate `line_id` or duplicate `(from_area, to_area)` pairs.
- Negative line capacities.
- Duplicate plant IDs across areas for row-oriented VRE and balancing-unit files.
