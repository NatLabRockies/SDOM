"""Write structured optimization result DataFrames to CSV."""

import logging
import os

from ..results import OptimizationResults


def export_results(
    results: OptimizationResults, case: str | int, output_dir: str = "./results_pyomo/"
) -> None:
    """Export optimization results to CSV files.

    Writes the results from an OptimizationResults object to CSV files in the
    specified directory. Creates output directory if it doesn't exist.

    Parameters
    ----------
    results : OptimizationResults
        Structured optimization results returned by run_solver() or
        reconstructed from an Infrasys System.
    case : str or int
        Case identifier used in output filenames to distinguish between
        different scenarios or runs.
    output_dir : str, optional
        Directory path for output files. Defaults to './results_pyomo/'.
        Directory will be created if it doesn't exist.

    Returns
    -------
    None

    Raises
    ------
    TypeError
        If results is not an OptimizationResults instance. Legacy exports
        directly from Pyomo models were deprecated and are no longer supported.
        Invalid inputs are rejected before creating directories or writing files.

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
        Cost breakdowns (VRE, storage, thermal CAPEX/FOM/VOM), and system-wide
        unused hydro budget energy (TWh and percentage, technology ``Hydro``).
        Includes individual Solar PV, Wind, and Hydro curtailment costs in
        USD, including signed and inactive zero values, already in Total cost.

    OutputThermalGeneration_{case}.csv
        Long individual dispatch with Hour, Area, Plant ID, and Generation
        (MW) columns. Includes single-plant fleets and zero dispatch.
        Copperplate uses area ``copperplate``; zonal rows use owning areas.

    OutputInterregionalExchanges_{case}.csv
        Hourly per-line interregional exchanges (PRD §2.4 schema). Emitted
        only for zonal runs (``Network = AreaTransportationModelNetwork``)
        when ``results.interregional_exchanges_df`` is non-empty. Columns:
        ``line_id, from_area, to_area, hour, flow_signed_MW, flow_FT_MW,
        flow_TF_MW, cap_FT_MW, cap_TF_MW, utilization_FT, utilization_TF``.
        Row count is ``|L| * n_hours``.

    OutputMarginalPrices_{case}.csv
        Fixed-decision LP marginal prices for successful solves. Columns:
        ``hour, area_id, marginal_price_USD_per_MWh,
        generation_component_USD_per_MWh, congestion_component_USD_per_MWh,
        supply_balance_dual, line_congestion_dual_sum, pricing_method,
        pricing_status``.

    Notes
    -----
    Export the result of ``run_solver(model, solver_config)``, not the raw model.
    Marginal prices use a case-specific filename so exporting another case into
    the same directory does not overwrite previously exported prices.
    """
    if not isinstance(results, OptimizationResults):
        raise TypeError(
            "export_results() requires an OptimizationResults instance. "
            "Legacy exports directly from Pyomo models were deprecated and are no longer supported. "
            "Use results = run_solver(model, solver_config), then export_results(results, case, output_dir)."
        )
    logging.info("Exporting SDOM results...")
    os.makedirs(output_dir, exist_ok=True)

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
            os.path.join(output_dir, f"OutputMarginalPrices_{case}.csv"),
            index=False,
        )
