# Model Formulations

Documentation for model formulation modules.

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
   :undoc-members:
   :show-inheritance:
```

## Storage Formulations

```{eval-rst}
.. automodule:: sdom.models.formulations_storage
   :members:
   :undoc-members:
   :show-inheritance:
```

## Thermal Formulations

```{eval-rst}
.. automodule:: sdom.models.formulations_thermal
   :members:
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
   :undoc-members:
   :show-inheritance:
```

## Network (Zonal) Formulations

```{eval-rst}
.. automodule:: sdom.models.formulations_network
   :members:
   :undoc-members:
   :show-inheritance:
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
