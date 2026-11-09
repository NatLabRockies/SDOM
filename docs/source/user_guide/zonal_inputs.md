# Zonal Inputs

This page documents all CSV inputs used when running SDOM with:

```csv
Component,Formulation
Network,AreaTransportationModelNetwork
```

Use this together with [Inputs](inputs.md).

The base input guide provides field units and primary equation links for all
technology, profile, cost, and scalar inputs. In zonal mode, those equations
apply within each area's block unless noted otherwise. The additional
**Main use (math)** references below identify network and ownership uses.

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

## Optional Local Capacity Margin

Add `Reserves,CapacityMarginFormulation` to `formulations.csv` and optionally
`capacity_marging_fraction,0.04` to the existing `scalars.csv` under its
`Parameter,Value` header. The exact spelling is intentional. This is one
global dimensionless fraction (4% in this example), applied independently
to every area's gross demand at every hour, not a per-area input.

The default fraction is `0.0`; enabled blank, nonnumeric, nonfinite, and negative
values fail model construction. Values are fractions, never implicitly divided
by 100. Only the exact enabled selection adds equations. A missing row,
`notModel`, or any other nonmatching selection leaves reserves disabled and
does not require or consume this scalar; a scalar row alone cannot enable them.
See [scalar validation and examples](inputs.md#optional-capacity-margin-scalar).

No new files are required. The adequacy duration is fixed at one hour and
cannot be configured. Existing scheduled inter-area net imports count toward
the capability requirement: imports are credited and exports deducted using
the same signed flows as the supply balance. No new inputs or transfer
variables are needed. A demand-only area can meet an enabled zero margin
through scheduled imports, but a positive margin still requires local upward
headroom. Unused remote capability and spare line capacity do not provide
additional reserve transfers. External imports/exports remain unsupported in
zonal mode. Existing network and energy-balance equations are unchanged.
See [capability equations](zonal_math_formulation.md#optional-local-capacity-margin).

| Parameter | Meaning | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `capacity_marging_fraction` | Shared optional margin, default `0.0`; applies to each area's gross hourly demand when enabled. | Dimensionless fraction | float | $m$ in the [local capacity-margin requirement](zonal_math_formulation.md#optional-local-capacity-margin). |

Storage contributes credited supply MW bounded by installed discharge power
and beginning-of-hour SOC. This is not an upward reserve award and does not
depend on scheduled charging/discharging or add another charging obligation.
No new storage input columns are required.

## New Zonal Files

### Conditional thermal minimum-dispatch profile

The [hourly thermal profile](inputs.md#optional-hourly-thermal-minimum-dispatch)
uses the same root `Thermal_MinDispatchFraction.csv` in zonal mode.
Headers are globally unique plant IDs, **not** `plant@area@` columns.
Ownership comes only from `Data_BalancingUnits.csv`'s existing `area_id`.
The global profile is validated before selecting each area's plant columns;
an area without thermal plants receives an hour-only slice. Static global
and per-area ownership/capacity views must agree for directly supplied data.
Copperplate aggregation preserves each plant's fractions separately without
averaging or capacity weighting. No additional per-area profile registry exists.

See the [column and unit table](inputs.md#optional-hourly-thermal-minimum-dispatch)
and [per-area thermal minimum-dispatch equations](zonal_math_formulation.md#optional-thermal-minimum-dispatch).

### areas.csv

Optional in zonal mode. When present, it declares the allowed `area_id` values.
When omitted, SDOM infers areas from tagged wide-file headers and `area_id`
columns in row-oriented files. Use `areas.csv` when you need explicit area
descriptions or validation that referenced areas are declared.

| Column | Meaning | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `area_id` | Area identifier (primary key). | Not applicable; identifier | string | Defines index $a$ in the [area set](zonal_math_formulation.md#sets) and [per-area supply balance](zonal_math_formulation.md#per-area-supply-balance). |
| `description` | Free-text area description. | Not applicable; metadata | string | No optimization equation; descriptive metadata for the [area set](zonal_math_formulation.md#sets). |

Example:

```csv
area_id,description
A1,North area
A2,South area
```

### interconnections.csv

Required in zonal mode.

| Column | Meaning | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `line_id` | Unique line identifier matching line-capacity columns. | Not applicable; identifier | string | Defines index $l$ in the [line set](zonal_math_formulation.md#sets) and [network capacity constraints](zonal_math_formulation.md#network-constraints). |
| `from_area` | Stored origin area of the line's positive-flow direction. | Not applicable; identifier | string | Defines $\mathcal L_{out}(a)$ and signed outflow in [per-area supply balance](zonal_math_formulation.md#per-area-supply-balance). |
| `to_area` | Stored destination area of the line's positive-flow direction. | Not applicable; identifier | string | Defines $\mathcal L_{in}(a)$ and signed inflow in [per-area supply balance](zonal_math_formulation.md#per-area-supply-balance). |

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

| File | Column | Meaning | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- | --- |
| Both line-cap files | `*Hour` | One-based hourly index. | Hour index; one-hour steps | int | Index $h$ in [network capacity constraints](zonal_math_formulation.md#network-constraints). |
| `LineCap_FT.csv` | `<line_id>` | Maximum power in the stored `from_area` to `to_area` direction. | MW | float | $\overline F^{FT}_{l,h}$ in [network limits](zonal_math_formulation.md#network-constraints): $f_{l,h} \le \overline F^{FT}_{l,h}$. |
| `LineCap_TF.csv` | `<line_id>` | Maximum power in the reverse direction. | MW | float | $\overline F^{TF}_{l,h}$ in [network limits](zonal_math_formulation.md#network-constraints): $-f_{l,h} \le \overline F^{TF}_{l,h}$. |

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

| Column | Meaning | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `area_id` | Owner of each VRE site or thermal plant; other fields retain the [base input schemas](inputs.md). | Not applicable; identifier | string | Assigns plants to each area in [supply balance](zonal_math_formulation.md#per-area-supply-balance), [thermal floors](zonal_math_formulation.md#optional-thermal-minimum-dispatch), and [capacity margin](zonal_math_formulation.md#optional-local-capacity-margin). |

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

Tagged profiles retain the [base file units and equation references](inputs.md).
The [hydro formulation choices](inputs.md#large-hydropower) apply independently
to every area: existing daily/monthly names enforce energy equality, while
explicit `UpperBound` names allow unused period energy. Area budgets remain
unscaled; `AlphaLargHy` scales hourly bounds only.
`@area_id@` assigns each profile or storage technology to an area in
[per-area supply balance](zonal_math_formulation.md#per-area-supply-balance)
and [local capacity margin](zonal_math_formulation.md#optional-local-capacity-margin).
The clean-share target still uses the
[system-wide clean-share constraint](zonal_math_formulation.md#system-wide-clean-share-constraint).

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

The capacity-factor units and [PV/wind availability equations](sdom_math_formulation.md#vre-balance-constraints)
are unchanged; each area's factors also enter
[local capacity margin](zonal_math_formulation.md#optional-local-capacity-margin).

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
