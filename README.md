# Storage Deployment Optimization Model (SDOM)
[![Tests](https://github.com/Omar0902/SDOM/workflows/Run%20Python%20Tests/badge.svg)](https://github.com/Omar0902/SDOM/actions/workflows/test.yaml)
[![Documentation](https://github.com/Omar0902/SDOM/workflows/Build%20and%20Deploy%20Documentation/badge.svg)](https://omar0902.github.io/SDOM/)
[![DOI](https://img.shields.io/badge/DOI-OSTI%20Code--111266-blue)](https://www.osti.gov/biblio/code-111266)
[![PyPI Downloads](https://img.shields.io/pypi/dm/sdom)](https://pypistats.org/packages/sdom)

SDOM (Storage Deployment Optimization Model) is an open-source, high-resolution grid capacity-expansion framework developed by the National Lab of the Rockies (NLR). It’s purpose-built to optimize the deployment and operation of energy storage technologies, leveraging hourly temporal resolution and granular spatial representation of Variable Renewable Energy (VRE) sources such as solar and wind.

SDOM is particularly well-suited for figure out the required capacity to meet a carbon-free generation mix target by:
- 📆 Evaluating long-duration and seasonal storage technologies
- 🌦 Analyzing complementarity and synergies among diverse VRE resources
- 📉 Assessing curtailment and operational strategies under various grid scenarios

## Table of contents
- [How SDOM Works](#how-sdom-works)
- [Key Features](#key-features)
- [Optimization Scope](#optimization-scope)
- [Notes on Model Expansion](#notes-on-model-expansion)
- [Sample Results](#sample-results)
- [Getting Started with SDOM](#getting-started-with-sdom)
  - [System Setup and Prerequisites](#system-setup-and-prerequisites)
  - [Install SDOM](#install-sdom)
  - [SDOM Input Files](#sdom-input-files)
  - [SDOM simple script example](#sdom-simple-script-example)
- [Publications and Use Cases of SDOM](#publications-and-use-cases-of-sdom)
- [Contributing Guidelines](#contributing-guidelines)


# How SDOM Works?
🔍 At its core, SDOM models the gap between electricity demand and fixed generation:

Inputs include time series data for:
- Load profiles
- Fixed generation (e.g., large hydropower, nuclear, and other must-run renewables)

Outputs include:
- The optimal technology portfolio capacity (PV solar, wind, storage types, thermal capacity) to reliably meet demand.
- Dispatch profiles for each technology, highlighting how resources are operated hour-by-hour.
- Insights on operational metrics like VRE curtailment, storage cycling, and thermal usage.

An illustrative figure below shows the flow from inputs to optimization results, enabling exploration of storage needs under varying renewable integration levels.

![Illustration about how SDOM works](https://github.com/Omar0902/SDOM/blob/master/docs/source/user_guide/sdom_illustration.png)

# Key Features
⚙️

- **Accurate Representation of Storage Technologies Diversity:** SDOM is strongly focused in providing a framework able to represent different storage technologies by:
  - Representation of short, long an seassonal storage technologies,
  -  Including charging/discharging capacity decoupling,
  -  Optimization of both energy and power capacity,
  -  Full temporal cronology.

- **Temporal Resolution:** Hourly simulations over a full year enable precise modeling of storage dynamics and renewable generation variability.

- **Spatial Resolution:** Fine-grained representation of VRE sources (e.g., solar, wind) captures geographic diversity and enhances system fidelity.

- **Copper Plate Modeling:** SDOM Model neglects transmission constraints to keep the model tractable from the computational standpoint. Future SDOM releases should include inter-regional transmission constraints.

- **Fixed Generation Profiles:** Nuclear, hydropower, and other non-variable renewables (e.g., biomass, geothermal) are treated as fixed inputs using year-long time series data.
  - Currently its beeing developed a modeling approach to include a Hydro modeling considering Monthly energy budgets in order to be able to represent the hydro flexibility.

- **System Optimization Objective:** Minimizes total system cost—including capital, fixed/variable O&M, and fuel costs—while satisfying user-defined carbon-free or renewable energy targets.

- **Modeling approach:** Formulated as a Mixed-Integer Linear Programming (MILP) model to allow rigorous optimization of investment and capacity decisions.

- **Parametric & Sensitivity Analysis:** Built-in [`ParametricStudy`](docs/source/user_guide/parametric_analysis.md) API to run multi-dimensional parameter sweeps in parallel — sweep `GenMix_Target`, technologies CAPEX costs, load growth factors, and more.

- **Platforms:** 
  - SDOM was originally developed in GAMS (https://github.com/NREL/SDOM). 
  
  - In order offer a full open-source solution also was developed this python package. This version requires python 3.10+.

- **Solver Compatibility:** Currently the SDOM python version has been tested using [open-source CBC solver](https://www.coin-or.org/Cbc/cbcuserguide.html) and [HiGHS open-source solver](https://highs.dev/) through highspy module. In this repo the [windows executable for cbc](./cbc.exe) is provided. You will need to provide the path of cbc solver to run SDOM as illustrated in our [script demonstration](#sdom-example-(demonstration-script))

## Optimization Scope
📉
SDOM performs cost minimization across a 1-year operation window using a copper plate assumption—i.e., no internal transmission constraints—making it computationally efficient while capturing major cost drivers. Conventional generators are used as balancing resources, and storage technologies serve to meet carbon or renewable penetration goals.

## Notes on Model Expansion
While SDOM currently supports a 1-year horizon, multiyear analyses could provide deeper insights into how interannual variability affects storage needs. Chronological, simulation-based approaches are better suited for this but present significant computational challenges—especially at hourly resolution. Extending SDOM to support multiyear optimization is left as future work.

## Sample Results

The figures below show example outputs from a 3-dimensional parametric study
(3 carbon-free targets × 2 storage CAPEX factors × 2 load scaling factors = 12 cases)
run against the `Data/no_exchange_run_of_river/` dataset included in this repository.

**Installed capacity by technology across all cases**

![Capacity comparison](docs/source/_static/parametric_example/sensitivity_plots/capacity_comparison.png)

**Total generation by technology across all cases**

![Generation comparison](docs/source/_static/parametric_example/sensitivity_plots/generation_comparison.png)

**VRE curtailment across all cases**

![Curtailment — absolute](docs/source/_static/parametric_example/sensitivity_plots/curtailment_absolute.png)

**Per-case capacity and generation mix (GenMix\_Target = 1.0, base CAPEX, base load)**

![Capacity and generation donuts](docs/source/_static/parametric_example/case_plots/capacity_generation_donuts.png)

**Hourly dispatch heatmap — net load**

![Heatmap — net load](docs/source/_static/parametric_example/case_plots/heatmap_net_load.png)

# GETTING STARTED WITH SDOM
## System Setup and Prerequisites 

- a. You'll need to install [python](https://www.python.org/downloads/)
  - After the installation make sure the [python enviroment variable is set](https://realpython.com/add-python-to-path/).
- b. Also, You'll need an IDE (Integrated Development Environment), we recommend to install [MS VS code](https://code.visualstudio.com/)
- d. We alse recommend to install extensions such as:
  - [edit CSV](https://marketplace.visualstudio.com/items?itemName=janisdd.vscode-edit-csv): To edit and interact with input csv files for SDOM directly in vs code.
  - [vscode-pdf](https://marketplace.visualstudio.com/items?itemName=tomoki1207.pdf): to read and see pdf files directly in vscode.


## Install SDOM

It is recommended to load the packages in a virtual enviroment. 

We recommend to use `uv`, a Python manager for virtual environments and packages.  

- a. Install `uv` following the instructions at [uv on PyPI](https://pypi.org/project/uv/).

- b. Create a new virtual environment named `.venv`:

  ```bash
  uv venv .venv
  ```
        This command creates a Python virtual environment in the `.venv` directory.


- c. Activate your virtual environment and install the SDOM package:

  ```bash
  uv pip install sdom
  ```
        
- d. Install the python module according to your solver. We'll use here [HiGHS open-source solver](https://highs.dev/)

  ```bash
  uv pip install highspy
  ```

- e. Install the Logging package to be able to see sdom info, warning and error messages and log those:

  ```bash
  uv pip install logging
  ```

- f. Verify your environment by listing installed packages:

  In your terminal or powershell run:

  ```bash
  uv pip list
  ```

  You should see output similar to:

  ```bash
Package         Version
--------------- -----------
contourpy       1.3.3
cycler          0.12.1
fonttools       4.63.0
highspy         1.14.0
kiwisolver      1.5.0
matplotlib      3.10.9
numpy           2.4.6
packaging       26.2
pandas          2.3.3
pillow          12.2.0
pyomo           6.10.0
pyparsing       3.3.2
python-dateutil 2.9.0.post0
pytz            2026.2
sdom            0.2.3
six             1.17.0
tzdata          2026.2
  ```

## SDOM Input Files
For detailed information about SDOM input files, please refer to the [SDOM Input Documentation](https://github.com/Omar0902/SDOM/blob/master/docs/source/user_guide/inputs.md).

## SDOM simple script example
For an script about how to run SDOM, please refer to the [SDOM simple script example](https://github.com/Omar0902/SDOM/blob/master/docs/source/user_guide/running_and_outputs.md).

# PUBLICATIONS AND USE CASES OF SDOM
📄
For a comprehensive list of publications and use cases, please refer to the [SDOM Publications Documentation](https://github.com/Omar0902/SDOM/blob/master/docs/source/sdom_publications.md).

# CONTRIBUTING GUIDELINES
💻
[Developers Guide](https://github.com/Omar0902/SDOM/blob/master/docs/source/sdom_Developers_guide.md) 
