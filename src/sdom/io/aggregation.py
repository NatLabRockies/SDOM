"""Transform zonal inputs into a single copper-plate area."""

import logging

import pandas as pd

from ..constants import (
    DEFAULT_AREA_ID,
)
from .areas import _parse_area_tagged_header, _split_wide_by_area
from .validation import validate_storage_technology_names


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
            accumulator = accumulator.merge(per_hour, on=key_col, how="outer", suffixes=("", "_b"))
            accumulator["_value"] = accumulator["_value"].fillna(0.0) + accumulator["_value_b"].fillna(0.0)
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
    r"""Aggregate per-area prices using per-area capacities as weights.

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
            fallback_count = fallback_count.add(pd.Series(1, index=price_series.index), fill_value=0)

    fallback_mean = fallback_mean / fallback_count
    zero_mask = weight_den.fillna(0.0) == 0
    aggregated = weighted_num / weight_den.replace({0.0: pd.NA})
    aggregated = aggregated.where(~zero_mask, fallback_mean)
    if zero_mask.any():
        logging.warning(
            "Aggregation fallback (%s prices): %d hour(s) had zero total "
            "capacity across areas; falling back to unweighted mean for "
            "those hours.",
            label,
            int(zero_mask.sum()),
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

    validate_storage_technology_names(new_cols)

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
        "Aggregating %d areas into a single 'default' area for CopperPlateNetwork.",
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
            per_area, _ = _split_wide_by_area(data[global_key], file_label=global_key)
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
        cap_per_area, _ = (
            _split_wide_by_area(data.get(cap_key), file_label=cap_key)
            if data.get(cap_key) is not None
            else ({}, set())
        )
        price_per_area, _ = _split_wide_by_area(data[price_key], file_label=price_key)
        aggregated = _capacity_weighted_average_prices(cap_per_area, price_per_area, label=label)
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
        data["STORAGE_SET_J_TECHS"] = data["storage_data"].columns.astype(str).tolist()
        if "Coupled" in data["storage_data"].index:
            data["STORAGE_SET_B_TECHS"] = (
                data["storage_data"].columns[data["storage_data"].loc["Coupled"] == 1].astype(str).tolist()
            )

    # ---- CFSolar / CFWind unchanged (plant ids globally unique) ---------

    # ---- Collapse areas + rebuild per_area_* dicts to single key --------
    data["areas"] = [{"area_id": DEFAULT_AREA_ID, "description": "Aggregated default area"}]
    data["per_area_demand"] = {DEFAULT_AREA_ID: data.get("load_data")}
    data["per_area_nuclear"] = {DEFAULT_AREA_ID: data.get("nuclear_data")}
    data["per_area_other_renewables"] = {DEFAULT_AREA_ID: data.get("other_renewables_data")}

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
        renamed = sub.rename(columns=dict.fromkeys(value_cols, label))
        hydro_merged = (
            renamed if hydro_merged is None else hydro_merged.merge(renamed, on=key_col, how="outer")
        )
    data["per_area_hydro"] = {DEFAULT_AREA_ID: hydro_merged} if hydro_merged is not None else {}

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
    data["per_area_imports"] = {DEFAULT_AREA_ID: imp_merged} if imp_merged is not None else {}
    data["per_area_exports"] = {DEFAULT_AREA_ID: exp_merged} if exp_merged is not None else {}

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
