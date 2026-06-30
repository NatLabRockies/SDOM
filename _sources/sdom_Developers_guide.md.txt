# GUIDELINES FOR DEVELOPING SDOM

## General Guidelines

- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) for code style and formatting.
- Write clear, concise, and well-documented code.
- Add docstrings to all public classes, methods, and functions.
- Include unit tests for new features and bug fixes.
- Use descriptive commit messages.
- Open issues or discussions for significant changes before submitting a pull request.
- Ensure all tests pass before submitting code.
- Keep dependencies minimal and document any new requirements.
- Review and update documentation as needed.
- Be respectful and collaborative in all communications.


## Table of Contents
- [GUIDELINES FOR DEVELOPING SDOM](#guidelines-for-developing-sdom)
  - [General Guidelines](#general-guidelines)
- [clone/fork SDOM repo](#clonefork-sdom-repo)
- [Setting up your enviroment](#setting-up-your-enviroment)
    - [Install uv](#install-uv)
    - [Install your local SDOM python module and pytest](#install-your-local-sdom-python-module-and-pytest)
- [Running tests locally](#running-tests-locally)
- [Build the documentation locally](#build-the-documentation-locally)
- [General Source code structure](#general-source-code-structure)


# clone/fork SDOM repo
- Open VS code and use file -> open folder and select the folder where you want to copy the repo.
- Clone in your local the python version of SDOM repo:
```powershell
git clone https://github.com/Omar0902/SDOM.git
```

# Setting up your enviroment
## Install uv
- Install uv [(A python manager for virtual enviroments, installing packages etc)](https://pypi.org/project/uv/). 
```powershell
pip install uv
```
For further instructions click in the link above.

- Create a virtual enviroment ".venv"
```powershell
uv venv .venv
```
This command creates a new Python virtual environment in the `.venv` directory.

## Install your local SDOM python module and pytest
- To be able to run the tests locally and develop SDOM source code, install your local SDOM module by runing in your powershell terminal (Modify the folder address approprietly):
```powershell
uv pip install -e "C:\YOUR_PATH\SDOM"
```

- It will install also the SDOM dependencies. You should see something like this:

```powershell
Resolved 17 packages in 342ms
      Built sdom @ file:///C:/YOUR_PATH/SDOM
Prepared 7 packages in 7.40s
░░░░░░░░░░░░░░░░░░░░ [0/17] Installing wheels...                                                                                                         warning: Failed to hardlink files; falling back to full copy. This may lead to degraded performance.
         If the cache and target directories are on different filesystems, hardlinking may not be supported.
         If this is intentional, set `export UV_LINK_MODE=copy` or use `--link-mode=copy` to suppress this warning.
Installed 17 packages in 10.95s
 + contourpy==1.3.3
 + cycler==0.12.1
 + fonttools==4.62.1
 + highspy==1.13.1
 + kiwisolver==1.5.0
 + matplotlib==3.10.8
 + numpy==2.4.4
 + packaging==26.1
 + pandas==2.3.3
 + pillow==12.2.0
 + pyomo==6.10.0
 + pyparsing==3.3.2
 + python-dateutil==2.9.0.post0
 + pytz==2026.1.post1
 + sdom==0.1.2 (from file:///C:/YOUR_PATH/SDOM)
 + six==1.17.0
 + tzdata==2026.1


- Also, install:
  - [pytests.py](https://docs.pytest.org/en/stable/) to be able to run the tests locally:
```powershell
uv pip install pytest
```

  - run the following codes to install all the requirements to build SDOM documentation:
```powershell
uv pip install -r docs\requirements.txt
```

# Running tests locally
The SDOM python version source code have a folder called "tests". This folder contains all the scripts with the unit tests. 

 **⚠️ Attention:**  
>  - Before to push and/or do a pull request please run locally all the tests scripts and make sure all the tests are passing sucessfully.
>  - Please add unit test for all new features and source code implementations.


- To run all the test files:
```powershell
uv run pytest
```

- To run a test python script you can use:
```powershell
uv run pytest tests/TEST_SCRIPT_NAME.py
```
- For instance, to run the tests of the script called "test_no_resiliency_optimization_cases.py" you should run
```powershell
uv run pytest tests/test_no_resiliency_optimization_cases.py
```
- This is an example of what you should see:
```powershell
uv run pytest tests/test_no_resiliency_optimization_cases.py
================================================================== test session starts ==================================================================
platform win32 -- Python 3.12.4, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\smachado\repositories\pySDOM\SDOM
configfile: pyproject.toml
plugins: anyio-4.8.0, hydra-core-1.3.2
collected 2 items                                                                                                                                                                                                       

tests\test_no_resiliency_optimization_cases.py ..                                                                                                                                                                 [100%]

================================================================== 2 passed in 2.71s ===================================================================
```

# Build the documentation locally

Please update the documentationd in the folder ``docs`` for each new feature implementation you are making in a pull request. The SDOM documentation is based on [sphinx](https://www.sphinx-doc.org/en/master/usage/quickstart.html).


 **⚠️ Attention:**  
>  - Before to push and/or do a pull request please build locally the documentation and make sure it does not have any issues.
>  - Please add Docstrings to all code implementations you include in your contributions.
>  - Add proper documentation for the new features before submit a pull request.

- In order to build locally the documentation and check if your changes are correct you can run:

```powershell
uv run .\docs\make.bat html
```
- to visualize locally the documentation website run
```
start docs\build\html\index.html
```

# General Source code structure
Below is a diagram illustrating the general folder and script structure of the SDOM repository:

```
SDOM/
├── src/
│   └── sdom/                          # Main SDOM source code package
│       ├── __init__.py
│       ├── __main__.py
│       ├── config_sdom.py             # SDOM configuration settings
│       ├── constants.py               # Global constants
│       ├── initializations.py         # Model initialization routines
│       ├── io_manager.py              # Input/output data management
│       ├── optimization_main.py       # Main optimization entry point
│       ├── results.py                 # Results processing and export
│       ├── utils_performance_meassure.py  # Performance measurement utilities
│       ├── common/                    # Shared utilities
│       │   └── utilities.py
│       ├── models/                    # Pyomo optimization formulations
│       │   ├── formulations_hydro.py
│       │   ├── formulations_imports_exports.py
│       │   ├── formulations_load.py
│       │   ├── formulations_nuclear.py
│       │   ├── formulations_other_renewables.py
│       │   ├── formulations_resiliency.py
│       │   ├── formulations_storage.py
│       │   ├── formulations_system.py
│       │   ├── formulations_thermal.py
│       │   ├── formulations_vre.py
│       │   └── models_utils.py
│       ├── analytic_tools/            # Post-optimization analysis and plotting
│       │   ├── __init__.py
│       │   ├── _colors.py
│       │   ├── _parametric.py
│       │   ├── _single.py
│       │   └── _utils.py
│       └── parametric/                # Parametric study framework
│           ├── __init__.py
│           ├── mutations.py
│           ├── study.py
│           ├── sweeps.py
│           └── worker.py
├── tests/                             # Unit and integration tests
│   ├── constants_test.py
│   ├── utils_tests.py
│   ├── test_input_data.py
│   ├── test_input_data_hydro_budget.py
│   ├── test_input_data_hydro_budget_imports_exports.py
│   ├── test_output_data.py
│   ├── test_no_resiliency_optimization_cases.py
│   ├── test_no_resiliency_hydro_budget_optimization_cases.py
│   ├── test_no_resiliency_imp_exp_hydro_budget_optimization_cases.py
│   ├── test_resiliency_optimization_cases.py
│   ├── test_parametric.py
│   ├── test_parametric_integration.py
│   ├── test_analytic_tools.py
│   └── test_docs_build.py
├── Data/                              # Input data sets for different scenarios
│   ├── exchange_hydro_daily_budget_multiple_balancing_p95/
│   ├── no_exchange_hydro_daily_budget_multiple_balancing_p95/
│   ├── no_exchange_monthly_hydro_budget_multiple_balancing_p50/
│   ├── no_exchange_run_of_river/
│   ├── storage_costs_templates/
│   └── test/
├── docs/                              # Sphinx documentation
│   ├── make.bat
│   ├── Makefile
│   ├── requirements.txt
│   └── source/
│       ├── conf.py
│       ├── index.md
│       ├── sdom_Developers_guide.md
│       ├── sdom_publications.md
│       ├── parametric_implementation.md
│       ├── api/                       # API reference (auto-generated)
│       └── user_guide/                # User guide pages
├── Solver/                            # Optimization solver binaries
│   └── bin/
├── results_pyomo/                     # Output directory for optimization results
├── .github/                           # CI/CD workflows
│   └── workflows/
│       ├── test.yaml
│       └── docs.yml
├── pyproject.toml                     # Project metadata and build configuration
├── LICENSE.txt
└── README.md
```