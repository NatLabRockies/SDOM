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
resiliency
infrasys_integration
```

## Quick Links

- {doc}`core` - Main optimization functions
- {doc}`results` - Optimization results data structure
- {doc}`models` - Model formulation modules  
- {doc}`io_manager` - Data loading and export
- {doc}`utilities` - Helper functions
- {doc}`parametric` - Parametric & sensitivity analysis
- {doc}`resiliency` - Operational resiliency evaluation
- {doc}`infrasys_integration` - Optional infrasys System adapters

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
```

## Package Structure

```
sdom/
├── __init__.py              # Package exports
├── config_sdom.py           # Logging configuration
├── constants.py             # Constants and mappings
├── optimization_main.py     # Model initialization and solving
├── results/                 # Structured results and model-value collection
│   ├── __init__.py          # Backward-compatible results API
│   ├── containers.py        # OptimizationResults and accessors
│   ├── results_collection_main.py  # Model collection dispatcher
│   ├── collect_copperplate_resuts.py  # Single-area collection
│   ├── collect_zonal_resuts.py  # Zonal assembly and network exchanges
│   ├── collect_individual_host_results.py  # Host metrics and thermal dispatch
│   ├── results_aggregation.py  # DataFrame and dictionary rollups
│   ├── summary.py           # Summary metric tables
│   ├── hydro.py             # Hydro-budget calculation and validation
│   ├── pricing.py           # Marginal-price and congestion-dual extraction
│   └── _values.py           # Internal numeric value helpers
├── io_manager.py            # Historical I/O compatibility facade
├── io/
│   ├── loader.py           # CSV reads and canonical dictionary preparation
│   ├── validation.py       # Shared input rules, without filesystem access
│   ├── formulations.py     # Selection and missing-row defaults
│   ├── areas.py            # Area parsing and per-area views
│   ├── network.py          # Topology and line-capacity reads
│   ├── aggregation.py      # Zonal-to-copper-plate transformations
│   └── export.py           # OptimizationResults CSV export
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
