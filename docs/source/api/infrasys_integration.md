# `sdom.infrasys_integration` - System Adapters

API reference for the optional infrasys System adapters. See the
[user guide](../user_guide/infrasys_integration.md) for copperplate, zonal,
persistence, result, and parametric workflows.

## Public adapter namespace

```{eval-rst}
.. automodule:: sdom.infrasys_integration
   :members:
   :member-order: bysource
```

## System loading and source data

```{eval-rst}
.. currentmodule:: sdom.infrasys_integration.make_system

.. autofunction:: load_system

.. autofunction:: load_system_from_data

.. autofunction:: system_to_data_dict

.. autofunction:: drop_system_source_data
```

## Pyomo builders

```{eval-rst}
.. currentmodule:: sdom.infrasys_integration.pyomo_builder

.. autofunction:: initialize_copperplate_model_from_system

.. autofunction:: initialize_model_from_system
```

Each builder returns a Pyomo `AbstractModel`; call its `create_instance()` once
to obtain the concrete model for `sdom.run_solver`. Instantiation releases the
retained compatibility source data.

## Results and plotting

```{eval-rst}
.. currentmodule:: sdom.infrasys_integration.results

.. autofunction:: add_results_to_system

.. autofunction:: optimization_results_from_system

.. autofunction:: query_result_attributes
```

```{eval-rst}
.. currentmodule:: sdom.infrasys_integration.plotting

.. autofunction:: plot_system_results

.. autofunction:: plot_system_parametric_results
```

## Parametric adapters

```{eval-rst}
.. currentmodule:: sdom.infrasys_integration.parametric

.. autoclass:: SystemParametricStudy
   :members: add_scalar_sweep, add_genmix_sweep, add_storage_factor_sweep, add_ts_sweep, run
   :member-order: bysource

.. autofunction:: apply_scalar_sweep_to_system

.. autofunction:: apply_time_series_sweep_to_system

.. autofunction:: add_parametric_results_to_system
```

`SystemParametricStudy` is an adapter around the legacy `sdom.parametric.ParametricStudy`;
the dict/CSV parametric API remains supported.