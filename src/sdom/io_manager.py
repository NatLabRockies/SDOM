import logging
import re
import pandas as pd
import os
import csv

from pyomo.environ import sqrt

from .common.utilities import safe_pyomo_value, check_file_exists, compare_lists, concatenate_dataframes, get_dict_string_void_list_from_keys_in_list, get_complete_path
from .constants import (
    INPUT_CSV_NAMES,
    MW_TO_KW,
    VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP,
    VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP,
    VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP,
    DEFAULT_NETWORK_FORMULATION,
    DEFAULT_AREA_ID,
    AREA_TAG_DELIMITER,
    COPPER_PLATE_NETWORK,
    AREA_TRANSPORTATION_MODEL_NETWORK,
    AREA_TRANSPORTATION_MODEL_NETWORK_REQUIRED_INPUTS,
    RUN_OF_RIVER_FORMULATION,
    IMPORTS_EXPORTS_CAPACITY_PRICE_NET_LOAD,
)

# Compiled once: matches "<entity>@<area_id>@" with no extra '@' characters.
_AREA_TAG_RE = re.compile(
    rf"^(?P<entity>[^{re.escape(AREA_TAG_DELIMITER)}]*)"
    rf"{re.escape(AREA_TAG_DELIMITER)}"
    rf"(?P<area>[^{re.escape(AREA_TAG_DELIMITER)}]+)"
    rf"{re.escape(AREA_TAG_DELIMITER)}$"
)

# Sentinel used to distinguish 'no default supplied' from 'default is None'.
_GET_FORMULATION_NO_DEFAULT = object()


def check_formulation( formulation:str, valid_formulations ):
    """Validate that a formulation string is in the list of valid formulations.
    
    Checks if the user-specified formulation (from formulations.csv) is valid for
    the component being configured. Raises an error with helpful message if invalid.
    
    Args:
        formulation (str): The formulation name specified by user (e.g.,
            'MonthlyBudgetFormulation', 'RunOfRiverFormulation').
        valid_formulations: Iterable (typically dict.keys()) containing all valid
            formulation names for the component.
    
    Returns:
        None
    
    Raises:
        ValueError: If formulation is not in valid_formulations, with a message
            listing all valid options.
    
    Notes:
        This function is called during data loading to validate formulation.csv entries.
    """
    
    if formulation not in valid_formulations:
        raise ValueError(f"Invalid formulation '{formulation}' selected by the user in file 'formulations.csv'. Valid options are: {valid_formulations}")
    return

def get_formulation(data: dict, component: str = 'hydro', *, default=_GET_FORMULATION_NO_DEFAULT):
    """Retrieve the selected formulation for a specific model component.

    Extracts the formulation name from the loaded formulations DataFrame for a
    given component (e.g., hydro, imports, exports, network). Used throughout
    model initialization to conditionally add constraints based on formulation.

    Parameters
    ----------
    data : dict
        Dictionary containing the 'formulations' DataFrame loaded from
        ``formulations.csv``.
    component : str, optional
        Component name to look up (case-insensitive). Examples: ``'hydro'``,
        ``'Imports'``, ``'Exports'``, ``'Network'``. Defaults to ``'hydro'``.
    default : str, optional
        Value returned (and logged at INFO level) when the requested component
        row is absent from ``formulations.csv``. If omitted, a missing row
        raises ``IndexError`` (preserves the legacy behaviour).

    Returns
    -------
    str
        The formulation name for the specified component.

    Notes
    -----
    - Performs case-insensitive matching on component name.
    - Returns the first matching formulation (expects unique component names).
    - The ``default`` keyword is keyword-only to keep the function's mandatory
      positional surface unchanged.
    """
    formulations = data["formulations"]
    matches = formulations.loc[
        formulations["Component"].str.lower() == component.lower()
    ]["Formulation"]
    if matches.empty:
        if default is _GET_FORMULATION_NO_DEFAULT:
            return matches.iloc[0]  # original IndexError surface
        logging.info(
            "Component '%s' not present in formulations.csv. Falling back to default '%s'.",
            component,
            default,
        )
        return default
    return matches.iloc[0]


def get_network_formulation(data: dict) -> str:
    """Return the active Network formulation for a loaded data dict.

    Thin accessor on top of :func:`get_formulation` that hides the storage
    detail of how the Network row is exposed in ``data``. Production code
    (and downstream callers) should use this helper instead of indexing
    ``data`` directly so the underlying representation can evolve without
    breaking consumers.

    Parameters
    ----------
    data : dict
        Data dictionary as returned by :func:`load_data` (or any partial
        dict that already contains the ``"formulations"`` DataFrame).

    Returns
    -------
    str
        One of the keys of
        :data:`~sdom.constants.VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP`,
        defaulting to :data:`~sdom.constants.DEFAULT_NETWORK_FORMULATION`
        when the ``Network`` row is absent.
    """
    return get_formulation(
        data, component="Network", default=DEFAULT_NETWORK_FORMULATION
    )


# ---------------------------------------------------------------------------------
# Per-area (zonal) parsing helpers
# ---------------------------------------------------------------------------------


def _parse_area_tagged_header(header):
    """Parse a wide-CSV column header for an ``@area_id@`` tag.

    The hybrid encoding for zonal data tags wide-CSV column names with
    ``<entity><AREA_TAG_DELIMITER><area_id><AREA_TAG_DELIMITER>``. Legacy
    column names without the delimiter are accepted and reported with
    ``area_id == None`` so the caller can decide whether to assign
    ``DEFAULT_AREA_ID`` (legacy file) or raise (mixed legacy + tagged).

    Parameters
    ----------
    header : str
        Column header to parse.

    Returns
    -------
    tuple[str, str | None]
        ``(entity_name, area_id)`` where ``area_id`` is ``None`` when the
        header contains no delimiter.

    Raises
    ------
    ValueError
        If the delimiter appears in the header but the overall shape is not
        ``<entity>@<area_id>@`` (stray ``@``, double tag, lone delimiter).
    """
    header = str(header)
    if AREA_TAG_DELIMITER not in header:
        return header, None
    match = _AREA_TAG_RE.match(header)
    if match is None:
        raise ValueError(
            f"Invalid area tag in column header '{header}'. Expected format "
            f"'<entity>{AREA_TAG_DELIMITER}<area_id>{AREA_TAG_DELIMITER}'."
        )
    return match.group("entity"), match.group("area")


def _split_wide_by_area(df, *, file_label):
    """Split a wide-format DataFrame into per-area DataFrames using header tags.

    The first column is treated as the time / property key and is preserved
    in every per-area slice. All non-key columns must be either fully
    untagged (legacy file → single ``DEFAULT_AREA_ID`` slice) or fully tagged
    with ``@area_id@`` (zonal file → one slice per observed area).

    Parameters
    ----------
    df : pandas.DataFrame or None
        Source DataFrame. ``None`` or empty returns ``({}, set())``.
    file_label : str
        Human-readable file identifier used in error messages.

    Returns
    -------
    tuple[dict[str, pandas.DataFrame], set[str]]
        ``(per_area, observed_areas)``. ``per_area`` maps ``area_id`` to a
        DataFrame containing the key column and the columns belonging to
        that area, with the ``@area_id@`` tag stripped from headers.
        ``observed_areas`` is the set of explicitly tagged area ids (empty
        for fully untagged legacy files).

    Raises
    ------
    ValueError
        If the file mixes untagged and tagged non-key columns, or any tagged
        column header has an invalid shape.
    """
    if df is None or df.empty:
        return {}, set()

    key_col = df.columns[0]
    parsed = []
    untagged = 0
    tagged = 0
    for col in df.columns[1:]:
        entity, area = _parse_area_tagged_header(col)
        if area is None:
            untagged += 1
        else:
            tagged += 1
        parsed.append((col, entity, area))

    if untagged and tagged:
        raise ValueError(
            f"{file_label} mixes legacy (untagged) and {AREA_TAG_DELIMITER}area_id"
            f"{AREA_TAG_DELIMITER}-tagged columns. All non-key columns must be "
            f"either all untagged or all tagged."
        )

    if tagged == 0:
        return {DEFAULT_AREA_ID: df.copy()}, set()

    # Group source columns by area, then build per-area DataFrames in one
    # shot (avoids pandas PerformanceWarning on fragmented frames).
    grouped: dict[str, list[tuple[str, str]]] = {}
    observed: set[str] = set()
    for orig, entity, area in parsed:
        observed.add(area)
        grouped.setdefault(area, []).append((orig, entity))

    per_area: dict[str, pd.DataFrame] = {}
    for area, items in grouped.items():
        sources = [orig for orig, _ in items]
        renames = {orig: entity for orig, entity in items}
        per_area[area] = df[[key_col, *sources]].rename(columns=renames).copy()
    return per_area, observed


def _split_row_by_area(df, *, id_col, file_label):
    """Split a row-oriented DataFrame by an optional ``area_id`` column.

    Files such as ``CapSolar.csv`` / ``CapWind.csv`` use Encoding A: an
    optional ``area_id`` column tags every row. Plant identifiers (``id_col``)
    must be globally unique across areas. Legacy files (no ``area_id`` column)
    are returned as a single ``DEFAULT_AREA_ID`` slice.

    Parameters
    ----------
    df : pandas.DataFrame or None
        Source DataFrame. ``None`` or empty returns ``({}, set())``.
    id_col : str
        Name of the globally unique row identifier (e.g. ``"sc_gid"``).
    file_label : str
        Human-readable file identifier used in error messages.

    Returns
    -------
    tuple[dict[str, pandas.DataFrame], set[str]]
        ``(per_area, observed_areas)``.

    Raises
    ------
    ValueError
        If duplicate ``id_col`` values appear across all areas.
    """
    if df is None or df.empty:
        return {}, set()

    if "area_id" not in df.columns:
        return {DEFAULT_AREA_ID: df.copy()}, set()

    if id_col in df.columns and df[id_col].duplicated().any():
        dups = (
            df.loc[df[id_col].duplicated(keep=False), id_col]
            .astype(str)
            .unique()
            .tolist()
        )
        raise ValueError(
            f"{file_label}: '{id_col}' values must be globally unique across "
            f"areas; duplicates found: {dups}."
        )

    per_area: dict[str, pd.DataFrame] = {}
    observed: set[str] = set()
    for area, sub in df.groupby("area_id", sort=False):
        area_str = str(area)
        observed.add(area_str)
        per_area[area_str] = sub.copy()
    return per_area, observed


def _split_cf_by_plant_area(cf_df, cap_per_area, *, id_col):
    """Group capacity-factor columns by area via the cap-table plant→area map.

    ``CFSolar.csv`` / ``CFWind.csv`` keep a single column per plant
    identifier (already globally unique). The plant→area mapping is recovered
    from ``CapSolar.csv`` / ``CapWind.csv`` (already split per area).

    Parameters
    ----------
    cf_df : pandas.DataFrame or None
        Wide capacity-factor DataFrame; first column is the time key and
        every other column header is a plant id.
    cap_per_area : dict[str, pandas.DataFrame]
        Per-area capacity tables keyed by ``area_id``.
    id_col : str
        Plant-id column name in the cap tables (e.g. ``"sc_gid"``).

    Returns
    -------
    dict[str, pandas.DataFrame]
        Per-area capacity-factor DataFrames; columns are the time key plus
        the plant ids assigned to that area.
    """
    if cf_df is None or cf_df.empty:
        return {}

    key_col = cf_df.columns[0]
    plant_to_area: dict[str, str] = {}
    for area, sub in cap_per_area.items():
        if id_col not in sub.columns:
            continue
        for plant_id in sub[id_col].astype(str):
            plant_to_area[plant_id] = area

    # Group columns by area first, then assemble each per-area DataFrame in
    # one go (avoids pandas PerformanceWarning about fragmented frames).
    cols_by_area: dict[str, list[str]] = {}
    for col in cf_df.columns[1:]:
        area = plant_to_area.get(str(col), DEFAULT_AREA_ID)
        cols_by_area.setdefault(area, []).append(col)

    per_area: dict[str, pd.DataFrame] = {}
    for area, cols in cols_by_area.items():
        per_area[area] = cf_df[[key_col, *cols]].copy()
    return per_area


def _combine_per_area_imp_exp(cap_per_area, price_per_area):
    """Merge per-area capacity and price DataFrames (imports or exports).

    Parameters
    ----------
    cap_per_area : dict[str, pandas.DataFrame]
        Per-area capacity tables (first column is the time key).
    price_per_area : dict[str, pandas.DataFrame]
        Per-area price tables (first column is the time key).

    Returns
    -------
    dict[str, pandas.DataFrame]
        Per-area DataFrames containing the time key plus ``cap`` / ``price``
        columns merged on the time key.
    """
    per_area: dict[str, pd.DataFrame] = {}
    for area in set(cap_per_area) | set(price_per_area):
        cap = cap_per_area.get(area)
        price = price_per_area.get(area)
        if cap is not None and price is not None:
            key_col = cap.columns[0]
            per_area[area] = cap.merge(price, on=key_col, how="outer")
        else:
            per_area[area] = (cap if cap is not None else price).copy()
    return per_area


def _load_areas(input_data_dir):
    """Load ``areas.csv`` if present, otherwise synthesize the default area.

    Parameters
    ----------
    input_data_dir : str
        Path to the SDOM input data folder.

    Returns
    -------
    tuple[list[dict], bool]
        ``(areas, present_on_disk)``. ``areas`` is a list of
        ``{"area_id": str, "description": str}`` dicts (always at least one
        entry). ``present_on_disk`` is ``True`` when ``areas.csv`` was found.

    Raises
    ------
    ValueError
        If ``areas.csv`` is present but missing the required ``area_id``
        column.
    """
    path = get_complete_path(input_data_dir, INPUT_CSV_NAMES["areas"])
    if path:
        df = pd.read_csv(path)
        if "area_id" not in df.columns:
            raise ValueError("areas.csv must include an 'area_id' column.")
        if "description" not in df.columns:
            df["description"] = ""
        df = df.copy()
        df["area_id"] = df["area_id"].astype(str)
        df["description"] = df["description"].fillna("").astype(str)
        return df[["area_id", "description"]].to_dict(orient="records"), True

    return (
        [{"area_id": DEFAULT_AREA_ID, "description": "Default area"}],
        False,
    )


def _validate_observed_areas(observed, *, areas, areas_csv_present, source_label):
    """Validate that observed area_ids reference declared areas.

    When ``areas.csv`` is present, every observed area must appear in
    ``areas`` (ERROR otherwise). When ``areas.csv`` is absent, any observed
    area is accepted (the caller will synthesize the area set).

    Parameters
    ----------
    observed : set[str]
        Area ids harvested from the per-device parser.
    areas : list[dict]
        Currently-known area list.
    areas_csv_present : bool
        Whether ``areas.csv`` was loaded from disk.
    source_label : str
        Human-readable identifier of the file that produced ``observed``,
        used in error messages.

    Raises
    ------
    ValueError
        If ``areas.csv`` is present and ``observed`` references an unknown
        ``area_id``.
    """
    if not observed or not areas_csv_present:
        return
    declared = {a["area_id"] for a in areas}
    unknown = sorted(observed - declared)
    if unknown:
        raise ValueError(
            f"{source_label}: references unknown area_id(s) {unknown} not "
            f"declared in areas.csv (declared: {sorted(declared)})."
        )


def _augment_with_per_area_views(data, *, input_data_dir):
    """Populate ``per_area_*`` views and validate the area encoding.

    Post-processing step run after the legacy global keys have been loaded
    into ``data``. Legacy single-area folders end up with all per-area dicts
    keyed by ``DEFAULT_AREA_ID`` and the existing global keys untouched.

    Parameters
    ----------
    data : dict
        The data dictionary returned by ``load_data`` so far.
    input_data_dir : str
        Path to the SDOM input data folder (used to locate ``areas.csv``).

    Returns
    -------
    dict
        The same ``data`` dict, mutated in place, with the new keys
        documented in PRD §4.4 (``areas``, ``per_area_demand``,
        ``per_area_pv_plants``, etc.).

    Raises
    ------
    ValueError
        On any of the validation rules in PRD §4.5 (mixed columns, stray
        ``@``, unknown area references, duplicate plant ids, …).
    """
    areas, areas_present = _load_areas(input_data_dir)

    wide_specs = [
        ("load_data", "Load_hourly.csv"),
        ("nuclear_data", "Nucl_hourly.csv"),
        ("large_hydro_data", "lahy_hourly.csv"),
        ("large_hydro_max", "lahy_max_hourly.csv"),
        ("large_hydro_min", "lahy_min_hourly.csv"),
        ("other_renewables_data", "otre_hourly.csv"),
        ("cap_imports", "Import_Cap.csv"),
        ("price_imports", "Import_Prices.csv"),
        ("cap_exports", "Export_Cap.csv"),
        ("price_exports", "Export_Prices.csv"),
    ]
    splits: dict[str, dict[str, pd.DataFrame]] = {}
    observed_total: set[str] = set()
    for key, label in wide_specs:
        per_area, observed = _split_wide_by_area(data.get(key), file_label=label)
        _validate_observed_areas(
            observed,
            areas=areas,
            areas_csv_present=areas_present,
            source_label=label,
        )
        splits[key] = per_area
        observed_total |= observed

    # StorageData.csv is read with index_col=0; rebuild the wide form for parsing.
    storage_df = data.get("storage_data")
    if storage_df is not None and not storage_df.empty:
        index_label = storage_df.index.name or "Property"
        storage_wide = storage_df.reset_index().rename(
            columns={storage_df.index.name or "index": index_label}
        )
        per_area_storage_wide, observed_storage = _split_wide_by_area(
            storage_wide, file_label="StorageData.csv"
        )
        _validate_observed_areas(
            observed_storage,
            areas=areas,
            areas_csv_present=areas_present,
            source_label="StorageData.csv",
        )
        per_area_storage = {
            area: sub.set_index(sub.columns[0])
            for area, sub in per_area_storage_wide.items()
        }
    else:
        per_area_storage, observed_storage = {}, set()
    observed_total |= observed_storage

    # Data_BalancingUnits.csv is currently row-oriented (Plant_id, MaxCapacity, ...).
    # Treat it as Encoding A (optional area_id column) for backward compatibility
    # with the existing fixtures; the PRD's wide-form example is aspirational and
    # will be revisited when the long-format migration lands.
    per_area_balancing_units, observed_bu = _split_row_by_area(
        data.get("thermal_data"), id_col="Plant_id", file_label="Data_BalancingUnits.csv"
    )
    _validate_observed_areas(
        observed_bu,
        areas=areas,
        areas_csv_present=areas_present,
        source_label="Data_BalancingUnits.csv",
    )
    observed_total |= observed_bu

    per_area_pv_plants, observed_pv = _split_row_by_area(
        data.get("cap_solar"), id_col="sc_gid", file_label="CapSolar.csv"
    )
    _validate_observed_areas(
        observed_pv,
        areas=areas,
        areas_csv_present=areas_present,
        source_label="CapSolar.csv",
    )
    observed_total |= observed_pv

    per_area_wind_plants, observed_wind = _split_row_by_area(
        data.get("cap_wind"), id_col="sc_gid", file_label="CapWind.csv"
    )
    _validate_observed_areas(
        observed_wind,
        areas=areas,
        areas_csv_present=areas_present,
        source_label="CapWind.csv",
    )
    observed_total |= observed_wind

    per_area_cf_pv = _split_cf_by_plant_area(
        data.get("cf_solar"), per_area_pv_plants, id_col="sc_gid"
    )
    per_area_cf_wind = _split_cf_by_plant_area(
        data.get("cf_wind"), per_area_wind_plants, id_col="sc_gid"
    )

    per_area_imports = _combine_per_area_imp_exp(
        splits["cap_imports"], splits["price_imports"]
    )
    per_area_exports = _combine_per_area_imp_exp(
        splits["cap_exports"], splits["price_exports"]
    )

    # Hydro composite per area: merge run-of-river / max / min on the time key.
    hydro_components = {
        "LargeHydro": splits["large_hydro_data"],
        "LargeHydro_Max": splits.get("large_hydro_max", {}),
        "LargeHydro_Min": splits.get("large_hydro_min", {}),
    }
    per_area_hydro: dict[str, pd.DataFrame] = {}
    for label, src in hydro_components.items():
        for area, sub in src.items():
            if sub is None or sub.empty:
                continue
            key_col = sub.columns[0]
            value_cols = [c for c in sub.columns if c != key_col]
            renamed = sub.rename(
                columns={
                    c: (label if len(value_cols) == 1 else f"{label}__{c}")
                    for c in value_cols
                }
            )
            if area not in per_area_hydro:
                per_area_hydro[area] = renamed
            else:
                per_area_hydro[area] = per_area_hydro[area].merge(
                    renamed, on=key_col, how="outer"
                )

    # Synthesize areas from observed tags when areas.csv was absent.
    if not areas_present and observed_total:
        areas = [
            {"area_id": area, "description": f"Area {area}"}
            for area in sorted(observed_total)
        ]

    data["areas"] = areas
    data["per_area_demand"] = splits["load_data"]
    data["per_area_pv_plants"] = per_area_pv_plants
    data["per_area_wind_plants"] = per_area_wind_plants
    data["per_area_balancing_units"] = per_area_balancing_units
    data["per_area_storage"] = per_area_storage
    data["per_area_hydro"] = per_area_hydro
    data["per_area_nuclear"] = splits["nuclear_data"]
    data["per_area_other_renewables"] = splits["other_renewables_data"]
    data["per_area_imports"] = per_area_imports
    data["per_area_exports"] = per_area_exports
    data["per_area_capacity_factors_pv"] = per_area_cf_pv
    data["per_area_capacity_factors_wind"] = per_area_cf_wind
    return data


# ---------------------------------------------------------------------------------
# Zonal topology (commit #5): interconnections + per-line hourly capacities
# ---------------------------------------------------------------------------------


def _load_interconnections(input_data_dir, *, areas):
    """Load the inter-area transmission topology from ``interconnections.csv``.

    Reads the line definitions used by the
    ``AreaTransportationModelNetwork`` formulation. The file is optional;
    when absent an empty list is returned so legacy and copper-plate
    fixtures continue to load. When present, it is fully validated.

    Parameters
    ----------
    input_data_dir : str
        Path to the SDOM input data folder.
    areas : list of dict
        Declared areas as returned by ``_load_areas``. Used as the
        foreign-key target for ``from_area`` / ``to_area``.

    Returns
    -------
    list of dict
        One ``{"line_id": str, "from_area": str, "to_area": str}`` per row,
        preserving the file order. Returns ``[]`` when the file is absent
        or empty.

    Raises
    ------
    ValueError
        If required columns are missing, ``line_id`` or
        ``(from_area, to_area)`` pairs are duplicated, a self-loop is
        declared, or an area reference does not exist in ``areas``.
    """
    path = get_complete_path(input_data_dir, INPUT_CSV_NAMES["interconnections"])
    if not path:
        return []

    df = pd.read_csv(path)
    required = {"line_id", "from_area", "to_area"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"interconnections.csv is missing required column(s): "
            f"{sorted(missing)}."
        )

    if df.empty:
        return []

    df = df.copy()
    for col in ("line_id", "from_area", "to_area"):
        df[col] = df[col].astype(str)

    # Duplicate line_id ----------------------------------------------------
    dup_ids = df.loc[df["line_id"].duplicated(keep=False), "line_id"].unique().tolist()
    if dup_ids:
        raise ValueError(
            f"interconnections.csv: duplicate line_id value(s) {sorted(dup_ids)}."
        )

    # Duplicate (from_area, to_area) pairs ---------------------------------
    pair_dup_mask = df.duplicated(subset=["from_area", "to_area"], keep=False)
    if pair_dup_mask.any():
        dup_pairs = (
            df.loc[pair_dup_mask, ["from_area", "to_area"]]
            .drop_duplicates()
            .apply(lambda r: (r["from_area"], r["to_area"]), axis=1)
            .tolist()
        )
        raise ValueError(
            f"interconnections.csv: duplicate (from_area, to_area) pair(s) "
            f"{dup_pairs}."
        )

    # Self-loops -----------------------------------------------------------
    self_loops = df.loc[df["from_area"] == df["to_area"], "line_id"].tolist()
    if self_loops:
        raise ValueError(
            f"interconnections.csv: self-loops are not allowed; offending "
            f"line_id(s): {self_loops}."
        )

    # Foreign-key check on areas ------------------------------------------
    declared = {a["area_id"] for a in areas}
    referenced = set(df["from_area"]).union(df["to_area"])
    unknown = sorted(referenced - declared)
    if unknown:
        raise ValueError(
            f"interconnections.csv: references unknown area_id(s) {unknown} "
            f"not declared in areas.csv (declared: {sorted(declared)})."
        )

    return df[["line_id", "from_area", "to_area"]].to_dict(orient="records")


def _load_one_line_cap(input_data_dir, filename, *, lines, n_hours, direction):
    """Load and validate one of ``LineCap_FT.csv`` / ``LineCap_TF.csv``.

    Returns an empty DataFrame when the file is absent (the caller decides
    whether the absence is acceptable for the active Network formulation).

    Parameters
    ----------
    input_data_dir : str
        Path to the SDOM input data folder.
    filename : str
        ``"LineCap_FT.csv"`` or ``"LineCap_TF.csv"``.
    lines : list of dict
        Lines returned by ``_load_interconnections``. Used to validate the
        column set of the capacity file.
    n_hours : int
        Expected number of rows (defaults to 8760 in the public wrapper).
    direction : str
        Human label (``"FT"`` or ``"TF"``) used in error messages.

    Returns
    -------
    pandas.DataFrame
        Indexed by hour, with one column per ``line_id``. Empty if the
        file is absent or ``lines`` is empty.

    Raises
    ------
    ValueError
        If the column set differs from ``{l["line_id"] for l in lines}``,
        the row count differs from ``n_hours``, or any value is negative.
    """
    path = get_complete_path(input_data_dir, filename)
    if not path:
        return pd.DataFrame()

    df = pd.read_csv(path)
    if df.shape[1] < 2:
        raise ValueError(
            f"{filename}: expected an hour-index column followed by one "
            f"column per line_id; found {df.shape[1]} column(s)."
        )

    key_col = df.columns[0]
    df = df.copy()
    df[key_col] = pd.to_numeric(df[key_col], errors="coerce")
    df = df.sort_values(key_col).reset_index(drop=True)
    cap = df.set_index(key_col)
    cap.columns = cap.columns.astype(str)

    # Without lines we still return what we read so callers can introspect;
    # but the column / non-negativity checks below are skipped because they
    # reference the `lines` set.
    if not lines:
        return cap

    expected_cols = {l["line_id"] for l in lines}
    actual_cols = set(cap.columns)
    if actual_cols != expected_cols:
        missing = sorted(expected_cols - actual_cols)
        extra = sorted(actual_cols - expected_cols)
        raise ValueError(
            f"{filename}: column set must match interconnections.csv line_ids. "
            f"Missing: {missing}; unexpected: {extra}."
        )

    if len(cap) != n_hours:
        raise ValueError(
            f"{filename}: expected {n_hours} hourly rows, found {len(cap)}."
        )

    neg_mask = (cap < 0)
    if neg_mask.values.any():
        # Identify the first offending (row, column) pair for the message.
        rows, cols = neg_mask.values.nonzero()
        first_row = int(rows[0])
        first_col = cap.columns[int(cols[0])]
        bad_value = cap.iat[first_row, int(cols[0])]
        raise ValueError(
            f"{filename}: line capacities must be non-negative; first "
            f"violation at row index {first_row} (hour={cap.index[first_row]}), "
            f"line_id='{first_col}', value={bad_value}."
        )

    # Reorder columns to match the lines listing for stable downstream use.
    cap = cap[[l["line_id"] for l in lines]]
    return cap


def _load_line_capacities(input_data_dir, *, lines, n_hours=8760):
    """Load both directional line-capacity files (``FT`` and ``TF``).

    Parameters
    ----------
    input_data_dir : str
        Path to the SDOM input data folder.
    lines : list of dict
        Lines returned by ``_load_interconnections``.
    n_hours : int, optional
        Expected number of rows in each capacity file. Default ``8760``.

    Returns
    -------
    tuple of pandas.DataFrame
        ``(line_cap_ft, line_cap_tf)``. Empty DataFrames are returned when
        ``lines`` is empty or the corresponding file is absent. Columns are
        ordered to match ``lines``.

    Raises
    ------
    ValueError
        Propagated from :func:`_load_one_line_cap` (column set mismatch,
        wrong row count, negative values).
    """
    if not lines:
        return pd.DataFrame(), pd.DataFrame()

    line_cap_ft = _load_one_line_cap(
        input_data_dir, INPUT_CSV_NAMES["line_cap_ft"],
        lines=lines, n_hours=n_hours, direction="FT",
    )
    line_cap_tf = _load_one_line_cap(
        input_data_dir, INPUT_CSV_NAMES["line_cap_tf"],
        lines=lines, n_hours=n_hours, direction="TF",
    )
    return line_cap_ft, line_cap_tf


# ---------------------------------------------------------------------------------
# Aggregation fallback (commit #6): zonal data + CopperPlateNetwork
# ---------------------------------------------------------------------------------


def _sum_per_area_wide(per_area, *, single_col_name=None):
    """Aggregate a wide per-area dict into a single-column wide DataFrame.

    All per-area frames must share the same first ("key") column. Non-key
    columns are summed across areas. When ``single_col_name`` is provided,
    the resulting non-key column is renamed accordingly; otherwise the
    original (tag-stripped) column name from the first area is reused.

    Parameters
    ----------
    per_area : dict[str, pandas.DataFrame]
        Per-area wide DataFrames as produced by :func:`_split_wide_by_area`.
    single_col_name : str, optional
        Name to assign to the aggregated non-key column.

    Returns
    -------
    pandas.DataFrame or None
        The aggregated wide DataFrame with the original key column followed
        by a single value column. ``None`` when ``per_area`` is empty.
    """
    if not per_area:
        return None
    first = next(iter(per_area.values()))
    key_col = first.columns[0]
    accumulator = None
    for sub in per_area.values():
        # Sum non-key columns within each area first (handles the rare case
        # of multiple tagged columns sharing the same area / entity name).
        value_cols = [c for c in sub.columns if c != key_col]
        if not value_cols:
            continue
        per_hour = sub[value_cols].sum(axis=1).to_frame(name="_value")
        per_hour[key_col] = sub[key_col].values
        if accumulator is None:
            accumulator = per_hour
        else:
            accumulator = accumulator.merge(
                per_hour, on=key_col, how="outer", suffixes=("", "_b")
            )
            accumulator["_value"] = (
                accumulator["_value"].fillna(0.0)
                + accumulator["_value_b"].fillna(0.0)
            )
            accumulator = accumulator.drop(columns="_value_b")
    if accumulator is None:
        return None
    accumulator = accumulator[[key_col, "_value"]]
    name = single_col_name
    if name is None:
        # Reuse the first non-key column name from the first area as a
        # sensible default (e.g. "Load" from the "Load@A1@" header).
        first_value_cols = [c for c in first.columns if c != key_col]
        name = first_value_cols[0] if first_value_cols else "value"
    return accumulator.rename(columns={"_value": name})


def _capacity_weighted_average_prices(cap_per_area, price_per_area, *, label):
    """Aggregate per-area prices using per-area capacities as weights.

    Hour-by-hour, the aggregated price is

    .. math::
        \\bar{c}_h = \\frac{\\sum_a c_{a,h}\\,\\overline{cap}_{a,h}}
                          {\\sum_a \\overline{cap}_{a,h}}.

    When the total capacity at hour ``h`` is zero the simple unweighted mean
    of the per-area prices is used (and a single ``WARNING`` log is emitted
    once per file). Returns ``None`` when no per-area data is available.

    Parameters
    ----------
    cap_per_area : dict[str, pandas.DataFrame]
        Per-area capacity DataFrames; first column is the time key, second
        column is the capacity series.
    price_per_area : dict[str, pandas.DataFrame]
        Per-area price DataFrames; first column is the time key, second
        column is the price series.
    label : str
        ``"imports"`` or ``"exports"`` — used only for log messages.

    Returns
    -------
    pandas.DataFrame or None
        Wide DataFrame with the time-key column followed by a single price
        column whose name is taken from the first per-area price frame.
    """
    if not price_per_area:
        return None
    first_price = next(iter(price_per_area.values()))
    key_col = first_price.columns[0]
    price_name = next(c for c in first_price.columns if c != key_col)

    areas = list(price_per_area.keys())
    weighted_num = None
    weight_den = None
    fallback_mean = None
    for area in areas:
        price_df = price_per_area[area]
        price_col = next(c for c in price_df.columns if c != key_col)
        price_series = price_df.set_index(key_col)[price_col]

        cap_df = cap_per_area.get(area)
        if cap_df is not None and not cap_df.empty:
            cap_col = next(c for c in cap_df.columns if c != key_col)
            cap_series = cap_df.set_index(key_col)[cap_col]
        else:
            cap_series = pd.Series(0.0, index=price_series.index)

        # Align indices defensively.
        cap_series, price_series = cap_series.align(price_series, fill_value=0.0)
        contrib = cap_series * price_series
        if weighted_num is None:
            weighted_num = contrib
            weight_den = cap_series
            fallback_mean = price_series.copy()
            fallback_count = pd.Series(1, index=price_series.index)
        else:
            weighted_num = weighted_num.add(contrib, fill_value=0.0)
            weight_den = weight_den.add(cap_series, fill_value=0.0)
            fallback_mean = fallback_mean.add(price_series, fill_value=0.0)
            fallback_count = fallback_count.add(
                pd.Series(1, index=price_series.index), fill_value=0
            )

    fallback_mean = fallback_mean / fallback_count
    zero_mask = weight_den.fillna(0.0) == 0
    aggregated = weighted_num / weight_den.replace({0.0: pd.NA})
    aggregated = aggregated.where(~zero_mask, fallback_mean)
    if zero_mask.any():
        logging.warning(
            "Aggregation fallback (%s prices): %d hour(s) had zero total "
            "capacity across areas; falling back to unweighted mean for "
            "those hours.",
            label, int(zero_mask.sum()),
        )
    out = aggregated.to_frame(name=price_name).reset_index()
    return out


def _strip_area_tags_from_storage(storage_df):
    """Return a copy of ``storage_data`` with ``@area_id@`` tags stripped.

    Parameters
    ----------
    storage_df : pandas.DataFrame
        Storage data DataFrame indexed by property (e.g. ``P_Capex``);
        columns are storage tech identifiers, possibly tagged with
        ``@area_id@``.

    Returns
    -------
    pandas.DataFrame
        Same DataFrame with tags removed from column headers.

    Raises
    ------
    ValueError
        If two columns collapse to the same (untagged) tech identifier.
    """
    if storage_df is None or storage_df.empty:
        return storage_df

    new_cols = []
    for col in storage_df.columns:
        entity, _ = _parse_area_tagged_header(str(col))
        new_cols.append(entity)

    duplicates = sorted(
        {name for name in new_cols if new_cols.count(name) > 1}
    )
    if duplicates:
        raise ValueError(
            "StorageData.csv aggregation fallback: storage tech identifiers "
            f"collide across areas after stripping {AREA_TAG_DELIMITER}area_id"
            f"{AREA_TAG_DELIMITER} tags: {duplicates}. Make storage tech "
            "identifiers globally unique (e.g. 'Li-Ion-A1', 'Li-Ion-A2') "
            "before aggregating to CopperPlateNetwork."
        )

    out = storage_df.copy()
    out.columns = new_cols
    return out


def _aggregate_to_single_area(data):
    """Collapse a multi-area ``data`` dict into a synthetic single area.

    Implements the PRD §4.6 aggregation rules used when the input folder
    contains zonal data (``|areas| > 1``) but the active formulation is
    ``CopperPlateNetwork``. Hourly profiles are summed across areas;
    import/export prices are aggregated as a capacity-weighted average;
    row-oriented per-device tables shed their ``area_id`` column; the
    storage table sheds its ``@area_id@`` header tags. Capacity-factor
    tables are kept as-is (plant ids are already globally unique).

    Mutates ``data`` in place: legacy global keys are replaced with their
    aggregated single-column / single-area counterparts, ``data["areas"]``
    collapses to ``[{"area_id": DEFAULT_AREA_ID}]``, and every
    ``per_area_*`` view is rebuilt to contain the single ``DEFAULT_AREA_ID``
    key.

    Parameters
    ----------
    data : dict
        Data dictionary already populated by :func:`_augment_with_per_area_views`.

    Returns
    -------
    dict
        The same ``data`` dict, mutated in place.

    Raises
    ------
    ValueError
        Propagated from :func:`_strip_area_tags_from_storage` when storage
        tech identifiers collide across areas.
    """
    n_areas_in = len(data.get("areas", []))
    logging.warning(
        "Aggregating %d areas into a single 'default' area for "
        "CopperPlateNetwork.",
        n_areas_in,
    )

    # ---- Hourly profiles: sum across areas ------------------------------
    sum_specs = [
        ("load_data", "per_area_demand", "Load"),
        ("nuclear_data", "per_area_nuclear", "Nuclear"),
        ("other_renewables_data", "per_area_other_renewables", "OtherRenewables"),
        # Hydro hourly bounds / runs of river — keep the original column name
        # from the first area (e.g. "LargeHydro").
        ("large_hydro_data", None, None),
        ("large_hydro_max", None, None),
        ("large_hydro_min", None, None),
        ("cap_imports", None, None),
        ("cap_exports", None, None),
    ]
    for global_key, per_area_key, single_name in sum_specs:
        if global_key not in data or data.get(global_key) is None:
            continue
        if per_area_key is not None:
            per_area = data.get(per_area_key, {})
        else:
            # Re-derive per-area split from the current global wide DataFrame.
            per_area, _ = _split_wide_by_area(
                data[global_key], file_label=global_key
            )
        aggregated = _sum_per_area_wide(per_area, single_col_name=single_name)
        if aggregated is not None:
            data[global_key] = aggregated

    # ---- Import / Export prices: capacity-weighted average --------------
    for label, cap_key, price_key in (
        ("imports", "cap_imports", "price_imports"),
        ("exports", "cap_exports", "price_exports"),
    ):
        if data.get(price_key) is None:
            continue
        cap_per_area, _ = _split_wide_by_area(
            data.get(cap_key), file_label=cap_key
        ) if data.get(cap_key) is not None else ({}, set())
        price_per_area, _ = _split_wide_by_area(
            data[price_key], file_label=price_key
        )
        aggregated = _capacity_weighted_average_prices(
            cap_per_area, price_per_area, label=label
        )
        if aggregated is not None:
            data[price_key] = aggregated

    # ---- Row-oriented per-device tables: drop area_id column ------------
    for global_key in ("cap_solar", "cap_wind", "thermal_data"):
        df = data.get(global_key)
        if df is not None and "area_id" in df.columns:
            data[global_key] = df.drop(columns=["area_id"]).copy()

    # ---- Storage table: strip @area_id@ tags from column headers --------
    storage_df = data.get("storage_data")
    if storage_df is not None:
        data["storage_data"] = _strip_area_tags_from_storage(storage_df)
        # Recompute derived storage tech lists from the newly tag-stripped frame.
        data["STORAGE_SET_J_TECHS"] = (
            data["storage_data"].columns.astype(str).tolist()
        )
        if "Coupled" in data["storage_data"].index:
            data["STORAGE_SET_B_TECHS"] = (
                data["storage_data"]
                .columns[data["storage_data"].loc["Coupled"] == 1]
                .astype(str)
                .tolist()
            )

    # ---- CFSolar / CFWind unchanged (plant ids globally unique) ---------

    # ---- Collapse areas + rebuild per_area_* dicts to single key --------
    data["areas"] = [
        {"area_id": DEFAULT_AREA_ID, "description": "Aggregated default area"}
    ]
    data["per_area_demand"] = {DEFAULT_AREA_ID: data.get("load_data")}
    data["per_area_nuclear"] = {DEFAULT_AREA_ID: data.get("nuclear_data")}
    data["per_area_other_renewables"] = {
        DEFAULT_AREA_ID: data.get("other_renewables_data")
    }

    # Hydro composite — merge run-of-river / max / min on the time key.
    hydro_components = [
        ("LargeHydro", data.get("large_hydro_data")),
        ("LargeHydro_Max", data.get("large_hydro_max")),
        ("LargeHydro_Min", data.get("large_hydro_min")),
    ]
    hydro_merged = None
    for label, sub in hydro_components:
        if sub is None or sub.empty:
            continue
        key_col = sub.columns[0]
        value_cols = [c for c in sub.columns if c != key_col]
        renamed = sub.rename(columns={c: label for c in value_cols})
        hydro_merged = (
            renamed
            if hydro_merged is None
            else hydro_merged.merge(renamed, on=key_col, how="outer")
        )
    data["per_area_hydro"] = (
        {DEFAULT_AREA_ID: hydro_merged} if hydro_merged is not None else {}
    )

    # Imports / exports composite — merge cap + price on the time key.
    def _merge_cap_price(cap_df, price_df):
        if cap_df is None and price_df is None:
            return None
        if cap_df is None:
            return price_df.copy()
        if price_df is None:
            return cap_df.copy()
        return cap_df.merge(price_df, on=cap_df.columns[0], how="outer")

    imp_merged = _merge_cap_price(data.get("cap_imports"), data.get("price_imports"))
    exp_merged = _merge_cap_price(data.get("cap_exports"), data.get("price_exports"))
    data["per_area_imports"] = (
        {DEFAULT_AREA_ID: imp_merged} if imp_merged is not None else {}
    )
    data["per_area_exports"] = (
        {DEFAULT_AREA_ID: exp_merged} if exp_merged is not None else {}
    )

    # Per-device tables.
    if data.get("cap_solar") is not None:
        data["per_area_pv_plants"] = {DEFAULT_AREA_ID: data["cap_solar"]}
    if data.get("cap_wind") is not None:
        data["per_area_wind_plants"] = {DEFAULT_AREA_ID: data["cap_wind"]}
    if data.get("thermal_data") is not None:
        data["per_area_balancing_units"] = {DEFAULT_AREA_ID: data["thermal_data"]}
    if data.get("storage_data") is not None:
        data["per_area_storage"] = {DEFAULT_AREA_ID: data["storage_data"]}

    # Capacity factors: a single area now holds every plant column.
    if data.get("cf_solar") is not None:
        data["per_area_capacity_factors_pv"] = {DEFAULT_AREA_ID: data["cf_solar"]}
    if data.get("cf_wind") is not None:
        data["per_area_capacity_factors_wind"] = {DEFAULT_AREA_ID: data["cf_wind"]}

    return data


def load_data( input_data_dir:str = '.\\Data\\' ):
    """Load all required SDOM input datasets from CSV files in the specified directory.
    
    Reads and validates all input CSV files needed for SDOM optimization including
    VRE data, fixed generation profiles, storage characteristics, thermal units,
    scalars, and formulation specifications. Performs data consistency checks and
    filters datasets based on completeness.
    
    Args:
        input_data_dir (str, optional): Path to directory containing input CSV files.
            Defaults to '.\\Data\\'. Should contain all required files defined in
            constants.INPUT_CSV_NAMES.
    
    Returns:
        dict: Dictionary containing loaded and processed data with keys:
            - 'formulations' (pd.DataFrame): Component formulation specifications
            - 'solar_plants', 'wind_plants' (list): Plant IDs for VRE technologies
            - 'cf_solar', 'cf_wind' (pd.DataFrame): Hourly capacity factors
            - 'cap_solar', 'cap_wind' (pd.DataFrame): Plant CAPEX and capacity data
            - 'load_data' (pd.DataFrame): Hourly electricity demand
            - 'nuclear_data' (pd.DataFrame): Hourly nuclear generation
            - 'large_hydro_data' (pd.DataFrame): Hourly hydropower generation/availability
            - 'large_hydro_max', 'large_hydro_min' (pd.DataFrame): Hydro bounds
              (if budget formulation)
            - 'other_renewables_data' (pd.DataFrame): Hourly other renewable generation
            - 'storage_data' (pd.DataFrame): Storage technology characteristics
            - 'STORAGE_SET_J_TECHS', 'STORAGE_SET_B_TECHS' (list): Storage tech identifiers
            - 'thermal_data' (pd.DataFrame): Thermal balancing unit parameters
            - 'scalars' (pd.DataFrame): System-level scalar parameters
            - 'import_cap', 'export_cap', 'import_prices', 'export_prices' (pd.DataFrame):
              Trade data (if import/export formulation active)
            - 'complete_solar_data', 'complete_wind_data' (pd.DataFrame): Filtered VRE data
            - 'filtered_cap_solar_dict', 'filtered_cap_wind_dict' (dict): Capacity mappings
    
    Raises:
        FileNotFoundError: If any required input file is missing from input_data_dir.
        ValueError: If formulation specifications are invalid.
    
    Notes:
        - All numeric data rounded to 5 decimal places for consistency
        - VRE plant lists filtered to include only plants with complete data
        - Conditionally loads hydro bounds and import/export data based on formulations
        - Uses flexible filename matching via normalize_string() for CSV files
        - Logs detailed progress at debug level for troubleshooting data loading issues
    """
    logging.info("Loading SDOM input data...")
    
    logging.debug("- Trying to load formulations data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["formulations"], "CSV file to specify the formulations for different components")
    if input_file_path != "":
        formulations = pd.read_csv( input_file_path )
    
    logging.debug("- Trying to load VRE data...")
    # THE SET CSV FILES WERE REMOVED
    # input_file_path = os.path.join(input_data_dir, INPUT_CSV_NAMES["solar_plants"])
    # if check_file_exists(input_file_path, "solar plants ids"):
    #     solar_plants = pd.read_csv( input_file_path, header=None )[0].tolist()
    
    # input_file_path = os.path.join(input_data_dir, INPUT_CSV_NAMES["wind_plants"])
    # if check_file_exists(input_file_path, "wind plants ids"):
    #     wind_plants = pd.read_csv( input_file_path, header=None )[0].tolist()


    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["cf_solar"], "Capacity factors for pv solar")
    if input_file_path != "":
        cf_solar = pd.read_csv( input_file_path ).round(5)
        cf_solar.columns = cf_solar.columns.astype(str)
        solar_plants = cf_solar.columns[1:].tolist()
        logging.debug( f"-- It were loaded a total of {len( solar_plants )} solar plants profiles." )
    
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["cf_wind"], "Capacity factors for wind")
    if input_file_path != "":
        cf_wind = pd.read_csv( input_file_path ).round(5)
        cf_wind.columns = cf_wind.columns.astype(str)
        wind_plants = cf_wind.columns[1:].tolist()
        logging.debug( f"-- It were loaded a total of {len( wind_plants )} wind plants profiles." )

    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["cap_solar"], "Capex information for solar")
    if input_file_path != "":
        cap_solar = pd.read_csv( input_file_path ).round(5)
        cap_solar['sc_gid'] = cap_solar['sc_gid'].astype(str)
        solar_plants_capex = cap_solar['sc_gid'].tolist()
        compare_lists(solar_plants, solar_plants_capex, text_comp="solar plants", list_names=["CF", "Capex"])

    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["cap_wind"], "Capex information for wind")
    if input_file_path != "":
        cap_wind = pd.read_csv( input_file_path ).round(5)
        cap_wind['sc_gid'] = cap_wind['sc_gid'].astype(str)
        wind_plants_capex = cap_wind['sc_gid'].tolist()
        compare_lists(wind_plants, wind_plants_capex, text_comp="wind plants", list_names=["CF", "Capex"])

    logging.debug("- Trying to load demand data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["load_data"], "load data")
    if input_file_path != "":
        load_data = pd.read_csv( input_file_path ).round(5)

    logging.debug("- Trying to load nuclear data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["nuclear_data"], "nuclear data")
    if input_file_path != "":
        nuclear_data = pd.read_csv( input_file_path ).round(5)

    logging.debug("- Trying to load large hydro data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["large_hydro_data"], "large hydro data")
    if input_file_path != "":
        large_hydro_data = pd.read_csv( input_file_path ).round(5)

    logging.debug("- Trying to load other renewables data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["other_renewables_data"], "other renewables data")
    if input_file_path != "":
        other_renewables_data = pd.read_csv( input_file_path ).round(5)

    logging.debug("- Trying to load storage data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["storage_data"], "Storage data")
    if input_file_path != "":
        storage_data = pd.read_csv( input_file_path, index_col=0 ).round(5)
        storage_set_j_techs = storage_data.columns[0:].astype(str).tolist()
        storage_set_b_techs = storage_data.columns[ storage_data.loc["Coupled"] == 1 ].astype( str ).tolist()

    logging.debug("- Trying to load thermal generation data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["thermal_data"], "thermal data")
    if input_file_path != "":
        thermal_data = pd.read_csv( input_file_path ).round(5)

    logging.debug("- Trying to load scalars data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["scalars"], "scalars")
    if input_file_path != "":
        scalars = pd.read_csv( input_file_path, index_col="Parameter" )
    #os.chdir('../')

    data_dict =  {
            "formulations": formulations,
            "solar_plants": solar_plants,
            "wind_plants": wind_plants,
            "load_data": load_data,
            "nuclear_data": nuclear_data,
            "large_hydro_data": large_hydro_data,
            "other_renewables_data": other_renewables_data,
            "cf_solar": cf_solar,
            "cf_wind": cf_wind,
            "cap_solar": cap_solar,
            "cap_wind": cap_wind,
            "storage_data": storage_data,
            "STORAGE_SET_J_TECHS": storage_set_j_techs,
            "STORAGE_SET_B_TECHS": storage_set_b_techs,
            "thermal_data": thermal_data,
            "scalars": scalars,
        }

    # --- Network (zonal) formulation: backward-compatible default ---
    network_formulation = get_network_formulation(data_dict)
    check_formulation(network_formulation, VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP.keys())

    hydro_formulation = get_formulation(data_dict, component='hydro')
    check_formulation( hydro_formulation, VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP.keys() )

    if not (hydro_formulation == RUN_OF_RIVER_FORMULATION):
        logging.debug("- Hydro was set to MonthlyBudgetFormulation. Trying to load large hydro max/min data...")
        
        input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["large_hydro_max"], "large hydro Maximum  capacity data")
        if input_file_path != "":
            large_hydro_max = pd.read_csv( input_file_path ).round(5)
        
        input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["large_hydro_min"], "large hydro Minimum capacity data")
        if input_file_path != "":
            large_hydro_min = pd.read_csv( input_file_path ).round(5)
        data_dict["large_hydro_max"] = large_hydro_max
        data_dict["large_hydro_min"] = large_hydro_min
    

    logging.debug("- Trying to load imports data...")    
    imports_formulation = get_formulation(data_dict, component='imports')
    check_formulation( imports_formulation, VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP.keys() )
    if (imports_formulation == IMPORTS_EXPORTS_CAPACITY_PRICE_NET_LOAD):
        logging.debug("- Imports was set to CapacityPriceNetLoadFormulation. Trying to load capacity and price...")
        
        input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["cap_imports"], "Imports hourly upper bound capacity data")
        if input_file_path != "":
            cap_imports = pd.read_csv( input_file_path ).round(5)

        input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["price_imports"], "Imports hourly price data")
        if input_file_path != "":
            price_imports = pd.read_csv( input_file_path ).round(5)
        data_dict["cap_imports"] = cap_imports
        data_dict["price_imports"] = price_imports

    
    logging.debug("- Trying to load exports data...")
    exports_formulation = get_formulation(data_dict, component='exports')
    check_formulation( exports_formulation, VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP.keys() )
    if (exports_formulation == IMPORTS_EXPORTS_CAPACITY_PRICE_NET_LOAD):
        logging.debug("- Exports was set to CapacityPriceNetLoadFormulation. Trying to load capacity and price...")
        
        input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["cap_exports"], "Exports hourly upper bound capacity data")
        if input_file_path != "":
            cap_exports = pd.read_csv( input_file_path ).round(5)

        input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["price_exports"], "Exports hourly price data")
        if input_file_path != "":
            price_exports = pd.read_csv( input_file_path ).round(5)
        data_dict["cap_exports"] = cap_exports
        data_dict["price_exports"] = price_exports
    
    _augment_with_per_area_views(data_dict, input_data_dir=input_data_dir)

    # ------------------------------------------------------------------
    # Aggregation fallback (commit #6): zonal data + CopperPlateNetwork.
    # When the user ships a multi-area input folder but selects (or
    # defaults to) ``CopperPlateNetwork``, collapse every per-area entity
    # into a single synthetic ``default`` area following PRD §4.6.
    # Transmission CSVs are dropped with a WARNING (no transmission in
    # copper-plate).
    # ------------------------------------------------------------------
    aggregated = False
    if (
        get_network_formulation(data_dict) == COPPER_PLATE_NETWORK
        and len(data_dict.get("areas", [])) > 1
    ):
        _aggregate_to_single_area(data_dict)
        aggregated = True
        if any(
            get_complete_path(input_data_dir, name)
            for name in AREA_TRANSPORTATION_MODEL_NETWORK_REQUIRED_INPUTS
        ):
            logging.warning(
                "Aggregation fallback: dropping interregional transmission "
                "files (%s) because Network=%s has no transmission.",
                ", ".join(AREA_TRANSPORTATION_MODEL_NETWORK_REQUIRED_INPUTS),
                COPPER_PLATE_NETWORK,
            )

    # ------------------------------------------------------------------
    # Zonal topology + line capacities (commit #5).
    # Skipped entirely when the aggregation fallback above collapsed the
    # input to a single synthetic area. Otherwise parsed when present so
    # legacy folders pick up empty defaults without raising; the
    # AreaTransportationModelNetwork formulation *requires* all three CSVs.
    # ------------------------------------------------------------------
    if aggregated:
        lines = []
        line_cap_ft, line_cap_tf = pd.DataFrame(), pd.DataFrame()
    else:
        lines = _load_interconnections(input_data_dir, areas=data_dict["areas"])
        line_cap_ft, line_cap_tf = _load_line_capacities(
            input_data_dir, lines=lines
        )

        if get_network_formulation(data_dict) == AREA_TRANSPORTATION_MODEL_NETWORK:
            missing_files = [
                name
                for name in AREA_TRANSPORTATION_MODEL_NETWORK_REQUIRED_INPUTS
                if not get_complete_path(input_data_dir, name)
            ]
            if missing_files:
                raise ValueError(
                    f"Network={AREA_TRANSPORTATION_MODEL_NETWORK} requires the "
                    f"following file(s) to be present: {missing_files}."
                )

    data_dict["lines"] = lines
    data_dict["line_cap_ft"] = line_cap_ft
    data_dict["line_cap_tf"] = line_cap_tf

    return data_dict
    



# ---------------------------------------------------------------------------------
# Export results to CSV files
# ---------------------------------------------------------------------------------

def export_results(results, case: str, output_dir: str = "./results_pyomo/"):
    """Export optimization results to CSV files.

    Writes the results from an OptimizationResults object to CSV files in the
    specified directory. Creates output directory if it doesn't exist.

    Parameters
    ----------
    results : OptimizationResults
        The optimization results object from run_solver().
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

    Notes
    -----
    This function accepts either an OptimizationResults dataclass (new API)
    or the legacy tuple return from run_solver (deprecated).
    """
    # Import here to avoid circular imports
    from .results import OptimizationResults

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
    gen_df = results.get_generation_dataframe()
    if not gen_df.empty:
        # Update scenario column with the case name
        gen_df["Scenario"] = case
        gen_df.to_csv(os.path.join(output_dir, f"OutputGeneration_{case}.csv"), index=False)

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
        installed_plants_df.to_csv(os.path.join(output_dir, f"OutputInstalledPowerPlants_{case}.csv"), index=False)


def _export_from_model_legacy(model, case, output_dir="./results_pyomo/"):
    """Legacy export function that works directly with a model object.

    This is the original implementation preserved for backward compatibility.

    Parameters
    ----------
    model : pyomo.core.base.PyomoModel.ConcreteModel
        Solved Pyomo model instance.
    case : str
        Case identifier for filenames.
    output_dir : str
        Output directory path.
    """
    logging.info("Exporting SDOM results (legacy mode)...")
    os.makedirs(output_dir, exist_ok=True)

    # Initialize results dictionaries column: [values]
    logging.debug("--Initializing results dictionaries...")
    gen_results = {
        "Scenario": [],
        "Hour": [],
        "Solar PV Generation (MW)": [],
        "Solar PV Curtailment (MW)": [],
        "Wind Generation (MW)": [],
        "Wind Curtailment (MW)": [],
        "All Thermal Generation (MW)": [],
        "Hydro Generation (MW)": [],
        "Nuclear Generation (MW)": [],
        "Other Renewables Generation (MW)": [],
        "Imports (MW)": [],
        "Storage Charge/Discharge (MW)": [],
        "Exports (MW)": [],
        "Load (MW)": [],
        "Net Load (MW)": [],
    }

    storage_results = {
        "Hour": [],
        "Technology": [],
        "Charging power (MW)": [],
        "Discharging power (MW)": [],
        "State of charge (MWh)": [],
    }

    # Extract generation results
    logging.debug("--Extracting generation results...")
    for h in model.h:
        solar_gen = safe_pyomo_value(model.pv.generation[h])
        solar_curt = safe_pyomo_value(model.pv.curtailment[h])
        wind_gen = safe_pyomo_value(model.wind.generation[h])
        wind_curt = safe_pyomo_value(model.wind.curtailment[h])
        gas_cc_gen = sum(safe_pyomo_value(model.thermal.generation[h, bu]) for bu in model.thermal.plants_set)
        hydro = safe_pyomo_value(model.hydro.generation[h])
        nuclear = safe_pyomo_value(model.nuclear.alpha * model.nuclear.ts_parameter[h]) if hasattr(model.nuclear, "alpha") else 0
        other_renewables = safe_pyomo_value(model.other_renewables.alpha * model.other_renewables.ts_parameter[h]) if hasattr(model.other_renewables, "alpha") else 0
        imports = safe_pyomo_value(model.imports.variable[h]) if hasattr(model.imports, "variable") else 0
        exports = safe_pyomo_value(model.exports.variable[h]) if hasattr(model.exports, "variable") else 0
        load = safe_pyomo_value(model.demand.ts_parameter[h]) if hasattr(model.demand, "ts_parameter") else 0
        net_load = safe_pyomo_value(model.net_load[h]) if hasattr(model, "net_load") else 0
        # Only append results if all values are valid (not None)
        if None not in [solar_gen, solar_curt, wind_gen, wind_curt, gas_cc_gen, hydro, imports, exports, load]:
            gen_results["Hour"].append(h)
            gen_results["Solar PV Generation (MW)"].append(solar_gen)
            gen_results["Solar PV Curtailment (MW)"].append(solar_curt)
            gen_results["Wind Generation (MW)"].append(wind_gen)
            gen_results["Wind Curtailment (MW)"].append(wind_curt)
            gen_results["All Thermal Generation (MW)"].append(gas_cc_gen)
            gen_results["Hydro Generation (MW)"].append(hydro)
            gen_results["Nuclear Generation (MW)"].append(nuclear)
            gen_results["Other Renewables Generation (MW)"].append(other_renewables)
            gen_results["Imports (MW)"].append(imports)

            power_to_storage = sum(safe_pyomo_value(model.storage.PC[h, j]) or 0 for j in model.storage.j) - sum(safe_pyomo_value(model.storage.PD[h, j]) or 0 for j in model.storage.j)
            gen_results["Storage Charge/Discharge (MW)"].append(power_to_storage)
            gen_results["Exports (MW)"].append(exports)
            gen_results["Load (MW)"].append(load)
            gen_results["Net Load (MW)"].append(net_load)
        gen_results["Scenario"].append(case)

    # Extract storage results
    logging.debug("--Extracting storage results...")
    for h in model.h:
        for j in model.storage.j:
            charge_power = safe_pyomo_value(model.storage.PC[h, j])
            discharge_power = safe_pyomo_value(model.storage.PD[h, j])
            soc = safe_pyomo_value(model.storage.SOC[h, j])
            if None not in [charge_power, discharge_power, soc]:
                storage_results["Hour"].append(h)
                storage_results["Technology"].append(j)
                storage_results["Charging power (MW)"].append(charge_power)
                storage_results["Discharging power (MW)"].append(discharge_power)
                storage_results["State of charge (MWh)"].append(soc)

    # Summary results (total capacities and costs)
    ## Total cost
    logging.debug("--Extracting summary results...")
    total_cost = pd.DataFrame.from_dict(
        {"Total cost": [None, 1, safe_pyomo_value(model.Obj()), "$US"]},
        orient="index",
        columns=["Technology", "Run", "Optimal Value", "Unit"],
    )
    total_cost = total_cost.reset_index(names="Metric")
    summary_results = total_cost

    ## Total capacity
    cap = {}
    cap["Thermal"] = sum(safe_pyomo_value(model.thermal.plant_installed_capacity[bu]) for bu in model.thermal.plants_set)
    cap["Solar PV"] = safe_pyomo_value(model.pv.total_installed_capacity)
    cap["Wind"] = safe_pyomo_value(model.wind.total_installed_capacity)
    cap["All"] = cap["Thermal"] + cap["Solar PV"] + cap["Wind"]

    summary_results = concatenate_dataframes(summary_results, cap, run=1, unit="MW", metric="Capacity")

    ## Charge power capacity
    storage_tech_list = list(model.storage.j)
    charge = {}
    sum_all = 0.0
    for tech in storage_tech_list:
        charge[tech] = safe_pyomo_value(model.storage.Pcha[tech])
        sum_all += charge[tech]
    charge["All"] = sum_all

    summary_results = concatenate_dataframes(summary_results, charge, run=1, unit="MW", metric="Charge power capacity")

    ## Discharge power capacity
    dcharge = {}
    sum_all = 0.0

    for tech in storage_tech_list:
        dcharge[tech] = safe_pyomo_value(model.storage.Pdis[tech])
        sum_all += dcharge[tech]
    dcharge["All"] = sum_all

    summary_results = concatenate_dataframes(summary_results, dcharge, run=1, unit="MW", metric="Discharge power capacity")

    ## Average power capacity
    avgpocap = {}
    sum_all = 0.0
    for tech in storage_tech_list:
        avgpocap[tech] = (charge[tech] + dcharge[tech]) / 2
        sum_all += avgpocap[tech]
    avgpocap["All"] = sum_all

    summary_results = concatenate_dataframes(summary_results, avgpocap, run=1, unit="MW", metric="Average power capacity")

    ## Energy capacity
    encap = {}
    sum_all = 0.0
    for tech in storage_tech_list:
        encap[tech] = safe_pyomo_value(model.storage.Ecap[tech])
        sum_all += encap[tech]
    encap["All"] = sum_all

    summary_results = concatenate_dataframes(summary_results, encap, run=1, unit="MWh", metric="Energy capacity")

    ## Discharge duration
    dis_dur = {}
    for tech in storage_tech_list:
        dis_dur[tech] = safe_pyomo_value(sqrt(model.storage.data["Eff", tech]) * model.storage.Ecap[tech] / (model.storage.Pdis[tech] + 1e-15))

    summary_results = concatenate_dataframes(summary_results, dis_dur, run=1, unit="h", metric="Duration")

    ## Generation
    gen = {}
    gen["Thermal"] = safe_pyomo_value(model.thermal.total_generation)
    gen["Solar PV"] = safe_pyomo_value(model.pv.total_generation)
    gen["Wind"] = safe_pyomo_value(model.wind.total_generation)
    gen["Other renewables"] = safe_pyomo_value(sum(model.other_renewables.ts_parameter[h] for h in model.h))
    gen["Hydro"] = safe_pyomo_value(sum(model.hydro.generation[h] for h in model.h))
    gen["Nuclear"] = safe_pyomo_value(sum(model.nuclear.ts_parameter[h] for h in model.h))

    # Storage energy discharging
    sum_all = 0.0
    storage_tech_list = list(model.storage.j)
    for tech in storage_tech_list:
        gen[tech] = safe_pyomo_value(sum(model.storage.PD[h, tech] for h in model.h))
        sum_all += gen[tech]

    gen["All"] = gen["Thermal"] + gen["Solar PV"] + gen["Wind"] + gen["Other renewables"] + gen["Hydro"] + gen["Nuclear"] + sum_all

    summary_results = concatenate_dataframes(summary_results, gen, run=1, unit="MWh", metric="Total generation")

    imp_exp = {}
    imp_exp["Imports"] = safe_pyomo_value(sum(model.imports.variable[h] for h in model.h)) if hasattr(model.imports, "variable") else 0
    imp_exp["Exports"] = safe_pyomo_value(sum(model.exports.variable[h] for h in model.h)) if hasattr(model.exports, "variable") else 0
    summary_results = concatenate_dataframes(summary_results, imp_exp, run=1, unit="MWh", metric="Total Imports/Exports")

    ## Storage energy discharging
    sum_all = 0.0
    stodisch = {}
    for tech in storage_tech_list:
        stodisch[tech] = safe_pyomo_value(sum(model.storage.PD[h, tech] for h in model.h))
        sum_all += stodisch[tech]
    stodisch["All"] = sum_all

    summary_results = concatenate_dataframes(summary_results, stodisch, run=1, unit="MWh", metric="Storage energy discharging")

    ## Demand
    dem = {}
    dem["demand"] = sum(model.demand.ts_parameter[h] for h in model.h)

    summary_results = concatenate_dataframes(summary_results, dem, run=1, unit="MWh", metric="Total demand")

    ## Storage energy charging
    sum_all = 0.0
    stoch = {}
    for tech in storage_tech_list:
        stoch[tech] = safe_pyomo_value(sum(model.storage.PC[h, tech] for h in model.h))
        sum_all += stoch[tech]
    stoch["All"] = sum_all

    summary_results = concatenate_dataframes(summary_results, stoch, run=1, unit="MWh", metric="Storage energy charging")

    ## CAPEX
    capex = {}
    capex["Solar PV"] = safe_pyomo_value(model.pv.capex_cost_expr)
    capex["Wind"] = safe_pyomo_value(model.wind.capex_cost_expr)
    capex["Thermal"] = safe_pyomo_value(model.thermal.capex_cost_expr)
    capex["All"] = capex["Solar PV"] + capex["Wind"] + capex["Thermal"]

    summary_results = concatenate_dataframes(summary_results, capex, run=1, unit="$US", metric="CAPEX")

    ## Power CAPEX
    pcapex = {}
    sum_all = 0.0
    for tech in storage_tech_list:
        pcapex[tech] = safe_pyomo_value(model.storage.power_capex_cost_expr[tech])
        sum_all += pcapex[tech]

    pcapex["All"] = sum_all

    summary_results = concatenate_dataframes(summary_results, pcapex, run=1, unit="$US", metric="Power-CAPEX")

    ## Energy CAPEX and Total CAPEX
    ecapex = {}
    tcapex = {}
    sum_all = 0.0
    sum_all_t = 0.0
    for tech in storage_tech_list:
        ecapex[tech] = safe_pyomo_value(model.storage.energy_capex_cost_expr[tech])
        sum_all += ecapex[tech]
        tcapex[tech] = pcapex[tech] + ecapex[tech]
        sum_all_t += tcapex[tech]
    ecapex["All"] = sum_all
    tcapex["All"] = sum_all_t

    summary_results = concatenate_dataframes(summary_results, ecapex, run=1, unit="$US", metric="Energy-CAPEX")
    summary_results = concatenate_dataframes(summary_results, tcapex, run=1, unit="$US", metric="Total-CAPEX")

    ## FOM
    fom = {}
    sum_all = 0.0
    fom["Thermal"] = safe_pyomo_value(model.thermal.fixed_om_cost_expr)
    fom["Solar PV"] = safe_pyomo_value(model.pv.fixed_om_cost_expr)
    fom["Wind"] = safe_pyomo_value(model.wind.fixed_om_cost_expr)

    for tech in storage_tech_list:
        fom[tech] = safe_pyomo_value(
            MW_TO_KW * model.storage.data["CostRatio", tech] * model.storage.data["FOM", tech] * model.storage.Pcha[tech]
            + MW_TO_KW * (1 - model.storage.data["CostRatio", tech]) * model.storage.data["FOM", tech] * model.storage.Pdis[tech]
        )
        sum_all += fom[tech]

    fom["All"] = fom["Thermal"] + fom["Solar PV"] + fom["Wind"] + sum_all

    summary_results = concatenate_dataframes(summary_results, fom, run=1, unit="$US", metric="FOM")

    ## VOM
    vom = {}
    sum_all = 0.0
    vom["Thermal"] = safe_pyomo_value(model.thermal.total_vom_cost_expr)

    for tech in storage_tech_list:
        vom[tech] = safe_pyomo_value(model.storage.data["VOM", tech] * sum(model.storage.PD[h, tech] for h in model.h))
        sum_all += vom[tech]
    vom["All"] = vom["Thermal"] + sum_all

    summary_results = concatenate_dataframes(summary_results, vom, run=1, unit="$US", metric="VOM")

    fuel_cost = {}
    fuel_cost["Thermal"] = safe_pyomo_value(model.thermal.total_fuel_cost_expr)
    summary_results = concatenate_dataframes(summary_results, fuel_cost, run=1, unit="$US", metric="Fuel-Cost")

    ## OPEX
    opex = {}
    sum_all = 0.0
    opex["Thermal"] = fom["Thermal"] + vom["Thermal"]
    opex["Solar PV"] = fom["Solar PV"]
    opex["Wind"] = fom["Wind"]

    for tech in storage_tech_list:
        opex[tech] = fom[tech] + vom[tech]
        sum_all += opex[tech]
    opex["All"] = opex["Thermal"] + opex["Solar PV"] + opex["Wind"] + sum_all

    summary_results = concatenate_dataframes(summary_results, opex, run=1, unit="$US", metric="OPEX")

    # IMPORTS/EXPORTS COSTS
    cost_revenue = {}
    cost_revenue["Imports Cost"] = safe_pyomo_value(model.imports.total_cost_expr)
    summary_results = concatenate_dataframes(summary_results, cost_revenue, run=1, unit="$US", metric="Cost")
    cost_revenue = {}
    cost_revenue["Exports Revenue"] = safe_pyomo_value(model.exports.total_cost_expr)
    summary_results = concatenate_dataframes(summary_results, cost_revenue, run=1, unit="$US", metric="Revenue")

    ## Equivalent number of cycles
    cyc = {}
    for tech in storage_tech_list:
        cyc[tech] = safe_pyomo_value(gen[tech] / (model.storage.Ecap[tech] + 1e-15))

    summary_results = concatenate_dataframes(summary_results, cyc, run=1, unit="-", metric="Equivalent number of cycles")

    ## VRE Curtailment
    pv_curtailment = safe_pyomo_value(model.pv.total_curtailment) if hasattr(model.pv, "total_curtailment") else 0.0
    wind_curtailment = safe_pyomo_value(model.wind.total_curtailment) if hasattr(model.wind, "total_curtailment") else 0.0
    pv_generation = safe_pyomo_value(model.pv.total_generation) if hasattr(model.pv, "total_generation") else 0.0
    wind_generation = safe_pyomo_value(model.wind.total_generation) if hasattr(model.wind, "total_generation") else 0.0
    
    total_vre_curtailment_mwh = pv_curtailment + wind_curtailment
    total_vre_availability = pv_generation + wind_generation + pv_curtailment + wind_curtailment
    total_vre_curtailment_pct = (total_vre_curtailment_mwh / total_vre_availability * 100) if total_vre_availability > 0 else 0.0
    
    vre_curt_mwh = {"Solar PV": pv_curtailment, "Wind": wind_curtailment, "All": total_vre_curtailment_mwh}
    summary_results = concatenate_dataframes(summary_results, vre_curt_mwh, run=1, unit="MWh", metric="Total VRE curtailment")
    
    vre_curt_pct = {"All": total_vre_curtailment_pct}
    summary_results = concatenate_dataframes(summary_results, vre_curt_pct, run=1, unit="%", metric="VRE curtailment percentage")

    logging.info("Exporting csv files containing SDOM results...")
    # Save generation results to CSV
    logging.debug("-- Saving generation results to CSV...")
    if gen_results["Hour"]:
        with open(output_dir + f"OutputGeneration_{case}.csv", mode="w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=gen_results.keys())
            writer.writeheader()
            writer.writerows([dict(zip(gen_results, t)) for t in zip(*gen_results.values())])

    # Save storage results to CSV
    logging.debug("-- Saving storage results to CSV...")
    if storage_results["Hour"]:
        with open(output_dir + f"OutputStorage_{case}.csv", mode="w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=storage_results.keys())
            writer.writeheader()
            writer.writerows([dict(zip(storage_results, t)) for t in zip(*storage_results.values())])

    # Save summary results to CSV
    logging.debug("-- Saving summary results to CSV...")
    if len(summary_results) > 0:
        summary_results.to_csv(output_dir + f"OutputSummary_{case}.csv", index=False)

    if len(model.thermal.plants_set) <= 1:
        return
    thermal_gen_columns = ["Hour"] + [str(plant) for plant in model.thermal.plants_set]
    disaggregated_thermal_gen_results = get_dict_string_void_list_from_keys_in_list(thermal_gen_columns)

    for h in model.h:
        disaggregated_thermal_gen_results["Hour"].append(h)
        for plant in model.thermal.plants_set:
            disaggregated_thermal_gen_results[plant].append(safe_pyomo_value(model.thermal.generation[h, plant]))

    logging.debug("-- Saving disaggregated thermal generation results to CSV...")
    if disaggregated_thermal_gen_results["Hour"]:
        with open(output_dir + f"OutputThermalGeneration_{case}.csv", mode="w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=disaggregated_thermal_gen_results.keys())
            writer.writeheader()
            writer.writerows([dict(zip(disaggregated_thermal_gen_results, t)) for t in zip(*disaggregated_thermal_gen_results.values())])