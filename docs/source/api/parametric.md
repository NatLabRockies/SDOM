# `sdom.parametric` — Parametric Analysis

API reference for the `sdom.parametric` sub-package.

See the [user guide](../user_guide/parametric_analysis.md) for a full
usage walkthrough and worked examples.

---

## ParametricStudy

```{eval-rst}
.. currentmodule:: sdom.parametric

.. autoclass:: ParametricStudy
   :members: add_scalar_sweep, add_storage_factor_sweep, add_ts_sweep, run
   :member-order: bysource
```

---

## Sweep descriptors

```{eval-rst}
.. autoclass:: ScalarSweep
   :members:

.. autoclass:: StorageFactorSweep
   :members:

.. autoclass:: TsSweep
   :members:
```

---

## Internal helpers (advanced)

These are not part of the public API but are documented for contributors
and advanced users who need to add custom mutation logic.

```{eval-rst}
.. currentmodule:: sdom.parametric.mutations

.. autodata:: TS_KEY_TO_COLUMN

.. autofunction:: _apply_scalar_mutation

.. autofunction:: _apply_storage_factor_mutation

.. autofunction:: _apply_ts_mutation
```

```{eval-rst}
.. currentmodule:: sdom.parametric.worker

.. autofunction:: _run_single_case
```
