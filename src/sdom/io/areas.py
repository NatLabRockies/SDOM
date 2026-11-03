"""Parse area encodings and construct canonical per-area input views."""

import pandas as pd

from ..common.utilities import (
    get_complete_path,
)
from ..constants import (
    AREA_TAG_DELIMITER,
    DEFAULT_AREA_ID,
    INPUT_CSV_NAMES,
)
from .validation import (
    validate_area_column_encoding,
    validate_area_tag,
    validate_areas_columns,
    validate_observed_areas,
    validate_unique_plant_ids,
)


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
    match = validate_area_tag(header)
    if match is None:
        return header, None
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

    validate_area_column_encoding(tagged=tagged, untagged=untagged, file_label=file_label)

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
        renames = dict(items)
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

    validate_unique_plant_ids(df, id_col=id_col, file_label=file_label)

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
        validate_areas_columns(df)
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
    storage_df = data.get("storage_data")

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

    # Fast path for legacy single-area folders: no areas.csv and no area encoding
    # in headers or row tables. This avoids expensive split/validation work while
    # preserving the exact per_area_* key surface expected downstream.
    has_tagged_wide_headers = any(
        df is not None and not df.empty and any(AREA_TAG_DELIMITER in str(col) for col in df.columns[1:])
        for key, _ in wide_specs
        for df in [data.get(key)]
    )
    has_tagged_storage_headers = (
        storage_df is not None
        and not storage_df.empty
        and any(AREA_TAG_DELIMITER in str(col) for col in storage_df.columns)
    )
    has_row_area_column = any(
        df is not None and not df.empty and "area_id" in df.columns
        for df in [
            data.get("thermal_data"),
            data.get("cap_solar"),
            data.get("cap_wind"),
        ]
    )

    if (
        not areas_present
        and not has_tagged_wide_headers
        and not has_tagged_storage_headers
        and not has_row_area_column
    ):
        default_area = DEFAULT_AREA_ID
        if not areas:
            areas = [
                {
                    "area_id": default_area,
                    "description": f"Area {default_area}",
                }
            ]

        def _single_area_view(df):
            if df is None or df.empty:
                return {}
            return {default_area: df.copy()}

        per_area_hydro = {}
        for label, key in (
            ("LargeHydro", "large_hydro_data"),
            ("LargeHydro_Max", "large_hydro_max"),
            ("LargeHydro_Min", "large_hydro_min"),
        ):
            sub = data.get(key)
            if sub is None or sub.empty:
                continue
            key_col = sub.columns[0]
            value_cols = [c for c in sub.columns if c != key_col]
            renamed = sub.rename(
                columns={c: (label if len(value_cols) == 1 else f"{label}__{c}") for c in value_cols}
            )
            if default_area not in per_area_hydro:
                per_area_hydro[default_area] = renamed
            else:
                per_area_hydro[default_area] = per_area_hydro[default_area].merge(
                    renamed, on=key_col, how="outer"
                )

        data["areas"] = areas
        data["per_area_demand"] = _single_area_view(data.get("load_data"))
        data["per_area_pv_plants"] = _single_area_view(data.get("cap_solar"))
        data["per_area_wind_plants"] = _single_area_view(data.get("cap_wind"))
        data["per_area_balancing_units"] = _single_area_view(data.get("thermal_data"))
        data["per_area_storage"] = _single_area_view(storage_df)
        data["per_area_hydro"] = per_area_hydro
        data["per_area_nuclear"] = _single_area_view(data.get("nuclear_data"))
        data["per_area_other_renewables"] = _single_area_view(data.get("other_renewables_data"))
        data["per_area_imports"] = _combine_per_area_imp_exp(
            _single_area_view(data.get("cap_imports")),
            _single_area_view(data.get("price_imports")),
        )
        data["per_area_exports"] = _combine_per_area_imp_exp(
            _single_area_view(data.get("cap_exports")),
            _single_area_view(data.get("price_exports")),
        )
        data["per_area_capacity_factors_pv"] = _single_area_view(data.get("cf_solar"))
        data["per_area_capacity_factors_wind"] = _single_area_view(data.get("cf_wind"))
        return data
    splits: dict[str, dict[str, pd.DataFrame]] = {}
    observed_total: set[str] = set()
    for key, label in wide_specs:
        per_area, observed = _split_wide_by_area(data.get(key), file_label=label)
        validate_observed_areas(
            observed,
            areas=areas,
            areas_csv_present=areas_present,
            source_label=label,
        )
        splits[key] = per_area
        observed_total |= observed

    # StorageData.csv is read with index_col=0; rebuild the wide form for parsing.
    if storage_df is not None and not storage_df.empty:
        index_label = storage_df.index.name or "Property"
        storage_wide = storage_df.reset_index().rename(
            columns={storage_df.index.name or "index": index_label}
        )
        per_area_storage_wide, observed_storage = _split_wide_by_area(
            storage_wide, file_label="StorageData.csv"
        )
        validate_observed_areas(
            observed_storage,
            areas=areas,
            areas_csv_present=areas_present,
            source_label="StorageData.csv",
        )
        per_area_storage = {
            area: sub.set_index(sub.columns[0]) for area, sub in per_area_storage_wide.items()
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
    validate_observed_areas(
        observed_bu,
        areas=areas,
        areas_csv_present=areas_present,
        source_label="Data_BalancingUnits.csv",
    )
    observed_total |= observed_bu

    per_area_pv_plants, observed_pv = _split_row_by_area(
        data.get("cap_solar"), id_col="sc_gid", file_label="CapSolar.csv"
    )
    validate_observed_areas(
        observed_pv,
        areas=areas,
        areas_csv_present=areas_present,
        source_label="CapSolar.csv",
    )
    observed_total |= observed_pv

    per_area_wind_plants, observed_wind = _split_row_by_area(
        data.get("cap_wind"), id_col="sc_gid", file_label="CapWind.csv"
    )
    validate_observed_areas(
        observed_wind,
        areas=areas,
        areas_csv_present=areas_present,
        source_label="CapWind.csv",
    )
    observed_total |= observed_wind

    per_area_cf_pv = _split_cf_by_plant_area(data.get("cf_solar"), per_area_pv_plants, id_col="sc_gid")
    per_area_cf_wind = _split_cf_by_plant_area(data.get("cf_wind"), per_area_wind_plants, id_col="sc_gid")

    per_area_imports = _combine_per_area_imp_exp(splits["cap_imports"], splits["price_imports"])
    per_area_exports = _combine_per_area_imp_exp(splits["cap_exports"], splits["price_exports"])

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
                columns={c: (label if len(value_cols) == 1 else f"{label}__{c}") for c in value_cols}
            )
            if area not in per_area_hydro:
                per_area_hydro[area] = renamed
            else:
                per_area_hydro[area] = per_area_hydro[area].merge(renamed, on=key_col, how="outer")

    # Synthesize areas from observed tags when areas.csv was absent.
    if not areas_present and observed_total:
        areas = [{"area_id": area, "description": f"Area {area}"} for area in sorted(observed_total)]

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
