# Model Formulations

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

```{eval-rst}
.. automodule:: sdom.models.formulations_thermal
   :members:
   :private-members:
   :undoc-members:
   :show-inheritance:
```

## Hydropower Formulations

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
