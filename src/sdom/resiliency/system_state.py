"""Dataclasses describing the fixed-capacity designed system and baseline state.

These containers are populated by :mod:`sdom.resiliency.data_loader` and consumed
by the (future) baseline and outage dispatch builders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class DesignedSystem:
    """Fixed-capacity designed system loaded from SDOM output snapshots.

    Parameters
    ----------
    storage_caps : dict
        Mapping ``{tech: {"Cap_Pch", "Cap_Pdis", "Cap_E", "eta_ch",
        "eta_dis", "soc_min_frac", "vom"}}`` for each storage technology with
        non-zero capacity. Capacities are in MW / MWh.
    thermal_caps : dict
        Mapping ``{tech: {"capacity_MW", "heat_rate", "fuel_cost",
        "vom", "var_cost"}}`` for each thermal technology with non-zero
        capacity. ``var_cost = heat_rate * fuel_cost + vom``.
    solar_caps : dict
        Mapping ``{plant_id: capacity_MW}`` for selected solar plants.
    wind_caps : dict
        Mapping ``{plant_id: capacity_MW}`` for selected wind plants.
    load, nuclear, hydro, other_renewables : pandas.Series
        Hourly time-series (length 8760) indexed by hour-of-year (1..8760).
    cf_solar, cf_wind : pandas.DataFrame
        Hourly capacity factors with columns indexed by plant id.
    import_cap, import_price, export_cap, export_price : pandas.Series
        Hourly grid-exchange capacity and price series.
    phi_fix_t, phi_var_t : pandas.Series
        Hourly fixed and variable demand-charge tariffs (USD/MW or USD/MWh).
    month_of_hour : pandas.Series
        Mapping from hour-of-year (1..8760) to calendar month (1..12) used to
        bill demand charges per month.
    scenario_id : int
        Scenario / Run id resolved from the snapshot CSVs.
    year : int
        Calendar year of the snapshot.
    formulation_map : dict
        Mapping ``{component: formulation_name}`` resolved from defaults
        plus user-provided overrides.
    """

    storage_caps: dict[str, dict[str, float]] = field(default_factory=dict)
    thermal_caps: dict[str, dict[str, float]] = field(default_factory=dict)
    solar_caps: dict[str, float] = field(default_factory=dict)
    wind_caps: dict[str, float] = field(default_factory=dict)

    load: pd.Series | None = None
    cf_solar: pd.DataFrame | None = None
    cf_wind: pd.DataFrame | None = None
    nuclear: pd.Series | None = None
    hydro: pd.Series | None = None
    other_renewables: pd.Series | None = None

    import_cap: pd.Series | None = None
    import_price: pd.Series | None = None
    export_cap: pd.Series | None = None
    export_price: pd.Series | None = None

    phi_fix_t: pd.Series | None = None
    phi_var_t: pd.Series | None = None
    month_of_hour: pd.Series | None = None

    scenario_id: int = 1
    year: int = 2030
    formulation_map: dict[str, str] = field(default_factory=dict)


@dataclass
class BaselineState:
    """Placeholder container for baseline-dispatch outputs (Phase 2).

    Parameters
    ----------
    soc_trajectory : pandas.DataFrame, optional
        Hourly state-of-charge per storage technology (hour x tech).
    solver_status : str, optional
        Solver termination status from the baseline run.
    objective_value : float, optional
        Baseline objective value (USD).
    metadata : dict, optional
        Free-form solver / run metadata.
    """

    soc_trajectory: pd.DataFrame | None = None
    solver_status: str | None = None
    objective_value: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BaselineDispatchResults:
    """Trajectories and metadata produced by :func:`run_baseline_dispatch`.

    Parameters
    ----------
    soc_trajectory : pandas.DataFrame
        Hourly state-of-charge per storage technology, indexed by hour and
        with one column per tech (MWh).
    pcha_trajectory, pdis_trajectory : pandas.DataFrame
        Hourly charge / discharge per storage tech (MW).
    pthermal_trajectory : pandas.DataFrame
        Hourly thermal dispatch per balancing-unit Plant_id (MW). Empty
        ``DataFrame`` when no thermal units survive the snapshot filter.
    psolar_trajectory, pwind_trajectory : pandas.DataFrame
        Hourly dispatched solar / wind power per plant id (MW).
    pimp, pexp : pandas.Series
        Hourly imports / exports (MW).
    nuclear, hydro, other_renewables, load : pandas.Series
        Hourly time-series parameters echoed from the input system (MW).
    month_of_hour : pandas.Series
        Hour -> month mapping used by the demand-charge billing.
    objective_value : float
        Operational objective value (USD).
    solver_status : str
        Solver termination condition (e.g. ``"optimal"``).
    metadata : dict, optional
        Free-form solver / run metadata.
    """

    soc_trajectory: pd.DataFrame | None = None
    pcha_trajectory: pd.DataFrame | None = None
    pdis_trajectory: pd.DataFrame | None = None
    pthermal_trajectory: pd.DataFrame | None = None
    psolar_trajectory: pd.DataFrame | None = None
    pwind_trajectory: pd.DataFrame | None = None
    pimp: pd.Series | None = None
    pexp: pd.Series | None = None
    nuclear: pd.Series | None = None
    hydro: pd.Series | None = None
    other_renewables: pd.Series | None = None
    load: pd.Series | None = None
    month_of_hour: pd.Series | None = None
    objective_value: float | None = None
    solver_status: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
