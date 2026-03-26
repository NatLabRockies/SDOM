"""sdom.analytic_tools — Plotting capabilities for SDOM simulation results.

This sub-package provides a high-level plotting API for both single-simulation
and parametric sensitivity-analysis results.

The dependency only flows **inward**: ``analytic_tools`` imports from
``sdom`` internals (e.g. :class:`~sdom.results.OptimizationResults`), never
the reverse.  Core solver modules must **not** import from this package.

Quick examples
--------------
Single simulation::

    from sdom.analytic_tools import plot_results
    plot_results(result, output_dir="results/my_case")

Parametric study::

    from sdom.analytic_tools import plot_parametric_results
    plot_parametric_results(
        study, results,
        group_by="GenMix_Target",
        hue_by="P_Capex",
    )
"""

from ._parametric import plot_parametric_results
from ._single import plot_results

__all__ = [
    "plot_results",
    "plot_parametric_results",
]
