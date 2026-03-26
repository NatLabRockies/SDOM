# API Reference

Complete API documentation for the SDOM package.

## Core Modules

```{toctree}
:maxdepth: 2

core
results
models
io_manager
utilities
parametric
```

## Quick Links

- {doc}`core` - Main optimization functions
- {doc}`results` - Optimization results data structure
- {doc}`models` - Model formulation modules  
- {doc}`io_manager` - Data loading and export
- {doc}`utilities` - Helper functions
- {doc}`parametric` - Parametric & sensitivity analysis

## Main Functions

The most commonly used functions are:

```{eval-rst}
.. currentmodule:: sdom

.. autosummary::
   :toctree: _autosummary

   load_data
   initialize_model
   run_solver
   export_results
   get_default_solver_config_dict
   configure_logging
   OptimizationResults
   ParametricStudy
```

## Package Structure

```
sdom/
├── __init__.py              # Package exports
├── config_sdom.py           # Logging configuration
├── constants.py             # Constants and mappings
├── optimization_main.py     # Model initialization and solving
├── results.py               # Results data structures
├── io_manager.py            # Data I/O operations
├── initializations.py       # Sets and parameters initialization
├── parametric/              # Parametric & sensitivity analysis
│   ├── __init__.py          # Public surface (ParametricStudy, sweep types)
│   ├── sweeps.py            # ScalarSweep, StorageFactorSweep, TsSweep
│   ├── mutations.py         # Data mutation helpers + TS_KEY_TO_COLUMN
│   ├── worker.py            # Multiprocessing worker (_run_single_case)
│   └── study.py             # ParametricStudy orchestrator
├── common/
│   └── utilities.py         # Helper utilities
└── models/
    ├── models_utils.py      # Model building utilities
    ├── formulations_system.py
    ├── formulations_vre.py
    ├── formulations_storage.py
    ├── formulations_thermal.py
    ├── formulations_hydro.py
    └── formulations_imports_exports.py
```
