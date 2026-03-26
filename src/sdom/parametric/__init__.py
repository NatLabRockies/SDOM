"""sdom.parametric — Parametric sensitivity analysis for SDOM.

This sub-package provides a high-level API for running multi-dimensional
sensitivity studies in parallel.  Users typically only need
:class:`ParametricStudy`.

Quick example
-------------
>>> from sdom.parametric import ParametricStudy
>>> study = ParametricStudy(base_data=data, solver_config=solver_cfg, n_hours=8760)
>>> study.add_scalar_sweep("scalars", "GenMix_Target", [0.8, 0.9, 1.0])
>>> study.add_storage_factor_sweep("P_Capex", [0.7, 1.0])
>>> study.add_ts_sweep("load_data", [0.95, 1.05])
>>> results = study.run()  # 3 × 2 × 2 = 12 cases
"""

from .study import ParametricStudy
from .sweeps import ScalarSweep, StorageFactorSweep, TsSweep

__all__ = [
    "ParametricStudy",
    "ScalarSweep",
    "StorageFactorSweep",
    "TsSweep",
]
