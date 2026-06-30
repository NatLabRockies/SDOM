# Resiliency Module

API reference for `sdom.resiliency` -- the operational-resiliency evaluation
module. See the user-guide page {doc}`../user_guide/resiliency` for the
mathematical background, file-format requirements and worked examples.

## Top-Level Convenience

```{eval-rst}
.. autofunction:: sdom.resiliency.evaluate_resiliency
```

## Data Loading

```{eval-rst}
.. autofunction:: sdom.resiliency.load_designed_system

.. autoclass:: sdom.resiliency.DesignedSystem
   :members:

.. autoclass:: sdom.resiliency.BaselineState
   :members:
```

## Outage Specification

```{eval-rst}
.. autoclass:: sdom.resiliency.OutageSpec
   :members:
   :special-members: __post_init__

.. autodata:: sdom.resiliency.VALID_COMPONENTS
   :no-value:

.. autodata:: sdom.resiliency.MUST_RUN_COMPONENTS
   :no-value:
```

## Baseline Dispatch (Problem B)

```{eval-rst}
.. autofunction:: sdom.resiliency.build_baseline_dispatch

.. autofunction:: sdom.resiliency.run_baseline_dispatch

.. autoclass:: sdom.resiliency.BaselineDispatchResults
   :members:
```

## Outage Dispatch (Problem O)

```{eval-rst}
.. autofunction:: sdom.resiliency.build_outage_dispatch
```

## Imports Formulation with Demand Charges

The opt-in `ImportsWithDemandChargesFormulation` block builder used by the
baseline LP. Pure linear program; not registered in
`io_manager.py`.

```{eval-rst}
.. autofunction:: sdom.resiliency.add_imports_with_demand_charges
```

## Parallel Runner

```{eval-rst}
.. autofunction:: sdom.resiliency.run_resiliency_evaluation
```

## Results Container

```{eval-rst}
.. autoclass:: sdom.resiliency.ResiliencyResults
   :members:
```

## Plotting

```{eval-rst}
.. autofunction:: sdom.resiliency.plot_metric_distribution
```
