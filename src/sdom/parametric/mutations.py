"""Data mutation helpers for SDOM parametric analysis.

Each helper applies one parameter change to the provided data dict.
These helpers mutate the given data structure in-place; callers who need to
preserve the original data are responsible for deep-copying before passing it
here.
"""

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lookup table: data-dict key → numeric column name to scale
# ---------------------------------------------------------------------------

#: Maps every supported ``ts_key`` to the column that holds numeric values
#: in the corresponding DataFrame.  Used by :func:`_apply_ts_mutation`.
TS_KEY_TO_COLUMN: dict[str, str] = {
    "load_data": "Load",
    "large_hydro_data": "LargeHydro",
    "large_hydro_max": "LargeHydro_max",
    "large_hydro_min": "LargeHydro_min",
    "cap_imports": "Imports",
    "price_imports": "Imports_price",
    "cap_exports": "Exports",
    "price_exports": "Exports_price",
    "nuclear_data": "Nuclear",
    "other_renewables_data": "OtherRenewables",
}

# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------


def _apply_scalar_mutation(data: dict, data_key: str, param_name: str, value: Any) -> None:
    """Replace a scalar value in a DataFrame row-indexed by parameter name.

    Sets ``data[data_key].loc[param_name, "Value"] = value``.

    Parameters
    ----------
    data : dict
        SDOM data dictionary (already deep-copied; will be mutated in-place).
    data_key : str
        Key identifying the DataFrame in *data* (e.g. ``"scalars"``).
    param_name : str
        Row label of the parameter to modify (e.g. ``"GenMix_Target"``).
    value : float or int
        New value to assign.

    Raises
    ------
    ValueError
        If *data_key* is not in *data*, or *param_name* is not a valid row
        label in ``data[data_key]``.
    """
    if data_key not in data:
        raise ValueError(
            f"_apply_scalar_mutation: data key '{data_key}' not found in data dict. "
            f"Available keys: {list(data.keys())}"
        )
    df: pd.DataFrame = data[data_key]
    if param_name not in df.index:
        raise ValueError(
            f"_apply_scalar_mutation: parameter '{param_name}' not found in "
            f"data['{data_key}'].index. Available: {list(df.index)}"
        )
    logger.debug(
        "_apply_scalar_mutation: data['%s'].loc['%s', 'Value'] = %s",
        data_key, param_name, value,
    )
    data[data_key].loc[param_name, "Value"] = value


def _apply_storage_factor_mutation(data: dict, param_name: str, factor: float) -> None:
    """Scale an entire row of ``data["storage_data"]`` by a multiplicative factor.

    Multiplies ``data["storage_data"].loc[param_name]`` (all technology
    columns) by *factor*.  This uniformly scales the parameter across all
    storage technologies.

    Parameters
    ----------
    data : dict
        SDOM data dictionary (already deep-copied; will be mutated in-place).
    param_name : str
        Row label in ``data["storage_data"]`` (e.g. ``"P_Capex"``).
    factor : float
        Multiplicative factor.  ``1.0`` leaves the row unchanged.

    Raises
    ------
    ValueError
        If ``"storage_data"`` is absent from *data* or *param_name* is not
        a valid row label.
    """
    data_key = "storage_data"
    if data_key not in data:
        raise ValueError(
            f"_apply_storage_factor_mutation: '{data_key}' not found in data dict."
        )
    df: pd.DataFrame = data[data_key]
    if param_name not in df.index:
        raise ValueError(
            f"_apply_storage_factor_mutation: parameter '{param_name}' not found in "
            f"data['storage_data'].index. Available: {list(df.index)}"
        )
    logger.debug(
        "_apply_storage_factor_mutation: data['storage_data'].loc['%s'] *= %s",
        param_name, factor,
    )
    data[data_key].loc[param_name] = data[data_key].loc[param_name] * factor


def _apply_ts_mutation(data: dict, ts_key: str, factor: float) -> None:
    """Scale the numeric column of a time-series DataFrame by a multiplicative factor.

    Looks up the target column name in :data:`TS_KEY_TO_COLUMN` and multiplies
    ``data[ts_key][column] *= factor``.

    Parameters
    ----------
    data : dict
        SDOM data dictionary (already deep-copied; will be mutated in-place).
    ts_key : str
        Key identifying the time-series DataFrame in *data*
        (e.g. ``"load_data"``).  Must be present in :data:`TS_KEY_TO_COLUMN`.
    factor : float
        Multiplicative scaling factor.  ``1.0`` leaves the series unchanged.

    Raises
    ------
    ValueError
        If *ts_key* is not in :data:`TS_KEY_TO_COLUMN`, if *ts_key* is not
        present in *data*, or if the resolved column is absent from the
        DataFrame.
    """
    if ts_key not in TS_KEY_TO_COLUMN:
        raise ValueError(
            f"_apply_ts_mutation: ts_key '{ts_key}' is not supported. "
            f"Supported keys: {list(TS_KEY_TO_COLUMN.keys())}"
        )
    if ts_key not in data:
        raise ValueError(
            f"_apply_ts_mutation: ts_key '{ts_key}' not found in data dict. "
            f"(The corresponding formulation may not include it.)"
        )
    column = TS_KEY_TO_COLUMN[ts_key]
    df: pd.DataFrame = data[ts_key]
    if column not in df.columns:
        raise ValueError(
            f"_apply_ts_mutation: expected column '{column}' not found in "
            f"data['{ts_key}'].columns. Available: {list(df.columns)}"
        )
    logger.debug(
        "_apply_ts_mutation: data['%s']['%s'] *= %s",
        ts_key, column, factor,
    )
    data[ts_key][column] = data[ts_key][column] * factor
