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
import logging
import math
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from sdom.resiliency.system_state import DesignedSystem


logger = logging.getLogger(__name__)


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
            logger.warning(
                "%s: only scenario_id=%s is present; ignoring user-supplied scenario_id=%s.",
                file_label,
                only,
                scenario_id,
            )
        return df[df[col] == only].copy(), only
    if int(scenario_id) not in unique_ids:
        raise ValueError(
            f"{file_label}: scenario_id={scenario_id} not found. "
            f"Available scenario ids: {unique_ids}."
        )
    return df[df[col] == int(scenario_id)].copy(), int(scenario_id)


def _warn_zero_capacity(tech: str, value: float) -> None:
    logger.warning(
        "Technology '%s' has capacity=%s; excluding from designed system.",
        tech,
        value,
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


def _load_vre_fom(
    inputs_dir: Path,
    year: int,
    solar_plants: set[str],
    wind_plants: set[str],
) -> tuple[dict[str, float], dict[str, float]]:
    """Read CapSolar / CapWind ``FOM_M`` (USD/kW-yr) for the given plants.

    Returns
    -------
    tuple of (dict, dict)
        ``(solar_fom, wind_fom)`` keyed by ``sc_gid`` cast to ``str``.
        Plants not in ``solar_plants`` / ``wind_plants`` are skipped.
        Missing values default to ``0.0`` and emit a debug-level log.
    """

    def _read(filename: str, wanted_ids: set[str]) -> dict[str, float]:
        path = inputs_dir / filename
        if not path.exists():
            logger.warning(
                "%s missing under %s; FOM defaults to 0 for all plants.",
                filename,
                inputs_dir,
            )
            return {pid: 0.0 for pid in wanted_ids}
        df = pd.read_csv(path)
        if "FOM_M" not in df.columns or "sc_gid" not in df.columns:
            logger.warning(
                "%s lacks FOM_M / sc_gid columns; FOM defaults to 0.",
                filename,
            )
            return {pid: 0.0 for pid in wanted_ids}
        idx = df.set_index(df["sc_gid"].astype(str))["FOM_M"].astype(float).to_dict()
        return {pid: float(idx.get(pid, 0.0)) for pid in wanted_ids}

    solar_fom = _read(f"CapSolar_{year}.csv", solar_plants)
    wind_fom = _read(f"CapWind_{year}.csv", wind_plants)
    return solar_fom, wind_fom


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
    sel_col = "Selection"

    solar_caps: dict[str, float] = {}
    wind_caps: dict[str, float] = {}
    for _, row in df.iterrows():
        plant_id = str(row[id_col]).strip()
        selection = float(row[sel_col]) if sel_col in df.columns else 1.0
        if selection <= 0.0:
            continue
        capacity = float(row[cap_col]) * selection
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

        # ``Eff`` in StorageData is round-trip efficiency (matches planning
        # model in formulations_storage.py which uses sqrt(Eff) one-way).
        eff = float(storage_data.at["Eff", tech]) if "Eff" in storage_data.index else 1.0
        vom = float(storage_data.at["VOM", tech]) if "VOM" in storage_data.index else 0.0
        # FOM ($/kW-yr) split between charge and discharge sides by CostRatio,
        # mirroring sdom.models.formulations_storage.storage_fixed_om_cost_expr_rule.
        # CEM default cost_ratio = 0.5 when missing.
        fom = float(storage_data.at["FOM", tech]) if "FOM" in storage_data.index else 0.0
        cost_ratio = (
            float(storage_data.at["CostRatio", tech])
            if "CostRatio" in storage_data.index
            else 0.5
        )
        eta_one_way = math.sqrt(max(eff, 0.0)) if eff > 0.0 else 1.0
        out[tech] = {
            "Cap_Pch": cap_pch,
            "Cap_Pdis": cap_pdis,
            "Cap_E": cap_e,
            "eta_ch": eta_one_way,
            "eta_dis": eta_one_way,
            "soc_min_frac": 0.0,
            "vom": vom,
            "fom": fom,
            "cost_ratio": cost_ratio,
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
        agg_heat = agg_fuel = agg_vom = agg_fom = 0.0
    else:
        agg_heat = float(balancing_units["HeatRate"].mean()) if "HeatRate" in balancing_units.columns else 0.0
        agg_fuel = float(balancing_units["FuelCost"].mean()) if "FuelCost" in balancing_units.columns else 0.0
        agg_vom = float(balancing_units["VOM"].mean()) if "VOM" in balancing_units.columns else 0.0
        agg_fom = float(balancing_units["FOM"].mean()) if "FOM" in balancing_units.columns else 0.0

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
            "fom": agg_fom,
        }
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Default formulations.csv content used when an inputs directory shipped from a
# legacy CEM run does not include a ``formulations.csv``. These values match
# what the CEM uses for the resiliency-evaluation dispatch (linear LP, no
# net-load coupling on imports/exports, run-of-river hydro).
_DEFAULT_CEM_FORMULATIONS_ROWS = [
    ("Thermal", "NoRampsDispatchFormulation", "Auto-injected by resiliency loader."),
    ("Hydro", "RunOfRiverFormulation", "Auto-injected by resiliency loader."),
    ("Imports", "CapacityPriceNetLoadFormulation", "Auto-injected by resiliency loader."),
    ("Exports", "CapacityPriceNetLoadFormulation", "Auto-injected by resiliency loader."),
]


def load_cem_data(inputs_dir, *, formulations_overrides=None):
    """Load the CEM-shaped data dict for the resiliency baseline dispatch.

    Wraps :func:`sdom.io_manager.load_data` so it can consume the
    previous-stage inputs directory used by the resiliency module. The
    directory typically lacks ``formulations.csv``; when missing, a minimal
    default is materialized in a temporary copy of ``inputs_dir`` (the
    original directory is never modified).

    Parameters
    ----------
    inputs_dir : str or pathlib.Path
        Directory containing the original CEM input CSVs.
    formulations_overrides : list of tuple, optional
        Sequence of ``(component, formulation, description)`` rows used to
        override / extend the default ``formulations.csv`` shim. Has no
        effect when ``formulations.csv`` already exists in ``inputs_dir``.

    Returns
    -------
    dict
        Data dictionary as returned by :func:`sdom.io_manager.load_data`.

    Raises
    ------
    FileNotFoundError
        If ``inputs_dir`` does not exist or is missing CSVs required by
        :func:`sdom.io_manager.load_data`.
    """
    from sdom.io_manager import load_data  # local import to avoid a cycle

    inputs_dir = Path(inputs_dir)
    if not inputs_dir.is_dir():
        raise FileNotFoundError(f"CEM inputs directory does not exist: {inputs_dir}")

    has_formulations = any(
        inputs_dir.glob("[Ff]ormulations*.csv")
    )
    if has_formulations:
        logger.debug("Found existing formulations.csv in %s; using as-is.", inputs_dir)
        return load_data(str(inputs_dir))

    # The CEM ``load_data`` requires a ``formulations.csv``. Materialize a
    # temporary mirror of ``inputs_dir`` so we never touch the user's source
    # tree, then write a default formulations.csv into the copy. The mirror is
    # only needed while ``load_data`` runs; clean it up afterwards so repeated
    # calls (e.g. in test suites) don't leak temp directories.
    rows = list(_DEFAULT_CEM_FORMULATIONS_ROWS)
    if formulations_overrides:
        rows.extend(formulations_overrides)
    with tempfile.TemporaryDirectory(prefix="sdom_cem_inputs_") as tmp_root_str:
        tmp_root = Path(tmp_root_str)
        tmp_inputs = tmp_root / inputs_dir.name
        logger.info(
            "Mirroring CEM inputs to %s and injecting default formulations.csv "
            "(original directory %s left untouched).",
            tmp_inputs,
            inputs_dir,
        )
        shutil.copytree(inputs_dir, tmp_inputs)
        formulations_df = pd.DataFrame(
            rows, columns=["Component", "Formulation", "Description"]
        )
        formulations_df.to_csv(tmp_inputs / "formulations.csv", index=False)
        _augment_storage_data(tmp_inputs)
        _augment_scalars(tmp_inputs)
        data = load_data(str(tmp_inputs))
    _coerce_plant_id_to_string(data)
    return data


def _augment_storage_data(inputs_dir: Path) -> None:
    """Inject required ``Coupled`` / ``MaxCycles`` rows into StorageData if absent.

    Older CEM input folders ship a ``StorageData_*.csv`` that omits the
    ``Coupled`` and ``MaxCycles`` rows required by the current
    :mod:`sdom.models.formulations_storage`. We patch the temporary mirror
    using ``Set_b(j)_CoupledStorageTech.csv`` (when present) for the coupled
    flags and a permissive ``MaxCycles=100000`` default (effectively unbounded
    for an annual dispatch).
    """
    storage_files = list(inputs_dir.glob("StorageData*.csv"))
    if not storage_files:
        return
    storage_path = storage_files[0]
    df = pd.read_csv(storage_path, index_col=0)
    changed = False
    if "Coupled" not in df.index:
        coupled_techs: set[str] = set()
        coupled_files = list(inputs_dir.glob("Set_b*Coupled*.csv"))
        if coupled_files:
            try:
                coupled_techs = set(
                    pd.read_csv(coupled_files[0], header=None)[0].astype(str).tolist()
                )
            except Exception:
                coupled_techs = set()
        df.loc["Coupled"] = [1 if str(c) in coupled_techs else 0 for c in df.columns]
        changed = True
        logger.info(
            "Injected 'Coupled' row into StorageData (coupled techs: %s).",
            sorted(coupled_techs) or "[]",
        )
    if "MaxCycles" not in df.index:
        df.loc["MaxCycles"] = [100000.0] * len(df.columns)
        changed = True
        logger.info("Injected 'MaxCycles' row into StorageData (default=100000).")
    if changed:
        df.to_csv(storage_path)


def _augment_scalars(inputs_dir: Path) -> None:
    """Normalize ``Scalars.csv`` to the schema expected by :func:`load_data`.

    Older inputs use ``ScalarInputs`` as the parameter column; the current
    loader expects ``Parameter``. Also injects ``EUE_max=0`` when absent so
    system constraints can build without modification.
    """
    candidates = list(inputs_dir.glob("[Ss]calars*.csv"))
    if not candidates:
        return
    path = candidates[0]
    df = pd.read_csv(path)
    changed = False
    if "Parameter" not in df.columns:
        for alt in ("ScalarInputs", "Scalar", "scalar", "scalarinputs"):
            if alt in df.columns:
                df = df.rename(columns={alt: "Parameter"})
                changed = True
                logger.info("Renamed scalar column '%s' -> 'Parameter'.", alt)
                break
    if "Parameter" in df.columns and "EUE_max" not in set(df["Parameter"].astype(str)):
        df = pd.concat(
            [df, pd.DataFrame([{"Parameter": "EUE_max", "Value": 0.0}])],
            ignore_index=True,
        )
        changed = True
        logger.info("Injected scalar 'EUE_max=0'.")
    if changed:
        df.to_csv(path, index=False)


def _augment_thermal_data(inputs_dir: Path) -> None:
    """Force ``Plant_id`` to string in legacy ``Data_BalancingUnits*.csv`` files.

    The CEM thermal parameter loader builds a Pyomo set from
    ``Plant_id.astype(str)`` but then keys a stacked-dict lookup off the raw
    column values. When ``Plant_id`` is integer-typed (as in older paper
    datasets), the two key spaces disagree and parameter assembly raises
    ``KeyError``. Casting the column to string in the temp mirror keeps the
    legacy data compatible without touching the user's source folder.
    """
    candidates = list(inputs_dir.glob("Data_*[Bb]alancing*nits*.csv"))
    if not candidates:
        return
    for path in candidates:
        df = pd.read_csv(path)
        if "Plant_id" not in df.columns:
            continue
        if df["Plant_id"].dtype == object:
            continue
        df["Plant_id"] = df["Plant_id"].astype(str)
        df.to_csv(path, index=False)
        logger.info("Cast Plant_id to string in %s.", path.name)


def _coerce_plant_id_to_string(data: dict) -> None:
    """Ensure ``data['thermal_data']['Plant_id']`` is string-typed.

    The CEM thermal parameter loader (
    :func:`sdom.models.formulations_thermal.add_thermal_parameters`) builds
    its Pyomo set from ``Plant_id.astype(str)`` but indexes the stacked
    parameter dict with the raw column values, so integer ``Plant_id``
    columns (as in older paper datasets) raise ``KeyError`` during model
    construction. This in-memory cast keeps the user's source folder
    untouched while making legacy CSVs work.
    """
    td = data.get("thermal_data")
    if td is None or "Plant_id" not in td.columns:
        return
    if td["Plant_id"].dtype != object:
        td["Plant_id"] = td["Plant_id"].astype(str)


def load_designed_system(
    snapshot_dir,
    *,
    inputs_dir,
    year=2030,
    scenario_id=1,
    formulation_overrides=None,
    attach_cem_data=True,
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
    attach_cem_data : bool, optional
        When ``True`` (default), also load the CEM-shaped data dict via
        :func:`load_cem_data` and attach it as
        ``DesignedSystem.cem_data``. Required by
        :func:`sdom.resiliency.build_baseline_dispatch`. Set to ``False`` to
        skip this step in environments where the previous-stage inputs
        directory is not a valid CEM inputs folder.

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
    logger.info(
        "Loading designed system: snapshot_dir=%s, inputs_dir=%s, year=%s, scenario_id=%s.",
        snapshot_dir,
        inputs_dir,
        year,
        scenario_id,
    )

    logger.debug("Locating OutputSummary snapshot for year=%s.", year)
    summary_path = _find_snapshot_file(snapshot_dir, "OutputSummary", year)
    logger.debug("Reading summary capacities from %s.", summary_path.name)
    summary_info = _load_summary_capacities(summary_path, scenario_id)
    resolved_id = summary_info["scenario_id"]
    logger.debug("Resolved scenario_id=%s.", resolved_id)

    logger.debug("Loading per-plant VRE selections from snapshot.")
    solar_caps, wind_caps = _load_vre_per_plant(snapshot_dir, resolved_id, year)
    logger.debug(
        "Per-plant VRE counts: solar=%d, wind=%d.", len(solar_caps), len(wind_caps)
    )

    logger.debug("Loading VRE FOM_M from CapSolar/CapWind input CSVs.")
    solar_fom, wind_fom = _load_vre_fom(
        inputs_dir, year, set(solar_caps.keys()), set(wind_caps.keys())
    )

    logger.debug("Loading previous-stage input CSVs from %s.", inputs_dir)
    inputs = _load_input_csvs(inputs_dir, year)

    logger.debug("Combining snapshot capacities with StorageData parameters.")
    storage_caps = _build_storage_caps(
        summary_info["storage_caps_raw"], inputs["storage_data"]
    )
    logger.debug("Aggregating thermal-tech capacity / cost parameters.")
    thermal_caps = _build_thermal_caps(
        summary_info["thermal_caps_raw"], inputs["balancing_units"]
    )

    formulation_map = dict(_DEFAULT_FORMULATION_MAP)
    if formulation_overrides:
        logger.debug("Applying formulation overrides: %s.", formulation_overrides)
        formulation_map.update(formulation_overrides)

    logger.info(
        "Designed system loaded: storage=%d, thermal=%d, solar plants=%d, wind plants=%d.",
        len(storage_caps),
        len(thermal_caps),
        len(solar_caps),
        len(wind_caps),
    )

    cem_data = None
    if attach_cem_data:
        logger.debug("Loading CEM-shaped data dict from %s.", inputs_dir)
        try:
            cem_data = load_cem_data(inputs_dir)
        except Exception as exc:
            logger.error(
                "Failed to load CEM data dict from %s: %s. "
                "Re-raising; build_baseline_dispatch requires cem_data and "
                "would otherwise fail with an unhelpful error downstream. "
                "Pass attach_cem_data=False to skip this step when the "
                "inputs directory is not a valid CEM inputs folder.",
                inputs_dir,
                exc,
            )
            raise

    return DesignedSystem(
        storage_caps=storage_caps,
        thermal_caps=thermal_caps,
        solar_caps=solar_caps,
        wind_caps=wind_caps,
        solar_fom=solar_fom,
        wind_fom=wind_fom,
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
        cem_data=cem_data,
    )
