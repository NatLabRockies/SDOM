"""Aggregate collected DataFrames and dictionaries without model access."""


import pandas as pd

_GENERATION_ADDITIVE_COLUMNS = (
    "Solar PV Generation (MW)",
    "Solar PV Curtailment (MW)",
    "Wind Generation (MW)",
    "Wind Curtailment (MW)",
    "All Thermal Generation (MW)",
    "Hydro Generation (MW)",
    "Nuclear Generation (MW)",
    "Other Renewables Generation (MW)",
    "Imports (MW)",
    "Storage Charge/Discharge (MW)",
    "Exports (MW)",
    "Load (MW)",
)


def _aggregate_zonal_generation_by_hour(generation_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-area generation rows into one system row per hour.

    Missing dispatch columns and missing values represent zero dispatch. Net
    load follows ``formulations_system.net_load_rule``: load less available
    solar and wind (generation plus curtailment), nuclear, other renewables,
    and hydro generation.
    """
    if generation_df.empty or "Hour" not in generation_df.columns:
        return pd.DataFrame()

    values = generation_df.reindex(columns=_GENERATION_ADDITIVE_COLUMNS).apply(
        pd.to_numeric, errors="coerce"
    ).fillna(0.0)
    values.insert(0, "Hour", generation_df["Hour"].to_numpy())
    system_df = values.groupby("Hour", as_index=False, sort=True).sum()

    if "Scenario" in generation_df.columns:
        scenarios = generation_df.groupby("Hour", sort=True)["Scenario"].first()
        system_df.insert(0, "Scenario", system_df["Hour"].map(scenarios))
    else:
        system_df.insert(0, "Scenario", "run")

    system_df["Net Load (MW)"] = (
        system_df["Load (MW)"]
        - system_df["Solar PV Generation (MW)"]
        - system_df["Solar PV Curtailment (MW)"]
        - system_df["Wind Generation (MW)"]
        - system_df["Wind Curtailment (MW)"]
        - system_df["Nuclear Generation (MW)"]
        - system_df["Other Renewables Generation (MW)"]
        - system_df["Hydro Generation (MW)"]
    )
    return system_df


def _merge_dict_sum(target: dict, source: dict) -> None:
    """Sum scalar values from ``source`` into ``target`` in-place.

    Numeric values are added; nested dicts are merged recursively.
    Used to aggregate per-area capacity / cost / generation dicts into the
    system-level rollups under the zonal path.

    Parameters
    ----------
    target : dict
        Destination dict (mutated).
    source : dict
        Per-area dict whose values are added to ``target``.
    """
    for key, val in source.items():
        if isinstance(val, dict):
            sub = target.setdefault(key, {})
            _merge_dict_sum(sub, val)
        elif isinstance(val, (int, float)):
            target[key] = target.get(key, 0.0) + float(val)
        else:
            # Non-numeric (e.g. nested list) — overwrite if absent.
            target.setdefault(key, val)
