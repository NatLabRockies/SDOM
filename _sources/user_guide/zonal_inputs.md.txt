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

Required in zonal mode.

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

Example:

```csv
sc_gid,area_id,capacity,CAPEX_M,trans_cap_cost,FOM_M
132876,A1,430.68,708.55,5323.33,8.29
Nordeste,A2,1.0,6209.28,0,94.08
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

These remain plant-keyed and do not require `@area_id@` tags.

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
