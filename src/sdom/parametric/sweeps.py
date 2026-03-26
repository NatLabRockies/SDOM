"""Parameter sweep descriptor dataclasses for SDOM parametric analysis."""

from dataclasses import dataclass, field
from typing import List, Union


@dataclass
class ScalarSweep:
    """Descriptor for a scalar parameter sweep.

    Defines a sweep over discrete absolute values for a scalar parameter
    stored in the SDOM data dict. The sweep replaces
    ``data[data_key].loc[param_name, "Value"]`` with each value in turn.

    Parameters
    ----------
    data_key : str
        Key in the SDOM data dict whose DataFrame contains the parameter
        (e.g. ``"scalars"``).
    param_name : str
        Row label in ``data[data_key]`` (e.g. ``"GenMix_Target"``).
    values : list of float
        Discrete values to evaluate. Each entry produces one case dimension
        in the Cartesian product.

    Examples
    --------
    >>> ScalarSweep("scalars", "GenMix_Target", [0.7, 0.8, 0.9, 1.0])
    """

    data_key: str
    param_name: str
    values: List[Union[int, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError(
                f"ScalarSweep for '{self.data_key}.{self.param_name}' must have at least one value."
            )


@dataclass
class StorageFactorSweep:
    """Descriptor for a multiplicative storage-parameter sweep.

    Multiplies the entire row ``data["storage_data"].loc[param_name]``
    (i.e. all storage technologies) by each factor. This is the primary
    use-case when scaling a cost parameter uniformly across all techs.

    Parameters
    ----------
    param_name : str
        Row label in ``data["storage_data"]`` (e.g. ``"P_Capex"``).
    factors : list of float
        Multiplicative factors to apply.  ``1.0`` keeps the base value.

    Examples
    --------
    >>> StorageFactorSweep("P_Capex", [0.7, 0.8, 1.0])
    """

    param_name: str
    factors: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.factors:
            raise ValueError(
                f"StorageFactorSweep for '{self.param_name}' must have at least one factor."
            )


@dataclass
class TsSweep:
    """Descriptor for a time-series parameter sweep.

    Multiplies the numeric column of ``data[ts_key]`` by each factor.
    The column name is resolved automatically via the ``TS_KEY_TO_COLUMN``
    mapping in ``sdom.parametric.mutations``.

    Parameters
    ----------
    ts_key : str
        Key in the SDOM data dict (e.g. ``"load_data"``, ``"large_hydro_max"``).
    factors : list of float
        Multiplicative scaling factors.  ``1.0`` keeps the base series.

    Examples
    --------
    >>> TsSweep("load_data", [0.9, 1.0, 1.1])
    """

    ts_key: str
    factors: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.factors:
            raise ValueError(
                f"TsSweep for '{self.ts_key}' must have at least one factor."
            )
