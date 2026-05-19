"""sdom.analytic_tools — Plotting capabilities for SDOM simulation results.

This sub-package provides a high-level plotting API for single-simulation,
parametric sensitivity-analysis, and zonal capacity-expansion results.

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

Zonal results::

    from sdom.analytic_tools import (
        plot_area_generation_stacks,
        plot_area_capacity_stacks,
        plot_line_flow_heatmap,
    )
    plot_area_generation_stacks(zonal_result, save_path="gen_stacks.png")
    plot_area_capacity_stacks(zonal_result, mode="power")
    plot_line_flow_heatmap(zonal_result)
"""

from ._parametric import plot_parametric_results
from ._single import plot_results
from ._zonal import (
    plot_area_capacity_stacks,
    plot_area_generation_stacks,
    plot_line_flow_heatmap,
)

__all__ = [
    "plot_results",
    "plot_parametric_results",
    "plot_area_generation_stacks",
    "plot_area_capacity_stacks",
    "plot_line_flow_heatmap",
]
