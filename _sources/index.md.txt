# SDOM Documentation

Welcome to the **Storage Deployment Optimization Model (SDOM)** documentation!

SDOM is an open-source, high-resolution grid capacity-expansion framework developed by the National Lab of the Rockies (NLR). It's purpose-built to optimize the deployment and operation of energy storage technologies, leveraging hourly temporal resolution and granular spatial representation of Variable Renewable Energy (VRE) sources such as solar and wind.


## Key Features

- ⚡ **Accurate Storage Representation**: Short, long, and seasonal storage technologies
- 📆 **Hourly Resolution**: Full 8760-hour annual simulation
- 🌍 **Spatial Granularity**: Fine-grained VRE resource representation
- 🔌 **Copper Plate Modeling**: Computationally efficient system optimization
- 💰 **Cost Minimization**: Optimizes total system cost (CAPEX + OPEX)
- 🐍 **Open Source**: Fully Python-based using Pyomo

## Installation

### System Setup and Prerequisites 

- a. You'll need to install [python](https://www.python.org/downloads/)
  - SDOM supports Python `>=3.11,<3.14`.
  - After the installation make sure the [python enviroment variable is set](https://realpython.com/add-python-to-path/).
- b. Also, You'll need an IDE (Integrated Development Environment), we recommend to install [MS VS code](https://code.visualstudio.com/)
- c. We also recommend to install extensions such as:
  - [Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python) (required): Provides Python language support, debugging, environment selection, and IntelliSense in VS Code.
  - [edit CSV](https://marketplace.visualstudio.com/items?itemName=janisdd.vscode-edit-csv): To edit and interact with input csv files for SDOM directly in vs code.
  - [vscode-pdf](https://marketplace.visualstudio.com/items?itemName=tomoki1207.pdf): to read and see pdf files directly in vscode.

### Installing SDOM python package
```bash
# Install uv if you haven't already
pip install uv

# Create virtual environment
uv venv .venv

# Activate (Windows PowerShell)
.venv\Scripts\Activate.ps1

# Activate (Unix/MacOS)
source .venv/bin/activate

# Install SDOM
uv pip install sdom

# Or install from source
uv pip install -e .
```

**Windows only — verify that `python` and `uv` are on your PATH:**

```powershell
# Run in PowerShell (or cmd). Each command should print a full path.
where.exe python
where.exe uv
```

If either command prints `INFO: Could not find files for the given pattern(s).`, the executable is not on your PATH. Re-check the Python installer option *Add python.exe to PATH*, or reinstall `uv` and open a new terminal so PATH changes take effect.

**Fix it manually (no admin required) — add the missing folders to your User PATH:**

1. Locate the install folder(s). Common defaults are:
   - Python: `%LOCALAPPDATA%\Programs\Python\Python3xx\` and `%LOCALAPPDATA%\Programs\Python\Python3xx\Scripts\`
   - `uv`: `%USERPROFILE%\.local\bin\` (official installer) or the `Scripts` folder of the Python you used with `pip install uv`

   You can list installed Python versions with:

   ```powershell
   Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Directory
   ```

2. Append the folder(s) to your **User** PATH (persists across sessions, no admin needed). Edit the `$newPaths` list to match what you found in step 1, then run:

   ```powershell
   $newPaths = @(
       "$env:LOCALAPPDATA\Programs\Python\Python312",
       "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts",
       "$env:USERPROFILE\.local\bin"
   )
   $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
   $updated  = (@($userPath.TrimEnd(';')) + $newPaths) -join ';'
   [Environment]::SetEnvironmentVariable("Path", $updated, "User")
   ```

3. **Close and reopen your terminal** (and VS Code) so the new PATH is picked up, then re-run `where.exe python` and `where.exe uv` to confirm both now resolve.

## Quick Start

```{important}
For new work, use the [Infrasys System interface](user_guide/infrasys_integration.md). In SDOM v0.3.0 it becomes the only supported workflow; the dict-based `load_data` and `initialize_model` interface is deprecated. The current v0.2.xx release continues to support existing dict-based scripts.
```

### System-first quick start

Install the Infrasys integration with `sdom[infrasys]` before running this example.

```python
from sdom import get_default_solver_config_dict, run_solver
from sdom.infrasys_integration import add_results_to_system, plot_system_results
from sdom.infrasys_integration.make_system import load_system
from sdom.infrasys_integration.pyomo_builder import initialize_copperplate_model_from_system

system = load_system("Data/no_exchange_run_of_river", name="copperplate")
model = initialize_copperplate_model_from_system(system, n_hours=24).create_instance()
solver_config = get_default_solver_config_dict(solver_name="highs", executable_path="")
results = run_solver(model, solver_config, case_name="copperplate")

if results.is_optimal:
  add_results_to_system(system, results, run_id="copperplate-24h")
  plot_system_results(system, run_id="copperplate-24h", output_dir="results/copperplate")
```

The System-first copperplate and zonal examples are in the [Infrasys System workflows guide](user_guide/infrasys_integration.md). The legacy example below remains available for existing v0.2.XX scripts.

```python
from sdom import (
    load_data, 
    initialize_model, 
    run_solver, 
    get_default_solver_config_dict,
    export_results
)

# Load input data
data = load_data("./Data/your_scenario/")

# Initialize model (8760 hours = full year)
model = initialize_model(data, n_hours=8760)

# Configure solver
solver_config = get_default_solver_config_dict(
    solver_name="cbc", 
    executable_path="./Solver/bin/cbc.exe"
)

# Solve optimization problem - returns OptimizationResults object
results = run_solver(model, solver_config)

# Access results
if results.is_optimal:
    print(f"Total Cost: ${results.total_cost:,.2f}")
    print(f"Wind Capacity: {results.total_cap_wind:.2f} MW")
    print(f"Solar Capacity: {results.total_cap_pv:.2f} MW")
    
    # Export results to CSV files
    export_results(results, case="scenario_1", output_dir="./results/")
```

## Documentation Contents

```{toctree}
:maxdepth: 2
:caption: User Guide

user_guide/introduction
user_guide/inputs
user_guide/zonal_inputs
user_guide/running_and_outputs
user_guide/zonal_model
user_guide/parametric_analysis
user_guide/infrasys_integration
user_guide/resiliency
user_guide/resiliency_math
user_guide/exploring_model
user_guide/sdom_math_formulation
user_guide/zonal_math_formulation
```

```{toctree}
:maxdepth: 2
:caption: API Reference

api/index
api/core
api/results
api/models
api/io_manager
api/utilities
api/resiliency
api/infrasys_integration
```

```{toctree}
:maxdepth: 1
:caption: Development

sdom_Developers_guide
parametric_implementation
sdom_publications
GitHub Repository <https://github.com/NatLabRockies/SDOM>
```

## Publications and Use Cases

SDOM has been used in various research studies to analyze storage deployment needs under different renewable energy scenarios. See the [publications page](sdom_publications.md) for details.

## Contributing

We welcome contributions! Please see our [Contributing Guidelines](sdom_Developers_guide.md) for details on how to:

- Lear how you can set-up your enviroment to contribute to SDOM source code
- Report bugs
- Suggest enhancements
- Submit pull requests
- Run tests locally

## License

SDOM is released under the [MIT License](https://github.com/NatLabRockies/SDOM/blob/main/LICENSE.txt).

## Indices and tables

* {ref}`genindex`
* {ref}`modindex`
* {ref}`search`
