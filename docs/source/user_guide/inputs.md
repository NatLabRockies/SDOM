# SDOM Input Data

This page describes all input data requirements for running SDOM optimizations.

## Input Data Structure

All input CSV files should be placed in a directory (e.g., `Data/scenario_name/`). The file names are defined in `constants.py` and are flexible (case-insensitive matching with spaces/hyphens/underscores ignored).

In the next sections each file will be listed and the data it is supossed to be in each field will be described

> **⚠️ Attention:**  
>  - Make sure all required CSV files are present in the specified folder before starting the simulation.
>  - Please keep the root names of each file. For instance, in the sample files you can change "2025" for whatever you prefer, but keeping the root name. For example, for "CapSolar_2025.csv" file you need to keep the root name as "CapSolar_".
>  - Please do not change the column names of each csv files.

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
| Field/Column           | Description                                                                    |Expected type |
|------------------------|--------------------------------------------------------------------------------|--------------|
| Component              | String with the component name you are going to set the formulation (Model).   |string        |
| Formulation            | Name of the formulation (model) you want to use. See more below.               |String        |
| Description (Optional) | Just a description/guidelines that developers let for users.                   |String        |

**Important Notes:**
- Only one formulation should be assigned per component.
- The chosen formulation directly affects how SDOM optimizes and simulates each component.
- Refer to the tables below for valid formulations for each component.

| Component | Formulation | Description |
|-----------|-------------|-------------|
| hydro | RunOfRiverFormulation | Fixed hourly hydro profile |
| hydro | MonthlyBudgetFormulation | Monthly energy budget constraint |
| hydro | DailyBudgetFormulation | Daily energy budget constraint |
| Imports | NotModel | No imports modeled |
| Imports | CapacityPriceNetLoadFormulation | Price-based import optimization |
| Exports | NotModel | No exports modeled |
| Exports | CapacityPriceNetLoadFormulation | Price-based export optimization |
| Network | CopperPlateNetwork | Single-area legacy network model |
| Network | AreaTransportationModelNetwork | Multi-area transportation network |

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
| Field/Column    | Description                                                                                         |Expected type |
|-----------------|-----------------------------------------------------------------------------------------------------|--------------|
| *Hour           | Number of the hour of the year, from 1 to 8760 (You can teh number of hours you prefer).            |Int           |
| Load            | The estimated system electricity demand at each hour of the year in MWh.                            |float         |



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
This file defines the hourly solar/wind capacity factors for each one of the potential sites defined in 2.1.1. This information can be obtained using, for instance [NLR SAM simulations](https://sam.nrel.gov/download.html) or [reV](https://www.nrel.gov/gis/renewable-energy-potential).
- Columns: `*Hour`, `plant_1`, `plant_2`, ..., `plant_n`
- Values: Capacity factors (0-1) for each hour and plant

**CSV file columns:**
| Field/Column    | Description                                                                                         |Expected type |
|-----------------|-----------------------------------------------------------------------------------------------------|--------------|
| Hour            | Number of the hour of the year, from 1 to 8760 (You can choose the number of hours you prefer)*.            |Int           |
| Col for each id | The estimated capacity factor at each hour of the year for each site in MWh/installed MW.          |float         |

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
This file lists all candidate sites for solar PV and wind energy deployment. For each site, it specifies the maximum allowed installed capacity, geographic coordinates, capital expenditure (CAPEX), fixed operation and maintenance (FOM) costs, and transmission interconnection costs. These parameters are used by SDOM to evaluate investment options and optimize resource allocation across the available sites
- Columns: `sc_gid` (plant ID), `capacity` (MW), `CAPEX_M` ($/kW), `FOM_M` ($/kW-yr), `trans_cap_cost` ($)

**CSV file columns:**
| Field/Column    | Description                                                                                         |Expected type |
|-----------------|-----------------------------------------------------------------------------------------------------|--------------|
| sc_gid          | Unique identifier for each PV/Wind site or resource that will be represented by a single profile.   |string        |
| capacity        | Upper bound for the allowed installed capacity at the site (MW).                                    |float         |
| latitude        | Latitude coordinate of the site (optional for future fetching of VRE files).                        |float         |
| longitude       | Longitude coordinate of the site (optional for future fetching of VRE profiles).                    |float         |
| trans_cap_cost  | Transmission Capital expediture costs associated with transmission in USD/kW                        |float         |
| CAPEX_M         | Capital expenditure in USD/kW.                                                                      |float         |
| FOM_M           | Fixed operation and maintenance cost in USD/kW.                                                     |float         |

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
| Field/Column    | Description                                                                                         |Expected type |
|-----------------|-----------------------------------------------------------------------------------------------------|--------------|
| *Hour           | Number of the hour of the year, from 1 to 8760 (You can teh number of hours you prefer).            |Int           |
| Nuclear/OtherRenewables| The estimated generation at each hour of the year in MWh from Nuclear of Other Renewables (Such as Biomass, for instance).|float    |

#### Large Hydropower
###### **File**: `lahy_hourly.csv`
This file provides the hourly generation time-series for hydropower plants. The way SDOM utilizes this data depends on the selected hydro formulation ([see section 2.1 formulations.csv](#21-formulationscsv)):

- **RunOfRiverFormulation:**  
    Hydropower generation is directly set to the values specified in the time-series. No optimization is performed; the model simply follows the provided hourly profile.

- **Budget Formulations (MonthlyBudgetFormulation or DailyBudgetFormulation):**  
    SDOM aggregates the time-series data into energy budgets over consecutive periods—24 hours for daily budgets and 730 hours for monthly budgets. These budgets define the total energy available for dispatch within each period, allowing SDOM to optimize the allocation of hydropower generation while respecting the specified limits.
    These budgets usually are outputs from long- and medium-term hydropower planning tools often based on Stochastic dual dynamic programming (SDDP). An example of open-source tool for this is [SimSEE](https://www.simsee.org/)

In summary, this file either serves as a fixed generation profile or as the basis for energy budgets, depending on the chosen hydro formulation.

**CSV file columns:**
| Field/Column    | Description                                                                                         |Expected type |
|-----------------|-----------------------------------------------------------------------------------------------------|--------------|
| *Hour           | Number of the hour of the year, from 1 to 8760 (You can teh number of hours you prefer).            |Int           |
| LargeHydro      | The estimated hydropower generation at each hour of the year in MWh or average values to make the budget.|float         |

**Budget Formulation Files** (if using Monthly/Daily budgets):
- These files determine the lower and upper bounds for hydropower dispatch when Budget Formulations are used.
- `lahy_max_hourly.csv`: Maximum hourly capacity (MW)
- `lahy_min_hourly.csv`: Minimum hourly generation (MW)

#### Other Renewables
**File**: `otre_hourly.csv`
- Other renewable sources (geothermal, biomass, etc.)

### 5. Storage Technology Data

#### **File**: `StorageData.csv`

This CSV input file provides key technical and economic parameters for diverse energy storage technologies (Some examples could be: Li-Ion (Lithium-Ion), CAES (Compressed Air Energy Storage), PHS (Pumped Hydro Storage), H2 (Hydrogen Storage), etc). Each column represents a technology, and each row specifies a parameter:

| Field        | Description                                                                                                    | Expected type   |
|--------------|----------------------------------------------------------------------------------------------------------------|-----------------|
| P_Capex      | Power-related capital expenditure (USD/kW)                                                                     | float           |
| E_Capex      | Energy-related capital expenditure (USD/kWh)                                                                   | float           |
| Eff          | Round-trip efficiency (fraction)                                                                               | float           |
| Min_Duration | Minimum storage duration (hours)                                                                               | float/int       |
| Max_Duration | Maximum storage duration (hours)                                                                               | float/int       |
| Max_P        | Maximum power capacity (kW)                                                                                    | float/int       |
| MaxCycles    | Maximum number of charge/discharge cycles                                                                      | int             |
| Coupled      | Indicates if input and output power are coupled (1 = coupled - enforces input Power = output Power)            | int (0 or 1)    |
| FOM          | Fixed operation and maintenance cost (USD/kW/year)                                                             | float           |
| VOM          | Variable operation and maintenance cost (USD/MWh)                                                              | float           |
| Lifetime     | Expected system lifetime (years)                                                                               | int             |
| CostRatio    | Ratio of cost allocation between input and output power. If Input Power Capex = Output Power Capex, then CostRatio = 0.5| float           |

**Key considerations:**
- If you dont have energy CAPEX for the technology, and you only have power CAPEX for a particular duration, enforce ```Min_Duration==Max_Duration```.
- If the power capex is equally divided for the input power capacity and output power capacity, set CostRatio = 0.5.
- if the storage technology does not have an specification for MaxCycles, use a large value.

**Cost Data Sources**
Some sources to get cost data for storage technologies are:
 - [NLR Annual Technology Baseline (ATB)](https://atb.nrel.gov/electricity/2024/utility-scale_battery_storage)
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
| Field/Column | Description | Expected type |
|--------------|-------------|---------------|
| Plant_id     | Unique identifier for each thermal generation plant or aggregation of plants. | string |
| MinCapacity  | Minimum allowed installed capacity at the plant (MW). | float |
| MaxCapacity  | Maximum allowed installed capacity at the plant (MW). | float |
| Lifetime     | Expected operational lifetime of the plant (years). | int |
| Capex        | Capital expenditure in USD/kW. | float |
| HeatRate     | Heat rate of the plant (fuel energy input per unit electricity output, typically in MMBtu/MWh). | float |
| FuelCost     | Fuel cost in USD/MMBtu. | float |
| VOM          | Variable operation and maintenance cost in USD/MWh. | float |
| FOM          | Fixed operation and maintenance cost in USD/kW. | float |

### 7. System Scalars

#### **File**: `scalars.csv`

This CSV file contains key parameters and their corresponding values for an energy system model. Each row specifies a parameter name and its value, which are used to configure various aspects of the model, such as technology lifetimes, financial rates, and generation mix targets.

| Parameter        | Description                                                                             | Expected Type|
|------------------|-----------------------------------------------------------------------------------------|--------------|
| LifeTimeVRE      | Operational lifetime in years of Variable Renewable Energy sources (To calculate CRF)   | int          |
| GenMix_Target    | Target value for generation mix (e.g., share of renewables). Between 0 and 1.           | float        |
| AlphaNuclear     | Activation/Deactivation (1/0) for nuclear energy                                        | int (0 or 1) |
| AlphaLargHy      | Activation/Deactivation (1/0) for large hydro energy                                    | int (0 or 1) |
| AlphaOtheRe      | Activation/Deactivation (1/0) for other renewable energy sources                        | int (0 or 1) |
| r                | Discount rate or interest rate used in financial calculations (Example: r=0.06)         | float        |
| EUE_max          | Maximum allowed Expected Unserved Energy (EUE) - used when resiliency constraints = true| float        |

**Note:** Adjust parameter values as needed to reflect the specific scenario or assumptions for your energy system analysis.

**Example**:
```csv
Parameter,Value
r,0.07
GenMix_Target,0.95
alpha_Nuclear,1.0
alpha_Hydro,1.0
alpha_OtherRenewables,1.0
```

### 8. Import/Export Data (Optional)

**If using CapacityPriceNetLoadFormulation**:
These files are only required when Imports and Exports formulations are set different to "NotModel" in "formulations.csv" ([see section about formulations.csv](#1-formulations-Configuration)).

- `Import_Cap.csv`: Hourly import capacity limits (MW)
- `Import_Prices.csv`: Hourly import prices ($/MWh)
- `Export_Cap.csv`: Hourly export capacity limits (MW)
- `Export_Prices.csv`: Hourly export prices ($/MWh)

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
