"""Store optimization results and expose nonmutating accessors."""


from dataclasses import dataclass, field

import pandas as pd

from .results_aggregation import _aggregate_zonal_generation_by_hour

_RESULT_ATTRIBUTE_UNITS = {
    "capacity": "MW",
    "storage_capacity.charge": "MW",
    "storage_capacity.discharge": "MW",
    "storage_capacity.energy": "MWh",
    "generation_totals": "MWh",
    "cost_breakdown": "USD",
}


@dataclass
class OptimizationResults:
    """Data class containing all optimization results from SDOM.

    This class stores the complete results from an SDOM optimization run,
    organized into DataFrames for different result categories (generation,
    storage, summary) and provides convenient accessors for specific metrics.

    Attributes
    ----------
    termination_condition : str
        The solver termination condition (e.g., 'optimal', 'infeasible').
    solver_status : str
        The solver status (e.g., 'ok', 'warning').
    total_cost : float
        The total objective value (cost) from the optimization.
    gen_mix_target : float
        The generation mix target value used in this run.
    generation_df : pd.DataFrame
        Hourly generation dispatch results for all technologies.
    storage_df : pd.DataFrame
        Hourly storage operation results (charge, discharge, SOC).
    thermal_generation_df : pd.DataFrame
        Long dispatch with Hour, Area, Plant ID, and Generation (MW) columns.
        Copperplate uses area ``copperplate``; zonal rows identify the owner.
    installed_plants_df : pd.DataFrame
        Installed capacity for each individual power plant (solar, wind, thermal).
    summary_df : pd.DataFrame
        Summary metrics including capacities, costs, totals, and system-wide
        unused hydro budget energy (TWh and percentage of available budget).
    problem_info : dict
        Solver problem information (constraints, variables, etc.).
    capacity : dict
        Installed capacity by technology.
    storage_capacity : dict
        Storage capacity details (charge, discharge, energy).
    generation_totals : dict
        Total generation by technology.
    cost_breakdown : dict
        Detailed cost breakdown (CAPEX, OPEX, FOM, VOM), including signed
        modeled-horizon USD ``curtailment_cost`` keyed by Solar PV, Wind, Hydro.
        The same nested category is present in ``area_cost_breakdown`` for
        zonal results and already included once in ``total_cost``.
        Older stored dictionaries without this additive category remain valid.
    attribute_units : dict[str, str]
        Display units for public result-attribute dictionaries. This metadata
        is optional for directly constructed and legacy deserialized results.
    """

    # Solver information
    termination_condition: str = ""
    solver_status: str = ""

    # Main objective
    total_cost: float = 0.0
    gen_mix_target: float = 0.0

    # DataFrames for CSV export
    generation_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    storage_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    thermal_generation_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    installed_plants_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    summary_df: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Problem info from solver
    problem_info: dict = field(default_factory=dict)

    # Capacity results
    capacity: dict = field(default_factory=dict)
    storage_capacity: dict = field(default_factory=dict)

    # Generation totals
    generation_totals: dict = field(default_factory=dict)

    # Cost breakdown
    cost_breakdown: dict = field(default_factory=dict)

    # ----------------------------------------------------------------------------------
    # Zonal-aware optional fields (PRD §6.1).
    #
    # These fields are populated only when the solved model is a zonal
    # ``AreaTransportationModelNetwork`` model (detected by the presence of
    # ``model.A``/``model.area``). On the legacy copper-plate path they keep
    # their default empty values so existing code paths are unaffected.
    # ----------------------------------------------------------------------------------
    is_zonal: bool = False
    areas: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    area_capacity: dict = field(default_factory=dict)
    area_storage_capacity: dict = field(default_factory=dict)
    area_generation_totals: dict = field(default_factory=dict)
    area_cost_breakdown: dict = field(default_factory=dict)
    area_generation_df: dict = field(default_factory=dict)
    area_storage_df: dict = field(default_factory=dict)
    area_thermal_generation_df: dict = field(default_factory=dict)
    area_installed_plants_df: dict = field(default_factory=dict)
    area_summary_df: dict = field(default_factory=dict)
    interregional_exchanges_df: pd.DataFrame = field(default_factory=pd.DataFrame)

    attribute_units: dict[str, str] = field(default_factory=dict)
    marginal_prices_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    line_congestion_duals_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    system_generation_df: pd.DataFrame = field(default_factory=pd.DataFrame)

    # ----------------------------------------------------------------------------------
    # Convenience properties for backward compatibility and easy access
    # ----------------------------------------------------------------------------------

    @property
    def is_optimal(self) -> bool:
        """Check if the solution is optimal."""
        return self.termination_condition == "optimal"

    def get_attribute_unit(self, name: str) -> str | None:
        """Return the display unit associated with a public result attribute.

        Parameters
        ----------
        name : str
            Result attribute name, including a dot-qualified nested key such
            as ``"storage_capacity.energy"``.

        Returns
        -------
        str or None
            The configured display unit, or ``None`` when unit metadata is
            unavailable for the attribute.
        """
        return getattr(self, "attribute_units", {}).get(name)

    # Capacity accessors
    @property
    def total_cap_thermal(self) -> float:
        """Total installed thermal capacity (MW)."""
        return self.capacity.get("Thermal", 0.0)

    @property
    def total_cap_pv(self) -> float:
        """Total installed solar PV capacity (MW)."""
        return self.capacity.get("Solar PV", 0.0)

    @property
    def total_cap_wind(self) -> float:
        """Total installed wind capacity (MW)."""
        return self.capacity.get("Wind", 0.0)

    @property
    def total_cap_storage_charge(self) -> dict:
        """Storage charging power capacity by technology (MW)."""
        return self.storage_capacity.get("charge", {})

    @property
    def total_cap_storage_discharge(self) -> dict:
        """Storage discharging power capacity by technology (MW)."""
        return self.storage_capacity.get("discharge", {})

    @property
    def total_cap_storage_energy(self) -> dict:
        """Storage energy capacity by technology (MWh)."""
        return self.storage_capacity.get("energy", {})

    # Generation accessors
    @property
    def total_gen_pv(self) -> float:
        """Total solar PV generation (MWh)."""
        return self.generation_totals.get("Solar PV", 0.0)

    @property
    def total_gen_wind(self) -> float:
        """Total wind generation (MWh)."""
        return self.generation_totals.get("Wind", 0.0)

    @property
    def total_gen_thermal(self) -> float:
        """Total thermal generation (MWh)."""
        return self.generation_totals.get("Thermal", 0.0)

    # ----------------------------------------------------------------------------------
    # DataFrame accessors
    # ----------------------------------------------------------------------------------

    def get_generation_dataframe(self) -> pd.DataFrame:
        """Get the hourly generation dispatch DataFrame.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: Scenario, Hour, Solar PV Generation (MW),
            Solar PV Curtailment (MW), Wind Generation (MW), Wind Curtailment (MW),
            All Thermal Generation (MW), Hydro Generation (MW), Nuclear Generation (MW),
            Other Renewables Generation (MW), Imports (MW), Storage Charge/Discharge (MW),
            Exports (MW), Load (MW).
        """
        return self.generation_df.copy()

    def get_system_generation_dataframe(self) -> pd.DataFrame:
        """Return hourly generation dispatch aggregated to the system level.

        Returns
        -------
        pd.DataFrame
            One row per hour for zonal results, or the copperplate generation
            DataFrame unchanged. Zonal net load is derived from aggregate
            fixed-generation quantities rather than summed across areas.
        """
        if not self.is_zonal:
            return self.generation_df.copy()
        system_generation_df = getattr(self, "system_generation_df", None)
        if system_generation_df is not None and not system_generation_df.empty:
            return system_generation_df.copy()
        return _aggregate_zonal_generation_by_hour(self.generation_df)

    def get_storage_dataframe(self) -> pd.DataFrame:
        """Get the hourly storage operation DataFrame.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: Hour, Technology, Charging power (MW),
            Discharging power (MW), State of charge (MWh).
        """
        return self.storage_df.copy()

    def get_thermal_generation_dataframe(self) -> pd.DataFrame:
        """Get the disaggregated hourly thermal generation DataFrame.

        Returns
        -------
        pd.DataFrame
            One row per hour and owned plant, with columns ``Hour``, ``Area``,
            ``Plant ID``, and ``Generation (MW)``. Copperplate uses area
            ``copperplate``; zero dispatch and single-plant fleets are retained.
        """
        return self.thermal_generation_df.copy()

    def get_summary_dataframe(self) -> pd.DataFrame:
        """Get the summary metrics DataFrame.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: Metric, Technology, Run, Optimal Value, Unit.
        """
        return self.summary_df.copy()

    def get_installed_plants_dataframe(self) -> pd.DataFrame:
        """Get the installed power plants capacity DataFrame.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: Plant ID, Technology, Installed Capacity (MW),
            Max Capacity (MW), Capacity Fraction.
        """
        return self.installed_plants_df.copy()

    def get_marginal_prices_dataframe(self) -> pd.DataFrame:
        """Return hourly marginal prices from the fixed-decision pricing LP.

        Returns
        -------
        pd.DataFrame
            Price rows keyed by hour and area. Numeric price fields are NaN
            whenever ``pricing_status`` reports unavailable duals or pricing.
        """
        return self.marginal_prices_df.copy()

    def get_line_congestion_duals_dataframe(self) -> pd.DataFrame:
        """Return directional zonal line-capacity duals for price auditing.

        Returns
        -------
        pd.DataFrame
            Rows keyed by line and hour with upper/lower capacity duals and
            their sum. Empty for copper-plate runs.
        """
        return self.line_congestion_duals_df.copy()

    def get_problem_info(self) -> dict:
        """Return solver problem-size information.

        Returns
        -------
        dict
            Dictionary with counts for constraints, variables, binary
            variables, objectives, and nonzeros.
        """
        return self.problem_info.copy()


# Preserve the historical class path for persisted results and worker pickles.
OptimizationResults.__module__ = "sdom.results"
