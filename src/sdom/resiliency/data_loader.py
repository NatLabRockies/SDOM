"""Load a fixed-capacity designed system from SDOM output CSV snapshots.

Phase 1 of the resiliency module reads the per-scenario capacities from a
prior SDOM design run plus the matching previous-stage input time-series CSVs
and returns a :class:`~sdom.resiliency.system_state.DesignedSystem`.

Notes
-----
- ``OutputGeneration_*.csv`` and ``OutputStorage_*.csv`` are intentionally
  ignored at this stage (per the resiliency-module plan).
- Files whose names contain ``Phase1`` are excluded from snapshot discovery.
- The previous-stage inputs directory does NOT contain a
  ``formulations.csv``; CSVs are therefore read directly with pandas
  rather than via :func:`sdom.io_manager.load_data`.
"""

from __future__ import annotations

import glob
import os
import warnings
from pathlib import Path

import pandas as pd

from sdom.resiliency.system_state import DesignedSystem


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_FORMULATION_MAP: dict[str, str] = {
    "Imports": "ImportsWithDemandChargesFormulation",
    "Exports": "ExportsFormulation",
    "Storage": "StorageFormulation",
    "Thermal": "ThermalFormulation",
    "Solar": "VREFormulation",
    "Wind": "VREFormulation",
    "Hydro": "HydroFormulation",
    "Nuclear": "NuclearFormulation",
    "OtherRenewables": "OtherRenewablesFormulation",
    "Load": "LoadFormulation",
}

_VRE_AGGREGATE_TECHS = {"Solar PV", "Wind", "All generation", "All technologies"}

# Metric labels in OutputSummary mapped to canonical storage capacity keys.
_STORAGE_METRIC_MAP = {
    "charge power capacity": "Cap_Pch",
    "discharge power capacity": "Cap_Pdis",
    "energy capacity": "Cap_E",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_snapshot_file(snapshot_dir: Path, prefix: str, year: int) -> Path:
    """Return the snapshot CSV matching ``{year}_{prefix}_*.csv``.

    Parameters
    ----------
    snapshot_dir : pathlib.Path
        Directory to search.
    prefix : str
        File prefix, e.g. ``"OutputSummary"``.
    year : int
        Year used in the file name.

    Returns
    -------
    pathlib.Path

    Raises
    ------
    FileNotFoundError
        When no matching file is found.
    """
    pattern = str(snapshot_dir / f"{year}_{prefix}_*.csv")
    matches = [Path(p) for p in glob.glob(pattern) if "Phase1" not in os.path.basename(p)]
    if not matches:
        raise FileNotFoundError(
            f"No {prefix} snapshot file matching pattern '{pattern}' "
            f"(excluding Phase1 files) was found."
        )
    # Deterministic selection: shortest filename wins (avoids picking ad-hoc copies).
    matches.sort(key=lambda p: (len(p.name), p.name))
    return matches[0]


def _detect_scenario_column(df: pd.DataFrame) -> str:
    """Return the scenario-filter column name (``Scenario`` or ``Run``)."""
    for col in ("Scenario", "Run"):
        if col in df.columns:
            return col
    raise ValueError(
        "Snapshot CSV is missing a scenario column; expected one of "
        "['Scenario', 'Run']."
    )


def _filter_scenario(df: pd.DataFrame, scenario_id: int, file_label: str) -> tuple[pd.DataFrame, int]:
    """Apply hybrid scenario-id resolution to a snapshot DataFrame.

    Parameters
    ----------
    df : pandas.DataFrame
        Snapshot DataFrame containing a ``Scenario`` or ``Run`` column.
    scenario_id : int
        User-requested scenario id.
    file_label : str
        Short label used in error / warning messages.

    Returns
    -------
    tuple of (pandas.DataFrame, int)
        Filtered DataFrame plus the resolved scenario id.

    Raises
    ------
    ValueError
        When multiple scenarios are present and none match ``scenario_id``.
    """
    col = _detect_scenario_column(df)
    unique_ids = sorted(int(v) for v in df[col].dropna().unique())
    if len(unique_ids) == 1:
        only = unique_ids[0]
        if int(scenario_id) != only:
            warnings.warn(
                f"{file_label}: only scenario_id={only} is present; ignoring "
                f"user-supplied scenario_id={scenario_id}.",
                stacklevel=3,
            )
        return df[df[col] == only].copy(), only
    if int(scenario_id) not in unique_ids:
        raise ValueError(
            f"{file_label}: scenario_id={scenario_id} not found. "
            f"Available scenario ids: {unique_ids}."
        )
    return df[df[col] == int(scenario_id)].copy(), int(scenario_id)


def _warn_zero_capacity(tech: str, value: float) -> None:
    warnings.warn(
        f"Technology '{tech}' has capacity={value}; excluding from designed system.",
        stacklevel=3,
    )


def _normalize_metric(metric: object) -> str:
    return str(metric).strip().lower()


def _load_summary_capacities(summary_path: Path, scenario_id: int):
    """Parse OutputSummary into raw capacity dicts.

    Returns
    -------
    dict
        ``{"storage_caps_raw", "thermal_caps_raw", "solar_total",
        "wind_total", "scenario_id"}``.
    """
    df = pd.read_csv(summary_path)
    df, resolved_id = _filter_scenario(df, scenario_id, file_label=summary_path.name)

    storage_caps_raw: dict[str, dict[str, float]] = {}
    thermal_caps_raw: dict[str, float] = {}
    solar_total = 0.0
    wind_total = 0.0

    for _, row in df.iterrows():
        metric = _normalize_metric(row["Metric"])
        tech = row["Technology"]
        try:
            value = float(row["Optimal Value"])
        except (TypeError, ValueError):
            continue

        # Storage capacities
        if metric in _STORAGE_METRIC_MAP:
            if pd.isna(tech) or tech == "All storage":
                continue
            key = _STORAGE_METRIC_MAP[metric]
            storage_caps_raw.setdefault(str(tech), {})[key] = value
            continue

        # Generation / VRE capacity rows
        if metric == "capacity":
            if pd.isna(tech):
                continue
            tech_str = str(tech).strip()
            if tech_str == "Solar PV":
                solar_total = value
            elif tech_str == "Wind":
                wind_total = value
            elif tech_str in _VRE_AGGREGATE_TECHS:
                continue
            else:
                thermal_caps_raw[tech_str] = value

    return {
        "storage_caps_raw": storage_caps_raw,
        "thermal_caps_raw": thermal_caps_raw,
        "solar_total": solar_total,
        "wind_total": wind_total,
        "scenario_id": resolved_id,
    }


def _load_vre_per_plant(snapshot_dir: Path, scenario_id: int, year: int):
    """Read OutputSelectedVRE and return per-plant capacity dicts."""
    path = _find_snapshot_file(snapshot_dir, "OutputSelectedVRE", year)
    df = pd.read_csv(path)
    # Strip stray spaces on header names (the file ships with "Selection ").
    df.columns = [c.strip() for c in df.columns]
    df, _ = _filter_scenario(df, scenario_id, file_label=path.name)
    cap_col = "Capacity (MW)"
    id_col = "VRE unit ID"
    tech_col = "Technology"

    solar_caps: dict[str, float] = {}
    wind_caps: dict[str, float] = {}
    for _, row in df.iterrows():
        plant_id = str(row[id_col]).strip()
        capacity = float(row[cap_col])
        tech = str(row[tech_col]).strip()
        if tech == "Solar PV":
            solar_caps[plant_id] = capacity
        elif tech == "Wind":
            wind_caps[plant_id] = capacity
    return solar_caps, wind_caps


def _read_hourly_csv(path: Path) -> pd.DataFrame:
    """Read a `*Hour`-indexed hourly CSV, normalising the index column."""
    df = pd.read_csv(path)
    df.columns = [c.lstrip("*").strip() for c in df.columns]
    if "Hour" in df.columns:
        df = df.set_index("Hour")
    return df


def _hourly_series(path: Path, value_col: str | None = None) -> pd.Series:
    df = _read_hourly_csv(path)
    if value_col is None:
        value_col = df.columns[0]
    s = df[value_col].astype(float)
    s.name = value_col
    return s


def _load_input_csvs(inputs_dir: Path, year: int) -> dict[str, pd.DataFrame | pd.Series]:
    """Load all hourly / parameter input CSVs for the given year."""

    def p(name: str) -> Path:
        return inputs_dir / name

    return {
        "load": _hourly_series(p(f"Load_hourly_{year}.csv")),
        "cf_solar": _read_hourly_csv(p(f"CFSolar_{year}.csv")).astype(float),
        "cf_wind": _read_hourly_csv(p(f"CFWind_{year}.csv")).astype(float),
        "nuclear": _hourly_series(p(f"Nucl_hourly_{year}.csv")),
        "hydro": _hourly_series(p(f"lahy_hourly_{year}.csv")),
        "other_renewables": _hourly_series(p(f"otre_hourly_{year}.csv")),
        "import_cap": _hourly_series(p(f"Import_Cap_{year}.csv")),
        "import_price": _hourly_series(p(f"import_prices_{year}.csv")),
        "export_cap": _hourly_series(p(f"Export_Cap_{year}.csv")),
        "export_price": _hourly_series(p(f"export_prices_{year}.csv")),
        "phi_fix_t": _hourly_series(p("fixed_dem_charges.csv")),
        "phi_var_t": _hourly_series(p("var_dem_charges.csv")),
        "storage_data": pd.read_csv(p(f"StorageData_{year}.csv"), index_col=0),
        "balancing_units": pd.read_csv(p(f"Data_Balancing_units_{year}.csv")),
    }


def _compute_month_of_hour(year: int) -> pd.Series:
    """Return a Series mapping hour-of-year (1..8760) to month (1..12)."""
    idx = pd.date_range(start=f"{year}-01-01", periods=8760, freq="h")
    return pd.Series(idx.month.values, index=range(1, 8761), name="month")


def _build_storage_caps(
    storage_caps_raw: dict[str, dict[str, float]],
    storage_data: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """Combine snapshot capacities with StorageData parameters.

    ``storage_data`` is indexed by parameter name (P_Capex, Eff, FOM, VOM, ...)
    with one column per storage technology.
    """
    out: dict[str, dict[str, float]] = {}
    techs_in_data = list(storage_data.columns)
    for tech in techs_in_data:
        cap = storage_caps_raw.get(tech, {})
        cap_e = float(cap.get("Cap_E", 0.0) or 0.0)
        cap_pch = float(cap.get("Cap_Pch", 0.0) or 0.0)
        cap_pdis = float(cap.get("Cap_Pdis", 0.0) or 0.0)
        if cap_e <= 0.0 and cap_pch <= 0.0 and cap_pdis <= 0.0:
            _warn_zero_capacity(tech, cap_e)
            continue

        # StorageData parameters: ``Eff`` is round-trip-style efficiency in
        # this project; we reuse it for both charge and discharge until a more
        # detailed split is added.
        eff = float(storage_data.at["Eff", tech]) if "Eff" in storage_data.index else 1.0
        vom = float(storage_data.at["VOM", tech]) if "VOM" in storage_data.index else 0.0
        out[tech] = {
            "Cap_Pch": cap_pch,
            "Cap_Pdis": cap_pdis,
            "Cap_E": cap_e,
            "eta_ch": eff,
            "eta_dis": eff,
            "soc_min_frac": 0.0,
            "vom": vom,
        }
    return out


def _build_thermal_caps(
    thermal_caps_raw: dict[str, float],
    balancing_units: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """Aggregate thermal-tech capacity / cost parameters.

    The previous-stage ``Data_Balancing_units_{year}.csv`` lists individual
    plants without a Technology column. We therefore aggregate by mean of
    HeatRate / FuelCost / VOM across all rows (documented behavior).
    """
    out: dict[str, dict[str, float]] = {}
    if balancing_units.empty:
        agg_heat = agg_fuel = agg_vom = 0.0
    else:
        agg_heat = float(balancing_units["HeatRate"].mean()) if "HeatRate" in balancing_units.columns else 0.0
        agg_fuel = float(balancing_units["FuelCost"].mean()) if "FuelCost" in balancing_units.columns else 0.0
        agg_vom = float(balancing_units["VOM"].mean()) if "VOM" in balancing_units.columns else 0.0

    for tech, capacity in thermal_caps_raw.items():
        if not capacity or float(capacity) <= 0.0:
            _warn_zero_capacity(tech, capacity)
            continue
        var_cost = agg_heat * agg_fuel + agg_vom
        out[tech] = {
            "capacity_MW": float(capacity),
            "heat_rate": agg_heat,
            "fuel_cost": agg_fuel,
            "vom": agg_vom,
            "var_cost": var_cost,
        }
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_designed_system(
    snapshot_dir,
    *,
    inputs_dir,
    year=2030,
    scenario_id=1,
    formulation_overrides=None,
):
    """Load a fixed-capacity designed system from SDOM output snapshots.

    Parameters
    ----------
    snapshot_dir : str or pathlib.Path
        Directory containing ``OutputSummary_*`` and ``OutputSelectedVRE_*``
        CSVs from a prior SDOM design run. ``OutputGeneration_*`` and
        ``OutputStorage_*`` files are ignored at this stage; files containing
        ``Phase1`` in their names are also excluded.
    inputs_dir : str or pathlib.Path
        Directory holding the previous-stage time-series and parameter CSVs
        (``Load_hourly_*``, ``CFSolar_*``, ``CFWind_*``,
        ``Data_Balancing_units_*``, ``StorageData_*``, ``Import_Cap_*``,
        ``import_prices_*``, ``Export_Cap_*``, ``export_prices_*``,
        ``fixed_dem_charges.csv``, ``var_dem_charges.csv``).
    year : int, optional
        Calendar year used in CSV filenames. Default ``2030``.
    scenario_id : int, optional
        Scenario / Run id to extract from snapshot CSVs. Default ``1``.
        If a snapshot file contains a single unique scenario, that one is
        used and a warning is emitted when ``scenario_id`` differs.
        If multiple scenarios are present, ``scenario_id`` must match one
        of them; otherwise :class:`ValueError` is raised listing the
        available ids.
    formulation_overrides : dict, optional
        Mapping ``{component: formulation_name}`` overlaid on the default
        formulation map.

    Returns
    -------
    DesignedSystem

    Raises
    ------
    FileNotFoundError
        When the ``OutputSummary_*`` snapshot is missing.
    ValueError
        When ``scenario_id`` cannot be resolved against the snapshot.

    Examples
    --------
    >>> ds = load_designed_system(
    ...     "Data/resiliency_eval/3MW_critical_load_24hrs_outage_24hrs_recovery",
    ...     inputs_dir="Data/resiliency_eval/inputs_previous_stage/Paper_PGnE/Paper",
    ...     year=2030,
    ...     scenario_id=1,
    ... )
    >>> ds.scenario_id
    1
    """
    snapshot_dir = Path(snapshot_dir)
    inputs_dir = Path(inputs_dir)

    summary_path = _find_snapshot_file(snapshot_dir, "OutputSummary", year)
    summary_info = _load_summary_capacities(summary_path, scenario_id)
    resolved_id = summary_info["scenario_id"]

    solar_caps, wind_caps = _load_vre_per_plant(snapshot_dir, resolved_id, year)

    inputs = _load_input_csvs(inputs_dir, year)

    storage_caps = _build_storage_caps(
        summary_info["storage_caps_raw"], inputs["storage_data"]
    )
    thermal_caps = _build_thermal_caps(
        summary_info["thermal_caps_raw"], inputs["balancing_units"]
    )

    formulation_map = dict(_DEFAULT_FORMULATION_MAP)
    if formulation_overrides:
        formulation_map.update(formulation_overrides)

    return DesignedSystem(
        storage_caps=storage_caps,
        thermal_caps=thermal_caps,
        solar_caps=solar_caps,
        wind_caps=wind_caps,
        load=inputs["load"],
        cf_solar=inputs["cf_solar"],
        cf_wind=inputs["cf_wind"],
        nuclear=inputs["nuclear"],
        hydro=inputs["hydro"],
        other_renewables=inputs["other_renewables"],
        import_cap=inputs["import_cap"],
        import_price=inputs["import_price"],
        export_cap=inputs["export_cap"],
        export_price=inputs["export_price"],
        phi_fix_t=inputs["phi_fix_t"],
        phi_var_t=inputs["phi_var_t"],
        month_of_hour=_compute_month_of_hour(year),
        scenario_id=resolved_id,
        year=year,
        formulation_map=formulation_map,
    )
