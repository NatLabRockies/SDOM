# SDOM Input Data

This page describes all input data requirements for running SDOM optimizations.

## Input Data Structure

All input CSV files should be placed in a directory (e.g., `Data/scenario_name/`). File matching is case-insensitive and ignores spaces, hyphens, and underscores. Use the documented canonical filename stems so SDOM can identify each input file.

The following sections list each file and describe the data required in every field.

Each **Main use (math)** column links to the equation or constraint that mainly
uses that input. Identifiers select model sets or profile columns; descriptions
and geographic coordinates are metadata, not numerical equation coefficients.
All hourly power profiles are in MW. Summing them over SDOM's one-hour steps
gives MWh. Preserve the CSV cost units below: the model converts USD/kW and
USD/kWh inputs to the USD/MW and USD/MWh coefficients used in the math reference.

> **⚠️ Attention:**  
>  - Make sure all required CSV files are present in the specified folder before starting the simulation.
>  - Preserve the documented filename stem. For example, `CapSolar_2025.csv` must retain the `CapSolar` stem, though case and separators can vary.
>  - Do not change required CSV column names.

## Zonal Mode Inputs

SDOM supports two network formulations:

- `CopperPlateNetwork`: legacy single-area system-wide balance.
- `AreaTransportationModelNetwork`: multi-area zonal balance with inter-area transport limits.

For full zonal CSV schema, validation rules, and examples, see [Zonal Inputs](zonal_inputs.md).


## Required Files

### 1. Formulations Configuration

**File**: `formulations.csv`

This file the user selects the modeling approach (formulation) for each major system component in the SDOM optimization model. Each row assigns a formulation to a component, determining how SDOM will represent its behavior and constraints during optimization.

**CSV file columns:**
| Field/Column | Description | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `Component` | Component whose formulation is selected. | Not applicable; selector | string | Selects the relevant [constraint family](sdom_math_formulation.md#constraints), not a numerical coefficient. |
| `Formulation` | Exact formulation name; see supported choices below. | Not applicable; selector | string | Enables the corresponding [constraints](sdom_math_formulation.md#constraints). |
| `Description` | Optional explanatory text. | Not applicable; metadata | string | No optimization equation; descriptive metadata for the selected [constraint family](sdom_math_formulation.md#constraints). |

**Important Notes:**
- Only one formulation should be assigned per component.
- The chosen formulation directly affects how SDOM optimizes and simulates each component.
- Refer to the tables below for valid formulations for each component.

| Component | Formulation | Description | Units | Main use (math) |
| --- | --- | --- | --- | --- |
| hydro | RunOfRiverFormulation | Fixed hourly hydro profile | Not applicable; selector | [Fixed generation injections](sdom_math_formulation.md#fixed-generation-injections). |
| hydro | MonthlyBudgetFormulation | Fixed 730-hour energy equality | Not applicable; selector | [Hydro energy equality](sdom_math_formulation.md#energy-budget-equality). |
| hydro | DailyBudgetFormulation | 24-hour energy equality | Not applicable; selector | [Hydro energy equality](sdom_math_formulation.md#energy-budget-equality). |
| hydro | MonthlyBudgetUpperBoundFormulation | Fixed 730-hour energy upper bound | Not applicable; selector | [Hydro energy upper bound](sdom_math_formulation.md#energy-budget-upper-bound). |
| hydro | DailyBudgetUpperBoundFormulation | 24-hour energy upper bound | Not applicable; selector | [Hydro energy upper bound](sdom_math_formulation.md#energy-budget-upper-bound). |
| Thermal | NoRampsDispatchFormulation | Legacy continuous dispatch; default if absent | Not applicable; selector | [Thermal dispatch limit](sdom_math_formulation.md#dispatch-limit). |
| Thermal | NoRampsMinDispatchFormulation | Hourly fractions of total installed capacity | Not applicable; selector | [Hourly minimum dispatch](sdom_math_formulation.md#hourly-minimum-dispatch). |
| Imports | NotModel | No imports modeled | Not applicable; selector | [External trade constraints](sdom_math_formulation.md#import-and-export-constraints) are disabled for imports. |
| Imports | CapacityPriceNetLoadFormulation | Capacity/price/net-load constrained imports | Not applicable; selector | [Import capacity](sdom_math_formulation.md#capacity-limits) and [import gate](sdom_math_formulation.md#import-allowed-only-when-net-load-is-positive). |
| Exports | NotModel | No exports modeled | Not applicable; selector | [External trade constraints](sdom_math_formulation.md#import-and-export-constraints) are disabled for exports. |
| Exports | CapacityPriceNetLoadFormulation | Capacity/price/net-load constrained exports | Not applicable; selector | [Export capacity](sdom_math_formulation.md#capacity-limits) and [export gate](sdom_math_formulation.md#export-allowed-only-when-net-load-is-negative). |
| Network | CopperPlateNetwork | Single-area system-wide balance | Not applicable; selector | [Energy supply balance](sdom_math_formulation.md#energy-supply-balance). |
| Network | AreaTransportationModelNetwork | Multi-area transportation network | Not applicable; selector | [Per-area supply balance](zonal_math_formulation.md#per-area-supply-balance) and [network limits](zonal_math_formulation.md#network-constraints). |
| Reserves | notModel | Disabled default; no reserve components | Not applicable; selector | [Capacity-margin equations](sdom_math_formulation.md#optional-hourly-capacity-margin) are disabled. |
| Reserves | CapacityMarginFormulation | Deterministic hourly capacity margin | Not applicable; selector | [Hourly capacity margin](sdom_math_formulation.md#optional-hourly-capacity-margin). |

Choose the existing daily/monthly names when the entire period energy budget
must be dispatched. Choose the corresponding `UpperBound` name when availability
is a ceiling and unused budget energy is allowed. If you relied on the recently
relaxed inequality behavior of `DailyBudgetFormulation` or
`MonthlyBudgetFormulation`, select `DailyBudgetUpperBoundFormulation` or
`MonthlyBudgetUpperBoundFormulation`, respectively, to retain that behavior.
Equality budgets are not automatically relaxed when infeasible. Upper-bound
budgets alone do not prioritize hydro over wind or solar; optional
[curtailment rates](#optional-curtailment-cost-scalars) can change dispatch preferences.

`get_formulation` uses centrally registered defaults for missing Thermal,
Network, and Reserves rows. An explicit API `default=` takes precedence.
Hydro, Imports, and Exports remain required; no defaults are invented for
unregistered components. Thermal rejects duplicate, blank, null, and unsupported
selections. Other components retain their existing lookup/validation behavior.

**Example**:
```csv
Component,Formulation
hydro,MonthlyBudgetFormulation
Imports,CapacityPriceNetLoadFormulation
Exports,NotModel
Network,CopperPlateNetwork
```

### 2. Load Data

#### **File**: `Load_hourly.csv`

This file provides the system hourly electricity demand time-series.

**CSV file columns:**
| Field/Column | Description | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `*Hour` | One-based hourly index covering the modeled horizon. | Hour index; one-hour steps | int | Index $h$ in [energy supply balance](sdom_math_formulation.md#energy-supply-balance). |
| `Load` | Gross customer electricity demand in each hour. | MW | float | $d_h$ in [supply balance](sdom_math_formulation.md#energy-supply-balance), [clean share](sdom_math_formulation.md#carbon-free-generation-target), and [capacity margin](sdom_math_formulation.md#optional-hourly-capacity-margin). |



**Example**:
```csv
*Hour,Load
1,45230.5
2,43100.2
3,41500.8
...
```

### 3. VRE (Variable Renewable Energy) Data

#### Solar PV

##### **Capacity Factors**: `CFSolar.csv`
This file defines the hourly solar/wind capacity factors for each one of the potential sites defined in 2.1.1. This information can be obtained using, for instance [NLR SAM simulations](https://sam.nlr.gov/download.html) or [reV](https://www.nlr.gov/gis/rev).
- Columns: `*Hour`, `plant_1`, `plant_2`, ..., `plant_n`
- Values: Capacity factors (0-1) for each hour and plant

**CSV file columns:**
| Field/Column | Description | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `*Hour` | First column: one-based hourly index. The VRE builder reads the first column as the hour key. | Hour index; one-hour steps | int | Index $h$ in [PV balance](sdom_math_formulation.md#pv-balance) or [wind balance](sdom_math_formulation.md#wind-balance). |
| `<sc_gid>` | One capacity-factor column per candidate site in the corresponding capacity table. Values are fractions between 0 and 1. | Dimensionless fraction | float | $\sigma_{ph}$ in [PV balance](sdom_math_formulation.md#pv-balance), $\zeta_{wh}$ in [wind balance](sdom_math_formulation.md#wind-balance), and contemporaneous VRE output in [capacity margin](sdom_math_formulation.md#optional-hourly-capacity-margin). |

 **\*⚠️ Attention:**  
>  - Ensure that your input files contain a number of hours equal to or greater than the `n_hours` parameter specified when calling the `initialize_model()` function:

```
model = initialize_model(
    data,
    n_hours=n_steps,
    with_resilience_constraints=with_resilience_constraints
)
```

##### **Plant Data**: `CapSolar.csv`
This file lists all candidate sites for solar PV and wind energy deployment. For each site, it specifies installed-capacity bounds, geographic coordinates, capital expenditure (CAPEX), fixed operation and maintenance (FOM) costs, and transmission interconnection costs. These parameters are used by SDOM to evaluate investment options and optimize resource allocation across the available sites.
- Columns: `sc_gid` (plant ID), `capacity` (MW), optional `MinCapacity` (MW), `CAPEX_M` (USD/kW), `FOM_M` (USD/kW/year), `trans_cap_cost` (USD/MW)

**CSV file columns:**
| Field/Column | Description | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `sc_gid` | Site identifier matching a capacity-factor column. | Not applicable; identifier | string | Selects plant index $p$ or $w$ in the [resource sets](sdom_math_formulation.md#sets). |
| `capacity` | Upper bound on installed capacity at the site. | MW | float | $\bar p$ in [VRE installed-capacity bounds](sdom_math_formulation.md#vre-installed-capacity-bounds), [PV balance](sdom_math_formulation.md#pv-balance), and [wind balance](sdom_math_formulation.md#wind-balance). |
| `MinCapacity` | Optional installed-capacity lower bound; omitted, blank, or NaN defaults to zero. | MW | float | $\underline p$ in [VRE installed-capacity bounds](sdom_math_formulation.md#vre-installed-capacity-bounds). |
| `latitude` | Optional geographic coordinate for reporting or resource preparation. | Degrees | float | No optimization equation; geographic metadata for the [renewable resource](sdom_math_formulation.md#renewable-investment). |
| `longitude` | Optional geographic coordinate for reporting or resource preparation. | Degrees | float | No optimization equation; geographic metadata for the [renewable resource](sdom_math_formulation.md#renewable-investment). |
| `trans_cap_cost` | Site interconnection capital cost, already expressed per MW; not a line-flow capacity or transmission-investment variable. | USD/MW | float | $\kappa^{tc}$ in [PV cost](sdom_math_formulation.md#pv-cost) or [wind cost](sdom_math_formulation.md#wind-cost). |
| `CAPEX_M` | Site capital expenditure; multiplied by 1000 to obtain USD/MW. | USD/kW | float | $\kappa$ in [PV cost](sdom_math_formulation.md#pv-cost) or [wind cost](sdom_math_formulation.md#wind-cost). |
| `FOM_M` | Annual fixed O&M; multiplied by 1000 to obtain USD/MW/year. | USD/kW/year | float | $\phi$ in [PV cost](sdom_math_formulation.md#pv-cost) or [wind cost](sdom_math_formulation.md#wind-cost). |

`capacity` (lowercase) is the installed-capacity upper bound. `MinCapacity` is optional and is the installed-capacity lower bound; both values are in MW. When `MinCapacity` is omitted, blank, or `NaN`, SDOM uses `0` MW. Otherwise, it must be finite and satisfy `0 <= MinCapacity <= capacity`. A `capacity` value of `0` is valid only when `MinCapacity` is omitted, blank, `NaN`, or `0`. These bounds apply in both copperplate and zonal runs. In the Infrasys System interface, `MinCapacity` maps to `min_active_power`.

#### Wind

##### **Capacity Factors**: `CFWind.csv`
(Same structure as solar)
##### **Plant Data**: `CapWind.csv`
(Same structure as solar)

**⚠️ Attention:**  
>  - Make sure that each "sc_gid" defined in "CapSolar.csv" and "CapWind.csv" has its correspondend capacity factor hourly profile in the "CFSolar.csv" or "CFWind.csv" files .

### 4. Fixed Generation Sources

#### Nuclear
This file provides the hourly generation time-series for nuclear power plants and other renewable plants respectively.
##### **File**: `Nucl_hourly.csv`
- Fixed nuclear generation profile (MW)

**CSV file columns:**
| Field/Column | Description | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `*Hour` | One-based hourly index. | Hour index; one-hour steps | int | Index $h$ in [energy supply balance](sdom_math_formulation.md#energy-supply-balance). |
| `Nuclear` | Fixed nuclear generation profile before `AlphaNuclear` scaling. | MW | float | $\nu_h$ in [fixed generation injections](sdom_math_formulation.md#fixed-generation-injections), [supply balance](sdom_math_formulation.md#energy-supply-balance), and [capacity margin](sdom_math_formulation.md#optional-hourly-capacity-margin). |

#### Large Hydropower
###### **File**: `lahy_hourly.csv`
This file provides the hourly generation time-series for hydropower plants. The way SDOM utilizes this data depends on the selected hydro formulation ([formulations configuration](#1-formulations-configuration)):

- **RunOfRiverFormulation:**  
    Hydropower generation is directly set to the values specified in the time-series. No optimization is performed; the model simply follows the provided hourly profile.

- **Equality budgets (`MonthlyBudgetFormulation` or `DailyBudgetFormulation`):**
    SDOM sums the reference profile over consecutive fixed periods: 24 hours for
    daily budgets and 730 hours for monthly budgets, not calendar months. The
    entire budget must be dispatched in each period; only its hourly allocation
    is optimized. Select these names for mandatory period-energy delivery.

- **Upper-bound budgets (`MonthlyBudgetUpperBoundFormulation` or `DailyBudgetUpperBoundFormulation`):**
    The same period sums cap energy dispatch rather than requiring it. Select
    these names when unused hydro availability is allowed, including when
    retaining the recently relaxed behavior of the existing names.

    All four budget choices use the unscaled profile: `AlphaLargHy` scales the
    hourly minimum and maximum bounds, not the budget. Before solving, equality
    budgets are checked against both summed scaled minimum and maximum dispatch;
    upper-bound budgets are checked against the summed scaled minimum only.
    Availability above maximum possible generation is valid only for upper-bound
    budgets. These preliminary checks do not guarantee system-wide feasibility.
    Requested horizons round up to complete budget periods. Unused energy does
    not carry into later periods; no reservoir balance or slack is introduced.
    These budgets usually are outputs from long- and medium-term hydropower planning tools often based on Stochastic dual dynamic programming (SDDP). Examples of open-source tools for this are [cobre](https://github.com/cobre-rs/cobre)and [SimSEE](https://www.simsee.org/)

In summary, this file either serves as a fixed generation profile or as the basis for energy budgets, depending on the chosen hydro formulation.
For budget formulations, reported [hydro curtailment](sdom_math_formulation.md#hydro-curtailment-reporting)
is unused period-budget energy, not an hourly reference-profile shortfall or
necessarily physical water spill.

**CSV file columns:**
| Field/Column | Description | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `*Hour` | One-based hourly index grouped into complete budget periods when a budget formulation is selected. | Hour index; one-hour steps | int | $\mathcal H_b$ in the [hydro budget constraints](sdom_math_formulation.md#hydro-budget-constraints). |
| `LargeHydro` | Run-of-river profile or hourly availability values whose one-hour sums form period energy budgets. | MW; period sums are MWh | float | $\rho_h$ in [fixed generation injections](sdom_math_formulation.md#fixed-generation-injections) or $\epsilon_b$ in the [hydro budget constraints](sdom_math_formulation.md#hydro-budget-constraints). |

**Budget Formulation Files** (if using Monthly/Daily budgets):
- These files determine the lower and upper bounds for hydropower dispatch when Budget Formulations are used.
- `lahy_max_hourly.csv`: Maximum hourly capacity (MW)
- `lahy_min_hourly.csv`: Minimum hourly generation (MW)

Both bound files use the same columns:

| Field/Column | Description | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `*Hour` | One-based hourly index covering the effective budget-adjusted horizon. | Hour index; one-hour steps | int | Index $h$ in [hydro hourly bounds](sdom_math_formulation.md#hourly-bounds). |
| `LargeHydro` | Minimum dispatch in `lahy_min_hourly.csv`, or maximum dispatch in `lahy_max_hourly.csv`, before `AlphaLargHy` scaling. | MW | float | $\underline g^{hyd}_h$ or $\overline g^{hyd}_h$ in [hydro hourly bounds](sdom_math_formulation.md#hourly-bounds). |

#### Other Renewables
**File**: `otre_hourly.csv`
- Other renewable sources (geothermal, biomass, etc.)

| Field/Column | Description | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `*Hour` | One-based hourly index. | Hour index; one-hour steps | int | Index $h$ in [energy supply balance](sdom_math_formulation.md#energy-supply-balance). |
| `OtherRenewables` | Fixed other-renewable generation profile before `AlphaOtheRe` scaling. | MW | float | $\omega_h$ in [fixed generation injections](sdom_math_formulation.md#fixed-generation-injections), [supply balance](sdom_math_formulation.md#energy-supply-balance), and [capacity margin](sdom_math_formulation.md#optional-hourly-capacity-margin). |

### 5. Storage Technology Data

#### **File**: `StorageData.csv`

This CSV input file provides key technical and economic parameters for diverse energy storage technologies (Some examples could be: Li-Ion (Lithium-Ion), CAES (Compressed Air Energy Storage), PHS (Pumped Hydro Storage), H2 (Hydrogen Storage), etc). Each column represents a technology, and each row specifies a parameter:

| Field | Description | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `P_Capex` | Power capital expenditure; converted to USD/MW for the objective. | USD/kW | float | $\kappa^P_j$ in [storage cost](sdom_math_formulation.md#storage-cost). |
| `E_Capex` | Energy capital expenditure; converted to USD/MWh for the objective. | USD/kWh | float | $\kappa^E_j$ in [storage cost](sdom_math_formulation.md#storage-cost). |
| `Eff` | Round-trip efficiency; charging and discharging each use its square root. | Dimensionless fraction | float | $\eta_j$ in [SOC balance](sdom_math_formulation.md#state-of-charge-balance) and [storage capacity-margin energy bound](sdom_math_formulation.md#optional-hourly-capacity-margin). |
| `Min_Duration` | Minimum energy-to-discharge-power duration. | hours | float | $\underline\delta_j$ in [duration limits](sdom_math_formulation.md#duration-limits). |
| `Max_Duration` | Maximum energy-to-discharge-power duration. | hours | float | $\overline\delta_j$ in [duration limits](sdom_math_formulation.md#duration-limits). |
| `Max_P` | Upper bound on installed charging and discharging power. | MW | float | $\bar p^{stor}_j$ in [power capacity bounds](sdom_math_formulation.md#power-capacity-bounds). |
| `MaxCycles` | Allowed equivalent cycles over the technology lifetime. | Equivalent cycle count | float | $\kappa^{cyc}_j$ in [cycle limits](sdom_math_formulation.md#cycle-limits); not prorated for a shortened run. |
| `Coupled` | `1` forces equal installed charging/discharging power; `0` permits separate ratings. | Dimensionless flag | int, `0` or `1` | Membership of $\mathcal J^c$ in [coupled power equality](sdom_math_formulation.md#coupled-power-equality). |
| `FOM` | Annual fixed O&M for installed power; converted to USD/MW/year. | USD/kW/year | float | $\phi^{stor}_j$ in [storage cost](sdom_math_formulation.md#storage-cost). |
| `VOM` | Variable O&M charged on discharged energy only. | USD/MWh | float | $\psi^{stor}_j$ in [storage cost](sdom_math_formulation.md#storage-cost). |
| `Lifetime` | Storage lifetime used to calculate its annualization factor. | years | float | [Capital recovery factor](sdom_math_formulation.md#derived-quantities) in [storage cost](sdom_math_formulation.md#storage-cost). |
| `CostRatio` | Fraction of power CAPEX and FOM assigned to charging; `0.5` splits costs equally. | Dimensionless fraction | float | $\alpha_j$ in [storage cost](sdom_math_formulation.md#storage-cost). |

**Key considerations:**
- If you dont have energy CAPEX for the technology, and you only have power CAPEX for a particular duration, enforce ```Min_Duration==Max_Duration```.
- If the power capex is equally divided for the input power capacity and output power capacity, set CostRatio = 0.5.
- if the storage technology does not have an specification for MaxCycles, use a large value.

**Cost Data Sources**
Some sources to get cost data for storage technologies are:
 - [NLR Annual Technology Baseline (ATB)](https://atb.nrel.gov/electricity/2024b/utility-scale_battery_storage)
 - [PNNL “Energy Storage Cost and Performance Database v2024”](https://www.pnnl.gov/projects/esgc-cost-performance/download-reports)


**Example**:
```csv
Parameter,Li-Ion,CAES,PHS,H2
P_Capex,300,100,1500,800
E_Capex,150,2,10,5
Eff,0.85,0.70,0.80,0.40
...
```

### 6. Thermal Generation Data

#### **File**: `Data_BalancingUnits.csv`

This file contains essential data for thermal generation plants or aggregated units that participate in system balancing. Each row represents a plant or group of plants, specifying their technical and economic parameters required for SDOM optimization.

**Key considerations:**
- Each `Plant_id` must be unique and consistently referenced across other input files.
- Capacity values (`MinCapacity`, `MaxCapacity`) set the bounds for possible investments (installed capacity).
- To represent already existent generation fleet it is recomended add a new row where `MinCapacity` = `MaxCapacity` and CAPEX = 0


**CSV file columns:**
| Field/Column | Description | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `Plant_id` | Unique exact plant identifier, also used by thermal-profile headers. | Not applicable; identifier | string | Selects index $k$ in the [balancing-unit set](sdom_math_formulation.md#sets) and [hourly minimum dispatch](sdom_math_formulation.md#hourly-minimum-dispatch). |
| `MinCapacity` | Minimum installed plant capacity, not an hourly dispatch floor. | MW | float | $\underline p^{bal}_k$ in [thermal capacity bounds](sdom_math_formulation.md#capacity-bounds). |
| `MaxCapacity` | Maximum installed plant capacity. | MW | float | $\bar p^{bal}_k$ in [thermal capacity bounds](sdom_math_formulation.md#capacity-bounds). |
| `Lifetime` | Plant lifetime used for its annualization factor. | years | float | [Capital recovery factor](sdom_math_formulation.md#derived-quantities) in [balancing-unit cost](sdom_math_formulation.md#balancing-unit-cost). |
| `Capex` | Plant capital expenditure; converted to USD/MW. | USD/kW | float | $\kappa^{bal}_k$ in [balancing-unit cost](sdom_math_formulation.md#balancing-unit-cost). |
| `HeatRate` | Fuel energy input per unit of electricity output; multiplied by fuel price. | MMBtu/MWh | float | $\gamma_k = HeatRate_k\,FuelCost_k$ in [balancing-unit cost](sdom_math_formulation.md#balancing-unit-cost). |
| `FuelCost` | Fuel price multiplied by the plant heat rate. | USD/MMBtu | float | $\gamma_k$ in [balancing-unit cost](sdom_math_formulation.md#balancing-unit-cost). |
| `VOM` | Variable O&M on generated energy. | USD/MWh | float | $\psi^{bal}_k$ in [balancing-unit cost](sdom_math_formulation.md#balancing-unit-cost). |
| `FOM` | Annual fixed O&M on installed capacity; converted to USD/MW/year. | USD/kW/year | float | $\phi^{bal}_k$ in [balancing-unit cost](sdom_math_formulation.md#balancing-unit-cost). |

#### Optional hourly thermal minimum dispatch

Select `Thermal,NoRampsMinDispatchFormulation` in `formulations.csv` and supply
`Thermal_MinDispatchFraction.csv`:

**CSV file columns:**

| Field/Column | Description | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `Hour` | Unique positive one-based hourly index covering the effective model horizon. | Hour index; one-hour steps | int | Index $h$ in the [hourly minimum-dispatch constraint](sdom_math_formulation.md#hourly-minimum-dispatch). |
| `<Plant_id>` | One column per exact thermal `Plant_id`; each value is the minimum dispatch fraction for that plant and hour, including candidate plants. | Dimensionless fraction, `[0,1]` | float | $q^{bal}_{kh}$ in [minimum dispatch](sdom_math_formulation.md#hourly-minimum-dispatch): $G^{bal}_{kh} \ge q^{bal}_{kh}P^{bal}_k$. |

`<Plant_id>` denotes a plant-specific header such as `GasCC_existing`, not a
literal column name. A value of `0.40` means at least 40% of installed MW;
do not enter `40` or a MW output value.

```csv
Hour,GasCC_existing,GasCC_candidate
1,0.40,0.00
2,0.30,0.20
3,0.50,0.20
4,0.60,0.10
```

The first column must be `Hour`; subsequent columns must match **every**
`Plant_id` in `Data_BalancingUnits.csv`, including candidates and zero-capacity
rows. IDs are exact strings (including leading zeros and literal `NA` or `NULL`);
blank or duplicate IDs and duplicate CSV headers are errors. Column order may differ from the
static table. No constant-fraction column is added to that table.

Hours must uniquely cover `1..N` for positive `N`; unordered rows are sorted.
Model construction requires coverage of the **effective** horizon, including
hydro-budget rounding. Extra rows are validated too. No padding, repetition,
interpolation, or resampling occurs. An empty thermal fleet requires an
hour-only file, not an omitted file.

Fractions are finite numeric values in `[0,1]`, not percentages or MW.
Numeric text is accepted; booleans, blanks, nulls, nonfinite values, and
out-of-range values fail with source/cell context. Fraction precision is
preserved without five-decimal rounding. Enabled capacity bounds must be finite
and satisfy `0 <= MinCapacity <= MaxCapacity`.

The floor applies to **total optimized installed capacity**, including
expansion, not to either input capacity bound. Zero fractions add no floor
rows; a fraction of one forces full output. A candidate may remain unbuilt.
This is a linear must-run obligation, not unit commitment or availability:
there are no new binaries, ramping constraints, startup costs, or capacity
credits. Capacity margins still credit full installed thermal MW once.
Surplus can be infeasible: VRE curtailment cannot dump thermal output, and
storage, exports (including existing net-load gates), transmission, and the
clean-share equation remain unchanged.

Thermal component matching is case-insensitive, but formulation values require
exact spelling. Missing Thermal rows default through `get_formulation` to
`NoRampsDispatchFormulation`; blank, null, unknown, and duplicate Thermal rows
are errors. Under legacy selection, a stale profile is ignored without being
read or validated, with an INFO message. Direct data dictionaries use the same
validation and optional `thermal_min_dispatch_fraction` key.

See [must-run equations and capacity-factor qualifications](sdom_math_formulation.md#hourly-minimum-dispatch).
Existing scalar, storage, and supported time-series parametric mutations retain
the selection/profile. A dedicated thermal-profile sweep is **not** supported;
prepare independent profile copies or edit System-owned series before building.
Result columns and zero/one/many-plant thermal reporting remain unchanged.

### 7. System Scalars

#### **File**: `scalars.csv`

This CSV file contains key parameters and their corresponding values for an energy system model. Each row specifies a parameter name and its value, which are used to configure various aspects of the model, such as technology lifetimes, financial rates, and generation mix targets.

| Parameter | Description | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- |
| `LifeTimeVRE` | Shared operational lifetime of PV and wind used to calculate their annualization factor. | years | float | [Capital recovery factor](sdom_math_formulation.md#derived-quantities), [PV cost](sdom_math_formulation.md#pv-cost), and [wind cost](sdom_math_formulation.md#wind-cost). |
| `GenMix_Target` | Minimum clean-energy share, entered as a fraction between 0 and 1. | Dimensionless fraction | float | $\tau$ in the [carbon-free generation target](sdom_math_formulation.md#carbon-free-generation-target). |
| `AlphaNuclear` | Multiplier for the fixed nuclear profile; typically 0 disables and 1 preserves the input profile. | Dimensionless multiplier | float | $\alpha^{nuc}\nu_h$ in [energy supply balance](sdom_math_formulation.md#energy-supply-balance) and [capacity margin](sdom_math_formulation.md#optional-hourly-capacity-margin). |
| `AlphaLargHy` | Multiplier for run-of-river generation or hourly hydro dispatch bounds; does not scale the energy budget. | Dimensionless multiplier | float | [Fixed generation injections](sdom_math_formulation.md#fixed-generation-injections) and [hydro hourly bounds](sdom_math_formulation.md#hourly-bounds). |
| `AlphaOtheRe` | Multiplier for the fixed other-renewables profile; typically 0 disables and 1 preserves the input profile. | Dimensionless multiplier | float | $\alpha^{oth}\omega_h$ in [energy supply balance](sdom_math_formulation.md#energy-supply-balance) and [capacity margin](sdom_math_formulation.md#optional-hourly-capacity-margin). |
| `r` | Discount rate for annualized capital costs; `0.06` means 6%. | Dimensionless annual rate | float | [Capital recovery factor](sdom_math_formulation.md#derived-quantities), used in the [cost objective](sdom_math_formulation.md#objective-function). |
| `EUE_max` | Aggregate load-shedding energy limit in the legacy planning resiliency constraints, enabled by `with_resilience_constraints=True`; not an outage-evaluator probability input. | MWh | float | $EUE^{max}$ in the [legacy aggregate planning resiliency limit](sdom_math_formulation.md#legacy-aggregate-planning-resiliency). |
| `capacity_marging_fraction` | Optional nonnegative capacity-margin fraction; default `0.0`. `0.04` requires generation capacity of at least 104% of gross hourly demand. Consumed only by `CapacityMarginFormulation`; applies separately in each zone. | Dimensionless fraction | float | $m$ in the [hourly capacity-margin requirement](sdom_math_formulation.md#optional-hourly-capacity-margin). |
| `SolarCurtailmentCost` | Optional solar PV curtailment rate; default `0.0` when absent. | USD/MWh | finite float | $c^{solar}$ in [curtailment costs](sdom_math_formulation.md#curtailment-costs). |
| `WindCurtailmentCost` | Optional wind curtailment rate; default `0.0` when absent. | USD/MWh | finite float | $c^{wind}$ in [curtailment costs](sdom_math_formulation.md#curtailment-costs). |
| `HydroCurtailmentCost` | Optional unused upper-bound hydro budget rate; default `0.0` when absent. | USD/MWh | finite float | $c^{hydro}$ in [curtailment costs](sdom_math_formulation.md#curtailment-costs). |

**Note:** Adjust parameter values as needed to reflect the specific scenario or assumptions for your energy system analysis.

**Example**:
```csv
Parameter,Value
r,0.07
GenMix_Target,0.95
AlphaNuclear,1.0
AlphaLargHy,1.0
AlphaOtheRe,1.0
capacity_marging_fraction,0.04
```

#### Optional curtailment-cost scalars

Append any subset of these rows below the existing `Parameter,Value` header
in `scalars.csv`, retaining all other rows (do not repeat the header):

```csv
SolarCurtailmentCost,5
WindCurtailmentCost,10
HydroCurtailmentCost,20
```

Each rate activates independently when nonzero; missing or exactly zero omits
that technology's objective term. No formulation toggle is required. Supplied
values must be numeric and finite: blank, nonnumeric, NaN, infinite, and duplicate
entries raise an error naming the offending parameter during model construction.
Finite negative rates are supported: they **reward curtailment** and may
materially change investment and dispatch.

Rates are global and shared by every zonal area, not area-specific inputs.
Solar and wind rates multiply existing curtailed energy in MWh. Hydro rates
apply only to `DailyBudgetUpperBoundFormulation` and
`MonthlyBudgetUpperBoundFormulation`, using unused **unscaled period-budget**
energy, not hourly profile shortfalls or water spill. Run-of-river and both
equality-budget choices have zero hydro cost. Zero dispatch capability does
not erase a positive available budget. Costs cover the effective modeled
horizon, rounded to complete 24-hour or fixed 730-hour hydro periods;
there is no extra annualization or kW conversion. See the
[objective equations](sdom_math_formulation.md#curtailment-costs) and
[individual output cost rows](running_and_outputs.md#curtailment-cost-totals).

#### Optional capacity-margin scalar

To opt in, add this row to `formulations.csv`:

```csv
Component,Formulation,Description
Reserves,CapacityMarginFormulation,Hourly capacity margin
```

Add the optional row to the existing `scalars.csv` (retain its other rows):

```csv
Parameter,Value
capacity_marging_fraction,0.04
```

Preserve the exact spelling **`capacity_marging_fraction`**. This dimensionless
fraction means capability must be at least 104% of **gross** demand in
every modeled hour. Zonal capability includes scheduled inter-area imports
minus exports; it does not include additional reserve transfers.
If absent, its default is `0.0`. When enabled, supplied
blank, nonnumeric, NaN, infinite, or negative values raise an error naming the
scalar during model construction. There is no upper cap or implicit percent
conversion: `15` means 1500%, not 15%.

Only the exact formulation value `CapacityMarginFormulation` enables the
equations (component names retain their existing case-insensitive lookup).
A missing `Reserves` row, explicit `notModel` (also internal `NotModel`), or any
nonmatching value leaves reserves disabled; the scalar alone never enables
them and is not consumed or validated by the disabled formulation. Enabled
zero margin still installs the constraints.

This global scalar applies separately to every area in zonal mode. No new
files, capacity-credit inputs, provider tables, or per-area margin settings
are required. `adequacy_duration_hours = 1` is fixed in the formulation module;
it is not a scalar or configurable API option. Existing scalar sweeps and
CSV-to-System-to-model adapters retain the scalar and selection.
See the [mathematical contract](sdom_math_formulation.md#optional-hourly-capacity-margin)
for resource accounting and beginning-SOC assumptions. Storage contributes
nonnegative deliverable capacity bounded by installed discharge MW and
beginning SOC, independent of baseline charge/discharge. No extra scalar,
upward-award input, or configurable duration is needed.

### 8. Import/Export Data (Optional)

**If using CapacityPriceNetLoadFormulation**:
These files are only required when Imports and Exports formulations are set different to "NotModel" in "formulations.csv" ([see section about formulations.csv](#1-formulations-Configuration)).

- `Import_Cap.csv`: Hourly import capacity limits (MW)
- `Import_Prices.csv`: Hourly import prices ($/MWh)
- `Export_Cap.csv`: Hourly export capacity limits (MW)
- `Export_Prices.csv`: Hourly export prices ($/MWh)

Each file has `*Hour` and the indicated value column. These are external
system imports/exports, not the inter-area flows of zonal mode.

| File | Field/Column | Description | Units | Expected type | Main use (math) |
| --- | --- | --- | --- | --- | --- |
| All four trade files | `*Hour` | One-based hourly index. | Hour index; one-hour steps | int | Index $h$ in [trade constraints](sdom_math_formulation.md#import-and-export-constraints) and [trade cost](sdom_math_formulation.md#trade-cost). |
| `Import_Cap.csv` | `Imports` | Hourly maximum external import power. | MW | float | $\bar\iota_h$ in [capacity limits](sdom_math_formulation.md#capacity-limits) and the [import net-load gate](sdom_math_formulation.md#import-allowed-only-when-net-load-is-positive). |
| `Import_Prices.csv` | `Imports_price` | Price paid per imported MWh. | USD/MWh | float | $c^{imp}_h$ in [trade cost](sdom_math_formulation.md#trade-cost). |
| `Export_Cap.csv` | `Exports` | Hourly maximum external export power. | MW | float | $\bar\xi_h$ in [capacity limits](sdom_math_formulation.md#capacity-limits) and the [export net-load gate](sdom_math_formulation.md#export-allowed-only-when-net-load-is-negative). |
| `Export_Prices.csv` | `Exports_price` | Revenue per exported MWh. | USD/MWh | float | $c^{exp}_h$ in [trade cost](sdom_math_formulation.md#trade-cost). |

## Data Validation

SDOM performs several validation checks during data loading:

1. **File Existence**: All required files must be present
2. **Plant Consistency**: Solar/wind plant IDs must match between CF and CAPEX files
3. **Completeness**: Filters out plants with missing data (NaN values)
4. **Formulation Validity**: Checks that specified formulations are valid
5. **Hour Count**: For budget formulations, adjusts hours to be multiple of budget interval

## Example Data Loading

```python
from sdom import load_data

# Load data from directory
data = load_data('./Data/my_scenario/')

# Access loaded data
print(f"Number of solar plants: {len(data['solar_plants'])}")
print(f"Number of wind plants: {len(data['wind_plants'])}")
print(f"Storage technologies: {data['STORAGE_SET_J_TECHS']}")
print(f"Discount rate: {data['scalars'].loc['r', 'Value']}")
```

## Tips for Data Preparation

1. **Consistent Plant IDs**: Use string IDs for VRE plants (e.g., "101", "202")
2. **Hour Indexing**: Use 1-based indexing (1-8760) for consistency
3. **Units**: Stick to MW for power, MWh for energy, $ for costs
4. **File Naming**: Use flexible naming (case doesn't matter, underscores/hyphens optional)
5. **Missing Data**: Remove rows/plants with incomplete data before running

## Next Steps

- [Run SDOM optimization](running_and_outputs.md)
- [Explore model structure](exploring_model.md)
