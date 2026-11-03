"""Validate scenario inputs without filesystem access.

Validators raise ``ValueError`` for invalid supplied inputs. Normalization is
explicit in return values; caller-owned DataFrames are not modified.
"""

import re
from collections.abc import Collection, Sequence

import numpy as np
import pandas as pd

from ..constants import (
    AREA_TAG_DELIMITER,
    FORMULATION_VALIDATION_BY_COMPONENT,
    INPUT_CSV_NAMES,
    NO_RAMPS_MIN_DISPATCH_FORMULATION,
)

_AREA_TAG_RE = re.compile(
    rf"^(?P<entity>[^{re.escape(AREA_TAG_DELIMITER)}]*)"
    rf"{re.escape(AREA_TAG_DELIMITER)}"
    rf"(?P<area>[^{re.escape(AREA_TAG_DELIMITER)}]+)"
    rf"{re.escape(AREA_TAG_DELIMITER)}$"
)


def check_formulation(formulation: str, valid_formulations: Collection[str]) -> None:
    """Validate a formulation against the supported selections.

    Parameters
    ----------
    formulation : str
        Selection supplied in ``formulations.csv``.
    valid_formulations : collection of str
        Supported selections for the component.

    Raises
    ------
    ValueError
        If the selection is unsupported.
    """
    if formulation not in valid_formulations:
        raise ValueError(
            f"Invalid formulation '{formulation}' selected by the user in file "
            f"'formulations.csv'. Valid options are: {valid_formulations}"
        )


def validate_formulation_selection(matches: pd.Series, *, component: str) -> None:
    """Validate supplied rows for a component with registered strict rules.

    Parameters
    ----------
    matches : pandas.Series
        Matching formulation values, possibly empty.
    component : str
        Case-insensitive component name.

    Raises
    ------
    ValueError
        If registered rules reject duplicate rows or a supplied selection.
        Missing rows are left to the caller's default-selection policy.
    """
    choices = FORMULATION_VALIDATION_BY_COMPONENT.get(component.lower())
    if choices is not None and len(matches) > 1:
        raise ValueError(
            f"formulations.csv: {component.capitalize()} has duplicate rows; "
            f"supported choices are {tuple(choices)}."
        )
    if choices is not None and not matches.empty:
        selected = matches.iloc[0]
        if not isinstance(selected, str) or selected not in choices:
            raise ValueError(
                f"formulations.csv: {component.capitalize()} selection {selected!r}; "
                f"supported choices are {tuple(choices)}."
            )


def validate_thermal_profile_headers(headers: Sequence[str]) -> None:
    """Validate raw thermal CSV headers before pandas can rename duplicates.

    Parameters
    ----------
    headers : sequence of str
        Unmodified CSV header row.

    Raises
    ------
    ValueError
        If headers repeat or the first column is not ``Hour``.
    """
    filename = INPUT_CSV_NAMES["thermal_min_dispatch_fraction"]
    if len(headers) != len(set(headers)):
        raise ValueError(f"{filename}: duplicate CSV headers are not allowed.")
    if not headers or headers[0] != "Hour":
        raise ValueError(f"{filename}: first column must be Hour.")


def validate_area_tag(header: str) -> re.Match[str] | None:
    """Validate the syntax of an optional area tag in a column header.

    Parameters
    ----------
    header : str
        Legacy header or ``<entity>@<area_id>@`` header.

    Returns
    -------
    re.Match or None
        Validated tag match, or ``None`` for an untagged legacy header.

    Raises
    ------
    ValueError
        If a delimiter is present but the complete tag is malformed.
    """
    if AREA_TAG_DELIMITER not in header:
        return None
    match = _AREA_TAG_RE.match(header)
    if match is None:
        raise ValueError(
            f"Invalid area tag in column header '{header}'. Expected format "
            f"'<entity>{AREA_TAG_DELIMITER}<area_id>{AREA_TAG_DELIMITER}'."
        )
    return match


def validate_area_column_encoding(*, tagged: int, untagged: int, file_label: str) -> None:
    """Reject mixed tagged and legacy non-key columns.

    Parameters
    ----------
    tagged : int
        Number of tagged non-key columns.
    untagged : int
        Number of untagged non-key columns.
    file_label : str
        Source label used in the error message.

    Raises
    ------
    ValueError
        If both encodings occur in one table.
    """
    if untagged and tagged:
        raise ValueError(
            f"{file_label} mixes legacy (untagged) and {AREA_TAG_DELIMITER}area_id"
            f"{AREA_TAG_DELIMITER}-tagged columns. All non-key columns must be "
            f"either all untagged or all tagged."
        )


def validate_unique_plant_ids(df: pd.DataFrame, *, id_col: str, file_label: str) -> None:
    """Validate global identifier uniqueness for an area-aware plant table.

    Parameters
    ----------
    df : pandas.DataFrame
        Row-oriented table already identified as area-aware.
    id_col : str
        Plant identifier column.
    file_label : str
        Source label used in the error message.

    Raises
    ------
    ValueError
        If the identifier column is present and contains duplicate values.
    """
    if id_col in df.columns and df[id_col].duplicated().any():
        duplicates = df.loc[df[id_col].duplicated(keep=False), id_col].astype(str).unique().tolist()
        raise ValueError(
            f"{file_label}: '{id_col}' values must be globally unique across "
            f"areas; duplicates found: {duplicates}."
        )


def validate_areas_columns(df: pd.DataFrame) -> None:
    """Validate the required column of a supplied area-declaration table.

    Parameters
    ----------
    df : pandas.DataFrame
        Parsed ``areas.csv`` contents.

    Raises
    ------
    ValueError
        If ``area_id`` is absent.
    """
    if "area_id" not in df.columns:
        raise ValueError("areas.csv must include an 'area_id' column.")


def validate_observed_areas(
    observed: set[str], *, areas: list[dict], areas_csv_present: bool, source_label: str
) -> None:
    """Validate references against explicit area declarations.

    Parameters
    ----------
    observed : set of str
        Area identifiers found in an input table.
    areas : list of dict
        Area descriptors containing ``area_id``.
    areas_csv_present : bool
        Whether declarations came from an explicit CSV. When false, the
        caller may synthesize declarations from observed identifiers.
    source_label : str
        Source label used in the error message.

    Raises
    ------
    ValueError
        If an observed identifier is absent from explicit declarations.
    """
    if not observed or not areas_csv_present:
        return
    declared = {area["area_id"] for area in areas}
    unknown = sorted(observed - declared)
    if unknown:
        raise ValueError(
            f"{source_label}: references unknown area_id(s) {unknown} not "
            f"declared in areas.csv (declared: {sorted(declared)})."
        )


def validate_interconnections(df: pd.DataFrame, *, areas: list[dict]) -> pd.DataFrame:
    """Validate topology and return a copy with normalized string identifiers.

    Parameters
    ----------
    df : pandas.DataFrame
        Parsed ``interconnections.csv`` contents.
    areas : list of dict
        Declared areas used as foreign-key targets.

    Returns
    -------
    pandas.DataFrame
        Validated topology. Empty tables are returned unchanged.

    Raises
    ------
    ValueError
        If columns are missing, identifiers or directed pairs repeat, a
        self-loop exists, or an endpoint references an unknown area.
    """
    required = {"line_id", "from_area", "to_area"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"interconnections.csv is missing required column(s): {sorted(missing)}.")
    if df.empty:
        return df
    df = df.copy()
    for column in ("line_id", "from_area", "to_area"):
        df[column] = df[column].astype(str)
    duplicate_ids = df.loc[df["line_id"].duplicated(keep=False), "line_id"].unique().tolist()
    if duplicate_ids:
        raise ValueError(f"interconnections.csv: duplicate line_id value(s) {sorted(duplicate_ids)}.")
    duplicate_pairs = df.duplicated(subset=["from_area", "to_area"], keep=False)
    if duplicate_pairs.any():
        pairs = (
            df.loc[duplicate_pairs, ["from_area", "to_area"]]
            .drop_duplicates()
            .apply(lambda row: (row["from_area"], row["to_area"]), axis=1)
            .tolist()
        )
        raise ValueError(f"interconnections.csv: duplicate (from_area, to_area) pair(s) {pairs}.")
    self_loops = df.loc[df["from_area"] == df["to_area"], "line_id"].tolist()
    if self_loops:
        raise ValueError(
            f"interconnections.csv: self-loops are not allowed; offending line_id(s): {self_loops}."
        )
    declared = {area["area_id"] for area in areas}
    referenced = set(df["from_area"]).union(df["to_area"])
    unknown = sorted(referenced - declared)
    if unknown:
        raise ValueError(
            f"interconnections.csv: references unknown area_id(s) {unknown} "
            f"not declared in areas.csv (declared: {sorted(declared)})."
        )
    return df


def validate_line_capacity_layout(df: pd.DataFrame, *, filename: str) -> None:
    """Validate that a line-capacity table has an index and value columns.

    Parameters
    ----------
    df : pandas.DataFrame
        Raw parsed capacity table.
    filename : str
        Source filename used in the error message.

    Raises
    ------
    ValueError
        If fewer than two columns are present.
    """
    if df.shape[1] < 2:
        raise ValueError(
            f"{filename}: expected an hour-index column followed by one "
            f"column per line_id; found {df.shape[1]} column(s)."
        )


def validate_line_capacities(
    cap: pd.DataFrame, *, filename: str, lines: list[dict], n_hours: int
) -> pd.DataFrame:
    """Validate indexed capacities and order columns by the supplied topology.

    Parameters
    ----------
    cap : pandas.DataFrame
        Capacity table indexed by hour.
    filename : str
        Source filename used in error messages.
    lines : list of dict
        Nonempty topology descriptors containing ``line_id``.
    n_hours : int
        Required row count.

    Returns
    -------
    pandas.DataFrame
        Validated capacities with columns in topology order.

    Raises
    ------
    ValueError
        If columns differ from topology, the row count is wrong, or a
        capacity is negative.
    """
    expected_cols = {line["line_id"] for line in lines}
    actual_cols = set(cap.columns)
    if actual_cols != expected_cols:
        missing = sorted(expected_cols - actual_cols)
        extra = sorted(actual_cols - expected_cols)
        raise ValueError(
            f"{filename}: column set must match interconnections.csv line_ids. "
            f"Missing: {missing}; unexpected: {extra}."
        )
    if len(cap) != n_hours:
        raise ValueError(f"{filename}: expected {n_hours} hourly rows, found {len(cap)}.")
    negative = cap < 0
    if negative.values.any():
        rows, cols = negative.values.nonzero()
        first_row = int(rows[0])
        first_col = cap.columns[int(cols[0])]
        bad_value = cap.iat[first_row, int(cols[0])]
        raise ValueError(
            f"{filename}: line capacities must be non-negative; first "
            f"violation at row index {first_row} (hour={cap.index[first_row]}), "
            f"line_id='{first_col}', value={bad_value}."
        )
    return cap[[line["line_id"] for line in lines]]


def validate_required_network_files(missing_files: list[str], *, formulation: str) -> None:
    """Reject missing files required by the active network formulation.

    Parameters
    ----------
    missing_files : list of str
        Required filenames not found by the loader.
    formulation : str
        Active network formulation.

    Raises
    ------
    ValueError
        If the list of missing files is nonempty.
    """
    if missing_files:
        raise ValueError(
            f"Network={formulation} requires the following file(s) to be present: {missing_files}."
        )


def validate_storage_technology_names(names: list[str]) -> None:
    """Reject storage identifiers that collide after area-tag removal.

    Parameters
    ----------
    names : list of str
        Storage technology identifiers with area tags already stripped.

    Raises
    ------
    ValueError
        If multiple tagged identifiers collapse to the same name.
    """
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(
            "StorageData.csv aggregation fallback: storage tech identifiers "
            f"collide across areas after stripping {AREA_TAG_DELIMITER}area_id"
            f"{AREA_TAG_DELIMITER} tags: {duplicates}. Make storage tech "
            "identifiers globally unique (e.g. 'Li-Ion-A1', 'Li-Ion-A2') "
            "before aggregating to CopperPlateNetwork."
        )


def validate_thermal_min_dispatch(data: dict, *, n_hours: int | None = None) -> pd.DataFrame:
    """Validate and canonicalize an enabled hourly thermal fraction table.

    Parameters
    ----------
    data : dict
        Static ``thermal_data`` and ``thermal_min_dispatch_fraction`` inputs.
        IDs use exact string identity; fractions are dimensionless.
    n_hours : int, optional
        Effective modeled horizon, including hydro-budget rounding.

    Returns
    -------
    pandas.DataFrame
        Full-precision fractions sorted by Hour, with columns in thermal
        plant order. Extra supplied hours are validated and retained.

    Raises
    ------
    ValueError
        If identity, bounds, headers, hours, values, or coverage are invalid.
        An empty thermal fleet still requires an hour-only profile.
    """
    source = INPUT_CSV_NAMES["thermal_min_dispatch_fraction"]
    thermal = data["thermal_data"]
    if not {"Plant_id", "MinCapacity", "MaxCapacity"} <= set(thermal.columns):
        raise ValueError(
            "Data_BalancingUnits.csv: Plant_id, MinCapacity, and MaxCapacity headers are required."
        )
    ids = thermal["Plant_id"].astype(str)
    if thermal["Plant_id"].isna().any() or ids.str.strip().eq("").any() or ids.duplicated().any():
        raise ValueError(
            "Data_BalancingUnits.csv: Plant_id must be nonblank and unique after string normalization."
        )
    bounds = {}
    for bound in ("MinCapacity", "MaxCapacity"):
        try:
            values = pd.to_numeric(thermal[bound], errors="raise").to_numpy(dtype=float)
        except (ValueError, TypeError) as exc:
            invalid = pd.to_numeric(thermal[bound], errors="coerce").isna().to_numpy()
            index = int(np.flatnonzero(invalid)[0])
            raise ValueError(
                f"Data_BalancingUnits.csv: Plant_id={ids.iloc[index]!r}: "
                f"{bound} requires finite numeric MW; got {thermal[bound].iloc[index]!r}."
            ) from exc
        bad = ~np.isfinite(values) | (values < 0)
        if bad.any():
            index = int(np.flatnonzero(bad)[0])
            raise ValueError(
                f"Data_BalancingUnits.csv: Plant_id={ids.iloc[index]!r}: invalid {bound}={thermal[bound].iloc[index]!r}; expected finite nonnegative MW."
            )
        bounds[bound] = values
    bad = bounds["MinCapacity"] > bounds["MaxCapacity"]
    if bad.any():
        index = int(np.flatnonzero(bad)[0])
        raise ValueError(
            f"Data_BalancingUnits.csv: Plant_id={ids.iloc[index]!r}: require 0 <= MinCapacity <= MaxCapacity; got {bounds['MinCapacity'][index]}, {bounds['MaxCapacity'][index]}."
        )
    if len(data.get("areas", [])) > 1:
        expected = {
            (str(a), str(k), float(lo), float(hi))
            for a, k, lo, hi in thermal[["area_id", "Plant_id", "MinCapacity", "MaxCapacity"]].itertuples(
                index=False, name=None
            )
        }
        actual = [
            (str(area), str(k), float(lo), float(hi))
            for area, table in data["per_area_balancing_units"].items()
            for k, lo, hi in table[["Plant_id", "MinCapacity", "MaxCapacity"]].itertuples(
                index=False, name=None
            )
        ]
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError(
                "thermal_data/per_area_balancing_units: thermal ownership and capacity bounds must agree."
            )
    frame = data.get("thermal_min_dispatch_fraction")
    if not isinstance(frame, pd.DataFrame):
        raise ValueError(
            f"{source} (thermal_min_dispatch_fraction): required under {NO_RAMPS_MIN_DISPATCH_FORMULATION}."
        )
    if frame.columns.duplicated().any():
        raise ValueError(f"{source}: duplicate headers are not allowed.")
    if not len(frame.columns) or frame.columns[0] != "Hour":
        raise ValueError(f"{source}: first column must be Hour.")
    missing = set(ids) - set(frame.columns[1:])
    extra = set(frame.columns[1:]) - set(ids)
    if missing or extra:
        raise ValueError(
            f"{source}: missing Plant_id columns {sorted(missing)}; unexpected columns {sorted(extra, key=str)}."
        )

    normalized = frame.loc[:, ["Hour", *ids]].copy()
    for column in normalized:
        raw = normalized[column]
        context = "Hour" if column == "Hour" else f"Plant_id={column!r}"
        boolean = (
            raw.map(lambda x: isinstance(x, (bool, np.bool_)))
            if raw.dtype == object or pd.api.types.is_bool_dtype(raw.dtype)
            else None
        )
        try:
            numeric = pd.to_numeric(raw, errors="raise").to_numpy(dtype=float, na_value=np.nan)
        except (ValueError, TypeError) as exc:
            # Conversion failures are rare; locate the offending cell only then.
            numeric = pd.to_numeric(raw, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
            bad_index = int(np.flatnonzero(~np.isfinite(numeric))[0])
            raise ValueError(
                f"{source}: {context}, Hour={frame['Hour'].iloc[bad_index]}: expected a finite "
                f"{'positive integer Hour' if column == 'Hour' else 'fraction in [0, 1]'}; got {raw.iloc[bad_index]!r}."
            ) from exc
        bad = ~np.isfinite(numeric)
        bad |= (
            (numeric < 1) | (numeric != np.floor(numeric))
            if column == "Hour"
            else (numeric < 0) | (numeric > 1)
        )
        if boolean is not None:
            bad |= boolean.to_numpy()
        if bad.any():
            index = int(np.flatnonzero(bad)[0])
            raise ValueError(
                f"{source}: {context}, Hour={frame['Hour'].iloc[index]}: expected a finite "
                f"{'positive integer Hour' if column == 'Hour' else 'fraction in [0, 1]'}; got {raw.iloc[index]!r}."
            )
        normalized[column] = numeric
    normalized = normalized.sort_values("Hour").reset_index(drop=True)
    if normalized.empty or not np.array_equal(
        normalized["Hour"].to_numpy(), np.arange(1, len(normalized) + 1)
    ):
        raise ValueError(f"{source}: Hour labels must uniquely cover exactly 1..N without gaps (N > 0).")
    normalized["Hour"] = normalized["Hour"].astype(int)
    if n_hours is not None and len(normalized) < n_hours:
        raise ValueError(
            f"{source}: insufficient Hour coverage for effective modeled horizon {n_hours}; got {len(normalized)}."
        )
    return normalized
