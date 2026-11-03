"""Load transmission topology and directional hourly line capacities."""

import pandas as pd

from ..common.utilities import (
    get_complete_path,
)
from ..constants import (
    INPUT_CSV_NAMES,
)
from .validation import (
    validate_interconnections,
    validate_line_capacities,
    validate_line_capacity_layout,
)


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
    df = validate_interconnections(df, areas=areas)
    if df.empty:
        return []

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
    validate_line_capacity_layout(df, filename=filename)

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

    cap = validate_line_capacities(cap, filename=filename, lines=lines, n_hours=n_hours)
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
        input_data_dir,
        INPUT_CSV_NAMES["line_cap_ft"],
        lines=lines,
        n_hours=n_hours,
        direction="FT",
    )
    line_cap_tf = _load_one_line_cap(
        input_data_dir,
        INPUT_CSV_NAMES["line_cap_tf"],
        lines=lines,
        n_hours=n_hours,
        direction="TF",
    )
    return line_cap_ft, line_cap_tf
