# Model Formulations

See [Pyomo Model Blocks and Input Provenance](../user_guide/pyomo_model_structure.md)
for the block hierarchy, field inventories, mathematical symbols, and CSV
origins of model parameters.

Implementation reference for the model formulation modules, including internal
rule helpers. Each equation-bearing rule documents its implemented relationship
in a NumPy-style `Notes` section, with symbol definitions and units.

Power is in MW and storage energy is in MWh. Time steps are implicitly one hour;
dispatch sums therefore represent MWh. Annualized CAPEX and fixed O&M are annual
costs, while variable costs accumulate over the modeled horizon without automatic
annual scaling. The docstrings identify formulation-specific exceptions, such as
the unscaled hydro energy budget and the unprorated storage cycle allowance.

For the full notation and formulation overview, see
{doc}`../user_guide/sdom_math_formulation` and
{doc}`../user_guide/zonal_math_formulation`.

## System Formulations

```{eval-rst}
.. automodule:: sdom.models.formulations_system
   :members:
   :undoc-members:
   :show-inheritance:
```

## VRE Formulations

```{eval-rst}
.. automodule:: sdom.models.formulations_vre
   :members:
   :private-members:
   :undoc-members:
   :show-inheritance:
```

## Storage Formulations

```{eval-rst}
.. automodule:: sdom.models.formulations_storage
   :members:
   :private-members:
   :undoc-members:
   :show-inheritance:
```

## Thermal Formulations

`add_thermal_constraints(host)` builds the upper bound and calls
`add_thermal_min_dispatch_constraints(host)` within the same profiled step.
The floor builder activates only when the validated immutable
`thermal.min_dispatch_fraction[h,k]` parameter exists, created by
`_add_thermal_min_dispatch_fraction_parameters(host, data, *, df)` only for
`NoRampsMinDispatchFormulation`. It uses
`thermal.min_dispatch_fraction[h,k]` in `[0,1]`. Zero coefficients skip rows:
there are $H K$ parameters, one inequality per positive modeled cell, and no
new variables or binaries; legacy mode creates neither new component.
The generic `sdom.io_manager.get_formulation` uses central component defaults
and a component-keyed validation policy. Missing Thermal rows default to legacy
dispatch; invalid/duplicate Thermal selections are rejected. Hydro, Imports,
and Exports remain required; other components retain their lookup behavior.
The existing Network accessor remains a compatibility wrapper.
Both CSV and direct-data construction
use `validate_thermal_min_dispatch` for input validation.
Enabled zonal and System paths also use `validate_thermal_ownership` before
consuming per-area tables, even for one area. System projection rechecks
retained source data; global-only copperplate construction does not consume
these views.

```{eval-rst}
.. automodule:: sdom.models.formulations_thermal
   :members:
   :private-members:
   :undoc-members:
   :show-inheritance:
```

## Hydropower Formulations

`DailyBudgetFormulation` and `MonthlyBudgetFormulation` enforce period-energy
equality. Select `DailyBudgetUpperBoundFormulation` or
`MonthlyBudgetUpperBoundFormulation` when availability is an upper bound and
unused energy is allowed, including when retaining the recently relaxed behavior
of the existing names. Equality is never automatically relaxed. All four use the
same hourly bounds and unscaled budgets, with fixed 24/730-hour periods and the
existing horizon rounding. `RunOfRiverFormulation` remains fixed-profile dispatch.
See the [hydro constraints and reporting equations](../user_guide/sdom_math_formulation.md#hydro-budget-constraints)
and [input selection guidance](../user_guide/inputs.md#large-hydropower).

```{eval-rst}
.. automodule:: sdom.models.formulations_hydro
   :members:
   :undoc-members:
   :show-inheritance:
```

## Import/Export Formulations

```{eval-rst}
.. automodule:: sdom.models.formulations_imports_exports
   :members:
   :private-members:
   :undoc-members:
   :show-inheritance:
```

## Capacity-Margin Formulation

In zonal models, construct the network flows before adding the per-area
capacity-margin constraints. These constraints reuse scheduled signed flows
to credit imports and deduct exports; they add no reserve-transfer variables.
Storage uses the nonnegative `reserves.storage_capacity_contribution[h,j]`
variable, bounded by discharge power and beginning SOC. This replaces
`storage_upward_capability` and `storage_activated_net_output`; scripts that
inspect those model internals should use the contribution variable instead.
Public runner signatures and result/export schemas are unchanged.

```{eval-rst}
.. automodule:: sdom.models.formulations_reserves
   :members:
```

## Network (Zonal) Formulations

```{eval-rst}
.. automodule:: sdom.models.formulations_network
   :members:
   :private-members:
   :undoc-members:
   :show-inheritance:
```

## Fixed Demand and Generation Profiles

These builders initialize parameters, not dispatch decisions. Nuclear and other
renewables are scaled by their activation parameters in downstream equations;
demand is used unscaled.

```{eval-rst}
.. automodule:: sdom.models.formulations_load
   :members:

.. automodule:: sdom.models.formulations_nuclear
   :members:

.. automodule:: sdom.models.formulations_other_renewables
   :members:
```

## Legacy Aggregate Resiliency Constraints

These helpers declare load shedding and aggregate energy limits. They do not
implement the separate outage-evaluation workflow described in
{doc}`../user_guide/resiliency_math`, nor do they add shedding to supply balance.

```{eval-rst}
.. automodule:: sdom.models.formulations_resiliency
   :members:
```

## Host Pattern in Formulation Builders

Most `add_*_*` model-builder functions now use `host` as the first argument.

- In copper-plate mode, `host` is the top-level model.
- In zonal mode, `host` is `model.area[a]` for each area.

This pattern allows the same formulation builders to populate either top-level blocks or per-area blocks.

## Model Utilities

Helper functions for building model components.

```{eval-rst}
.. automodule:: sdom.models.models_utils
   :members:
   :undoc-members:
   :show-inheritance:
```

## Initialization Functions

Functions for initializing model sets and parameters.

```{eval-rst}
.. automodule:: sdom.initializations
   :members:
   :undoc-members:
   :show-inheritance:
```
