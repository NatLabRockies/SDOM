"""Extract operational tables and technology metrics from a model host."""


import numpy as np
import pandas as pd

from ..common.utilities import safe_pyomo_value
from ..constants import MW_TO_KW
from ._values import _collect_curtailment_costs, _value_or_nan, _value_or_zero
from .hydro import _collect_hydro_budget_energy


def _collect_thermal_generation_dataframe(host, *, generation: np.ndarray | None = None) -> pd.DataFrame:
    """Collect long-format hourly thermal dispatch for every owned plant.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        System or area exposing ``h`` and ``thermal.plants_set``.
    generation : numpy.ndarray, optional
        Already extracted hour-major dispatch, reused by zonal collection.

    Returns
    -------
    pandas.DataFrame
        Columns ``Hour``, ``Plant ID``, and ``Generation (MW)``, including
        zero dispatch and single-plant fleets. Empty fleets retain the schema.

    Raises
    ------
    ValueError
        If individual thermal dispatch contains missing or nonfinite values.
    """
    hours = list(host.h)
    plants = list(host.thermal.plants_set)
    if generation is None:
        generation = np.fromiter(
            (_value_or_nan(host.thermal.generation[hour, plant]) for hour in hours for plant in plants),
            dtype=float,
            count=len(hours) * len(plants),
        )
    values = generation.reshape(-1)
    if not np.isfinite(values).all():
        raise ValueError(f"Nonfinite thermal dispatch for {host.name}.")
    return pd.DataFrame(
        {
            "Hour": np.repeat(np.asarray(hours, dtype=int), len(plants)),
            "Plant ID": np.tile(np.asarray(plants, dtype=object), len(hours)),
            "Generation (MW)": values,
        }
    )


def _collect_host_metrics(host, hours, *, case_name: str = "run") -> dict:
    """Collect dispatch and capacity metrics from a single host block.

    Mirrors the legacy collection logic in
    :func:`_collect_results_copperplate` but operates on an arbitrary ``host``
    (either the top-level model or an area sub-block ``model.area[a]``).
    Imports / exports terms are guarded by ``hasattr`` so this helper is
    safe to call on a zonal area block where the imports / exports
    variables and cost expressions are intentionally not added.

    Parameters
    ----------
    host : pyomo.environ.Block or pyomo.environ.ConcreteModel
        The block exposing ``pv``, ``wind``, ``thermal``, ``storage``,
        ``hydro``, ``demand``, ``nuclear``, ``other_renewables`` (and,
        on legacy hosts, ``imports``/``exports``) sub-blocks.
    hours : iterable of int
        Hours to iterate over (e.g. ``list(model.h)`` or ``list(host.h)``).
    case_name : str, optional
        Scenario label for the per-row ``"Scenario"`` column of the
        generation DataFrame. Defaults to ``"run"``.

    Returns
    -------
    dict
        Bundle with keys:

        - ``capacity`` : dict by technology (Thermal, Solar PV, Wind, All).
        - ``storage_capacity`` : dict with ``charge``/``discharge``/``energy``.
        - ``storage_tech_list`` : list of storage tech identifiers.
        - ``generation_totals`` : dict by technology (incl. each storage tech).
        - ``cost_breakdown`` : dict (``capex``, ``power_capex``, ``energy_capex``,
          ``fom``, ``vom``, ``fuel_cost``, ``imports_cost``, ``exports_revenue``,
          and additive ``curtailment_cost`` keyed by Solar PV, Wind, Hydro).
          Signed curtailment costs are authoritative model expressions in USD.
        - ``hydro_budget_energy`` : tuple of budget and unused energy in MWh,
          validated independently for each period.
        - ``generation_df``, ``storage_df``, ``thermal_generation_df``,
          ``installed_plants_df`` : pandas DataFrames with the same schema
          as the legacy top-level frames.
    """
    hours = list(hours)
    n_hours = len(hours)
    storage_tech_list = list(host.storage.j)
    storage_tech_arr = np.array(storage_tech_list, dtype=object)
    thermal_plants = list(host.thermal.plants_set)
    n_thermal = len(thermal_plants)

    # One-pass extraction of solved values for hourly outputs.
    solar_gen = np.fromiter(
        (_value_or_nan(host.pv.generation[h]) for h in hours),
        dtype=float,
        count=n_hours,
    )
    solar_curt = np.fromiter(
        (_value_or_nan(host.pv.curtailment[h]) for h in hours),
        dtype=float,
        count=n_hours,
    )
    wind_gen = np.fromiter(
        (_value_or_nan(host.wind.generation[h]) for h in hours),
        dtype=float,
        count=n_hours,
    )
    wind_curt = np.fromiter(
        (_value_or_nan(host.wind.curtailment[h]) for h in hours),
        dtype=float,
        count=n_hours,
    )
    hydro_gen = np.fromiter(
        (_value_or_nan(host.hydro.generation[h]) for h in hours),
        dtype=float,
        count=n_hours,
    )

    if n_thermal > 0:
        thermal_flat = np.fromiter(
            (
                _value_or_nan(host.thermal.generation[h, bu])
                for h in hours
                for bu in thermal_plants
            ),
            dtype=float,
            count=n_hours * n_thermal,
        )
        thermal_mat = thermal_flat.reshape(n_hours, n_thermal)
    else:
        thermal_mat = np.zeros((n_hours, 0), dtype=float)
    thermal_total_per_hour = np.nansum(thermal_mat, axis=1)

    n_storage = len(storage_tech_list)
    if n_storage > 0:
        storage_pc_flat = np.fromiter(
            (
                _value_or_nan(host.storage.PC[h, j])
                for h in hours
                for j in storage_tech_list
            ),
            dtype=float,
            count=n_hours * n_storage,
        )
        storage_pd_flat = np.fromiter(
            (
                _value_or_nan(host.storage.PD[h, j])
                for h in hours
                for j in storage_tech_list
            ),
            dtype=float,
            count=n_hours * n_storage,
        )
        storage_soc_flat = np.fromiter(
            (
                _value_or_nan(host.storage.SOC[h, j])
                for h in hours
                for j in storage_tech_list
            ),
            dtype=float,
            count=n_hours * n_storage,
        )
        storage_pc_mat = storage_pc_flat.reshape(n_hours, n_storage)
        storage_pd_mat = storage_pd_flat.reshape(n_hours, n_storage)
        storage_soc_mat = storage_soc_flat.reshape(n_hours, n_storage)
        storage_net_per_hour = np.nansum(storage_pc_mat, axis=1) - np.nansum(
            storage_pd_mat, axis=1
        )
    else:
        storage_pc_mat = np.zeros((n_hours, 0), dtype=float)
        storage_pd_mat = np.zeros((n_hours, 0), dtype=float)
        storage_soc_mat = np.zeros((n_hours, 0), dtype=float)
        storage_net_per_hour = np.zeros(n_hours, dtype=float)

    has_nuclear_alpha = hasattr(host.nuclear, "alpha")
    has_other_alpha = hasattr(host.other_renewables, "alpha")
    nuclear_alpha = _value_or_zero(host.nuclear.alpha) if has_nuclear_alpha else 0.0
    other_alpha = (
        _value_or_zero(host.other_renewables.alpha) if has_other_alpha else 0.0
    )
    nuclear_ts = np.fromiter(
        (_value_or_zero(host.nuclear.ts_parameter[h]) for h in hours),
        dtype=float,
        count=n_hours,
    )
    other_ts = np.fromiter(
        (_value_or_zero(host.other_renewables.ts_parameter[h]) for h in hours),
        dtype=float,
        count=n_hours,
    )
    nuclear_gen = nuclear_alpha * nuclear_ts
    other_gen = other_alpha * other_ts

    if hasattr(host, "imports") and hasattr(host.imports, "variable"):
        imports_series = np.fromiter(
            (_value_or_nan(host.imports.variable[h]) for h in hours),
            dtype=float,
            count=n_hours,
        )
    else:
        imports_series = np.zeros(n_hours, dtype=float)
    if hasattr(host, "exports") and hasattr(host.exports, "variable"):
        exports_series = np.fromiter(
            (_value_or_nan(host.exports.variable[h]) for h in hours),
            dtype=float,
            count=n_hours,
        )
    else:
        exports_series = np.zeros(n_hours, dtype=float)
    load_series = np.fromiter(
        (_value_or_nan(host.demand.ts_parameter[h]) for h in hours),
        dtype=float,
        count=n_hours,
    )
    if hasattr(host, "net_load"):
        net_load_series = np.fromiter(
            (_value_or_nan(host.net_load[h]) for h in hours),
            dtype=float,
            count=n_hours,
        )
    else:
        net_load_series = np.zeros(n_hours, dtype=float)

    # Capacities -----------------------------------------------------------
    capacity = {
        "Thermal": safe_pyomo_value(host.thermal.total_installed_capacity),
        "Solar PV": safe_pyomo_value(host.pv.total_installed_capacity),
        "Wind": safe_pyomo_value(host.wind.total_installed_capacity),
    }
    capacity["All"] = capacity["Thermal"] + capacity["Solar PV"] + capacity["Wind"]

    charge_cap = {t: safe_pyomo_value(host.storage.Pcha[t]) for t in storage_tech_list}
    discharge_cap = {t: safe_pyomo_value(host.storage.Pdis[t]) for t in storage_tech_list}
    energy_cap = {t: safe_pyomo_value(host.storage.Ecap[t]) for t in storage_tech_list}
    charge_cap["All"] = sum(charge_cap[t] for t in storage_tech_list)
    discharge_cap["All"] = sum(discharge_cap[t] for t in storage_tech_list)
    energy_cap["All"] = sum(energy_cap[t] for t in storage_tech_list)
    storage_capacity = {
        "charge": charge_cap,
        "discharge": discharge_cap,
        "energy": energy_cap,
    }

    # Generation totals ----------------------------------------------------
    generation_totals = {
        "Thermal": float(np.nansum(thermal_total_per_hour)),
        "Solar PV": float(np.nansum(solar_gen)),
        "Wind": float(np.nansum(wind_gen)),
        "Other renewables": float(np.nansum(other_gen)),
        "Hydro": float(np.nansum(hydro_gen) * _value_or_zero(host.hydro.alpha)),
        "Nuclear": float(np.nansum(nuclear_gen)),
    }
    storage_discharge_total = 0.0
    for idx, tech in enumerate(storage_tech_list):
        tech_discharge = float(np.nansum(storage_pd_mat[:, idx]))
        generation_totals[tech] = tech_discharge
        storage_discharge_total += tech_discharge
    generation_totals["All"] = (
        generation_totals["Thermal"]
        + generation_totals["Solar PV"]
        + generation_totals["Wind"]
        + generation_totals["Other renewables"]
        + generation_totals["Hydro"]
        + generation_totals["Nuclear"]
        + storage_discharge_total
    )

    # Cost breakdown -------------------------------------------------------
    capex = {
        "Solar PV": safe_pyomo_value(host.pv.capex_cost_expr),
        "Wind": safe_pyomo_value(host.wind.capex_cost_expr),
        "Thermal": safe_pyomo_value(host.thermal.capex_cost_expr),
    }
    capex["All"] = capex["Solar PV"] + capex["Wind"] + capex["Thermal"]

    power_capex = {
        t: safe_pyomo_value(host.storage.power_capex_cost_expr[t]) for t in storage_tech_list
    }
    energy_capex = {
        t: safe_pyomo_value(host.storage.energy_capex_cost_expr[t]) for t in storage_tech_list
    }
    power_capex["All"] = sum(power_capex[t] for t in storage_tech_list)
    energy_capex["All"] = sum(energy_capex[t] for t in storage_tech_list)

    fom = {
        "Thermal": safe_pyomo_value(host.thermal.fixed_om_cost_expr),
        "Solar PV": safe_pyomo_value(host.pv.fixed_om_cost_expr),
        "Wind": safe_pyomo_value(host.wind.fixed_om_cost_expr),
    }
    fom_storage_total = 0.0
    for tech in storage_tech_list:
        fom[tech] = safe_pyomo_value(
            MW_TO_KW * host.storage.data["CostRatio", tech] * host.storage.data["FOM", tech] * host.storage.Pcha[tech]
            + MW_TO_KW * (1 - host.storage.data["CostRatio", tech]) * host.storage.data["FOM", tech] * host.storage.Pdis[tech]
        )
        fom_storage_total += fom[tech]
    fom["All"] = fom["Thermal"] + fom["Solar PV"] + fom["Wind"] + fom_storage_total

    vom = {"Thermal": safe_pyomo_value(host.thermal.total_vom_cost_expr)}
    vom_storage_total = 0.0
    for idx, tech in enumerate(storage_tech_list):
        vom[tech] = safe_pyomo_value(
            host.storage.data["VOM", tech] * float(np.nansum(storage_pd_mat[:, idx]))
        )
        vom_storage_total += vom[tech]
    vom["All"] = vom["Thermal"] + vom_storage_total

    fuel_cost = {"Thermal": safe_pyomo_value(host.thermal.total_fuel_cost_expr)}

    imports_cost = (
        safe_pyomo_value(host.imports.total_cost_expr)
        if hasattr(host, "imports") and hasattr(host.imports, "total_cost_expr")
        else 0.0
    )
    exports_revenue = (
        safe_pyomo_value(host.exports.total_cost_expr)
        if hasattr(host, "exports") and hasattr(host.exports, "total_cost_expr")
        else 0.0
    )

    cost_breakdown = {
        "capex": capex,
        "power_capex": power_capex,
        "energy_capex": energy_capex,
        "fom": fom,
        "vom": vom,
        "fuel_cost": fuel_cost,
        "imports_cost": imports_cost,
        "exports_revenue": exports_revenue,
        "curtailment_cost": _collect_curtailment_costs(host),
    }

    # Generation DataFrame -------------------------------------------------
    valid_mask = (
        ~np.isnan(solar_gen)
        & ~np.isnan(solar_curt)
        & ~np.isnan(wind_gen)
        & ~np.isnan(wind_curt)
        & ~np.isnan(thermal_total_per_hour)
        & ~np.isnan(hydro_gen)
        & ~np.isnan(imports_series)
        & ~np.isnan(exports_series)
        & ~np.isnan(load_series)
    )
    hours_arr = np.asarray(hours)
    generation_df = pd.DataFrame(
        {
            "Scenario": np.full(np.count_nonzero(valid_mask), case_name, dtype=object),
            "Hour": hours_arr[valid_mask],
            "Solar PV Generation (MW)": solar_gen[valid_mask],
            "Solar PV Curtailment (MW)": solar_curt[valid_mask],
            "Wind Generation (MW)": wind_gen[valid_mask],
            "Wind Curtailment (MW)": wind_curt[valid_mask],
            "All Thermal Generation (MW)": thermal_total_per_hour[valid_mask],
            "Hydro Generation (MW)": hydro_gen[valid_mask],
            "Nuclear Generation (MW)": nuclear_gen[valid_mask],
            "Other Renewables Generation (MW)": other_gen[valid_mask],
            "Imports (MW)": imports_series[valid_mask],
            "Storage Charge/Discharge (MW)": storage_net_per_hour[valid_mask],
            "Exports (MW)": exports_series[valid_mask],
            "Load (MW)": load_series[valid_mask],
            "Net Load (MW)": net_load_series[valid_mask],
        }
    )

    # Storage DataFrame ----------------------------------------------------
    if n_storage > 0:
        hour_repeat = np.repeat(hours_arr, n_storage)
        tech_tile = np.tile(storage_tech_arr, n_hours)
        charge_flat = storage_pc_mat.reshape(-1)
        discharge_flat = storage_pd_mat.reshape(-1)
        soc_flat = storage_soc_mat.reshape(-1)
        storage_valid = (
            ~np.isnan(charge_flat)
            & ~np.isnan(discharge_flat)
            & ~np.isnan(soc_flat)
        )
        storage_df = pd.DataFrame(
            {
                "Hour": hour_repeat[storage_valid],
                "Technology": tech_tile[storage_valid],
                "Charging power (MW)": charge_flat[storage_valid],
                "Discharging power (MW)": discharge_flat[storage_valid],
                "State of charge (MWh)": soc_flat[storage_valid],
            }
        )
    else:
        storage_df = pd.DataFrame(
            columns=[
                "Hour",
                "Technology",
                "Charging power (MW)",
                "Discharging power (MW)",
                "State of charge (MWh)",
            ]
        )

    # Thermal generation DataFrame (disaggregated) -------------------------
    thermal_generation_df = _collect_thermal_generation_dataframe(host, generation=thermal_mat)

    # Installed plants DataFrame ------------------------------------------
    installed_plants_data = {
        "Plant ID": [],
        "Technology": [],
        "Installed Capacity (MW)": [],
        "Max Capacity (MW)": [],
        "Capacity Fraction": [],
    }
    for plant in host.pv.plants_set:
        installed_cap = safe_pyomo_value(host.pv.plant_installed_capacity[plant])
        max_cap = safe_pyomo_value(host.pv.max_capacity[plant])
        cap_fraction = safe_pyomo_value(host.pv.capacity_fraction[plant])
        installed_plants_data["Plant ID"].append(str(plant))
        installed_plants_data["Technology"].append("Solar PV")
        installed_plants_data["Installed Capacity (MW)"].append(installed_cap)
        installed_plants_data["Max Capacity (MW)"].append(max_cap)
        installed_plants_data["Capacity Fraction"].append(cap_fraction)
    for plant in host.wind.plants_set:
        installed_cap = safe_pyomo_value(host.wind.plant_installed_capacity[plant])
        max_cap = safe_pyomo_value(host.wind.max_capacity[plant])
        cap_fraction = safe_pyomo_value(host.wind.capacity_fraction[plant])
        installed_plants_data["Plant ID"].append(str(plant))
        installed_plants_data["Technology"].append("Wind")
        installed_plants_data["Installed Capacity (MW)"].append(installed_cap)
        installed_plants_data["Max Capacity (MW)"].append(max_cap)
        installed_plants_data["Capacity Fraction"].append(cap_fraction)
    for plant in host.thermal.plants_set:
        installed_cap = safe_pyomo_value(host.thermal.plant_installed_capacity[plant])
        max_cap = safe_pyomo_value(host.thermal.data["MaxCapacity", plant])
        cap_fraction = installed_cap / max_cap if max_cap > 0 else 0.0
        installed_plants_data["Plant ID"].append(str(plant))
        installed_plants_data["Technology"].append("Thermal")
        installed_plants_data["Installed Capacity (MW)"].append(installed_cap)
        installed_plants_data["Max Capacity (MW)"].append(max_cap)
        installed_plants_data["Capacity Fraction"].append(cap_fraction)
    installed_plants_df = pd.DataFrame(installed_plants_data)

    return {
        "capacity": capacity,
        "storage_capacity": storage_capacity,
        "storage_tech_list": storage_tech_list,
        "generation_totals": generation_totals,
        "cost_breakdown": cost_breakdown,
        "generation_df": generation_df,
        "storage_df": storage_df,
        "thermal_generation_df": thermal_generation_df,
        "installed_plants_df": installed_plants_df,
        "hydro_budget_energy": _collect_hydro_budget_energy(host, hydro_gen),
    }
