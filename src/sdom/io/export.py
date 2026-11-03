"""Write modern result DataFrames and dispatch deprecated model exports."""

import logging
import os

from ..results import OptimizationResults
from ._legacy_export import _export_from_model_legacy


def export_results(results, case: str, output_dir: str = "./results_pyomo/"):
    """Export optimization results to CSV files.

    Writes the results from an OptimizationResults object to CSV files in the
    specified directory. Creates output directory if it doesn't exist.

    Parameters
    ----------
    results : OptimizationResults or pyomo.environ.ConcreteModel
        The optimization results object from run_solver(), or a solved model
        for the deprecated direct-model export path.
    case : str or int
        Case identifier used in output filenames to distinguish between
        different scenarios or runs.
    output_dir : str, optional
        Directory path for output files. Defaults to './results_pyomo/'.
        Directory will be created if it doesn't exist.

    Returns
    -------
    None

    Output Files
    ------------
    OutputGeneration_{case}.csv
        Hourly dispatch results containing: Scenario, Hour, Solar PV/Wind
        generation and curtailment, Thermal, hydro, nuclear, other renewables
        generation, Storage net charge/discharge, imports, exports, Load.
        Zonal runs contain one system aggregate row per hour.

    OutputGenerationPerArea_{case}.csv
        Zonal-only hourly dispatch results with one row per ``Area`` and hour.

    OutputStorage_{case}.csv
        Hourly storage operation for each technology: Hour, Technology,
        Charging power (MW), Discharging power (MW), State of charge (MWh).

    OutputSummary_{case}.csv
        Summary metrics including: Total costs, Installed capacities by
        technology, Total generation by technology, Demand statistics,
        Cost breakdowns (VRE, storage, thermal CAPEX/FOM/VOM).

    OutputThermalGeneration_{case}.csv
        Disaggregated hourly thermal generation by plant (only if more than
        one thermal plant exists).

    OutputInterregionalExchanges_{case}.csv
        Hourly per-line interregional exchanges (PRD §2.4 schema). Emitted
        only for zonal runs (``Network = AreaTransportationModelNetwork``)
        when ``results.interregional_exchanges_df`` is non-empty. Columns:
        ``line_id, from_area, to_area, hour, flow_signed_MW, flow_FT_MW,
        flow_TF_MW, cap_FT_MW, cap_TF_MW, utilization_FT, utilization_TF``.
        Row count is ``|L| * n_hours``.

    marginal_prices.csv
        Fixed-decision LP marginal prices for successful solves. Columns:
        ``hour, area_id, marginal_price_USD_per_MWh,
        generation_component_USD_per_MWh, congestion_component_USD_per_MWh,
        supply_balance_dual, line_congestion_dual_sum, pricing_method,
        pricing_status``.

    Notes
    -----
    This function accepts either an OptimizationResults dataclass or a solved
    Pyomo model (deprecated). Both paths retain their existing CSV schemas.
    """
    logging.info("Exporting SDOM results...")
    os.makedirs(output_dir, exist_ok=True)

    # Handle both new OptimizationResults and legacy model input
    if isinstance(results, OptimizationResults):
        _export_from_results_object(results, case, output_dir)
    else:
        # Legacy support: assume it's a model object
        logging.warning(
            "export_results() received a model object instead of OptimizationResults. "
            "This usage is deprecated. Please use the OptimizationResults from run_solver()."
        )
        _export_from_model_legacy(results, case, output_dir)


def _export_from_results_object(results, case: str, output_dir: str):
    """Export results from OptimizationResults object to CSV files.

    Parameters
    ----------
    results : OptimizationResults
        The optimization results object.
    case : str
        Case identifier for filenames.
    output_dir : str
        Output directory path.
    """
    logging.info("Exporting csv files containing SDOM results...")

    # Save generation results to CSV
    logging.debug("-- Saving generation results to CSV...")
    gen_df = results.get_system_generation_dataframe()
    if not gen_df.empty:
        # Update scenario column with the case name
        gen_df["Scenario"] = case
        gen_df.to_csv(os.path.join(output_dir, f"OutputGeneration_{case}.csv"), index=False)

    if getattr(results, "is_zonal", False):
        area_gen_df = results.get_generation_dataframe()
        if not area_gen_df.empty:
            area_gen_df["Scenario"] = case
            area_gen_df.to_csv(
                os.path.join(output_dir, f"OutputGenerationPerArea_{case}.csv"),
                index=False,
            )

    # Save storage results to CSV
    logging.debug("-- Saving storage results to CSV...")
    storage_df = results.get_storage_dataframe()
    if not storage_df.empty:
        storage_df.to_csv(os.path.join(output_dir, f"OutputStorage_{case}.csv"), index=False)

    # Save summary results to CSV
    logging.debug("-- Saving summary results to CSV...")
    summary_df = results.get_summary_dataframe()
    if not summary_df.empty:
        summary_df.to_csv(os.path.join(output_dir, f"OutputSummary_{case}.csv"), index=False)

    # Save thermal generation results to CSV (if available)
    logging.debug("-- Saving disaggregated thermal generation results to CSV...")
    thermal_df = results.get_thermal_generation_dataframe()
    if not thermal_df.empty:
        thermal_df.to_csv(os.path.join(output_dir, f"OutputThermalGeneration_{case}.csv"), index=False)

    # Save installed power plants results to CSV
    logging.debug("-- Saving installed power plants results to CSV...")
    installed_plants_df = results.get_installed_plants_dataframe()
    if not installed_plants_df.empty:
        installed_plants_df.to_csv(
            os.path.join(output_dir, f"OutputInstalledPowerPlants_{case}.csv"), index=False
        )

    # Save interregional exchanges results to CSV (zonal / AreaTransportationModelNetwork only)
    logging.debug("-- Saving interregional exchanges results to CSV...")
    interregional_df = getattr(results, "interregional_exchanges_df", None)
    if interregional_df is not None and not interregional_df.empty:
        interregional_df.to_csv(
            os.path.join(output_dir, f"OutputInterregionalExchanges_{case}.csv"),
            index=False,
        )

    marginal_prices_df = getattr(results, "marginal_prices_df", None)
    if marginal_prices_df is not None and not marginal_prices_df.empty:
        marginal_prices_df.to_csv(
            os.path.join(output_dir, "marginal_prices.csv"),
            index=False,
        )
