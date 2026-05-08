"""Build the canonical 2-area zonal test fixture under ``Data/zonal_test/``.

This is a one-shot helper used to regenerate the `Data/zonal_test/` directory
from the two source legacy folders. The fixture is checked into the repo, so
this script normally does NOT need to be re-run.

Sources
-------
- ``A1`` = ``Data/no_exchange_run_of_river``        (year suffixes: 2050/2030/2019)
- ``A2`` = ``Data/no_exchange_monthly_hydro_budget_multiple_balancing_p50``
                                                    (year suffix: 2025)

Encodings produced (see PRD §2)
-------------------------------
- Encoding B (wide CSV ``@area_id@`` headers): Load_hourly, Nucl_hourly,
  otre_hourly, lahy_hourly, StorageData.
- Encoding A (row-oriented ``area_id`` column): CapSolar, CapWind,
  Data_BalancingUnits.
- Plant-keyed wide files (no area encoding): CFSolar, CFWind. Plant ids
  are globally unique across areas so no tagging is required.

Locked decisions
----------------
- Hydro = ``RunOfRiverFormulation`` globally (drop A2's lahy_max/lahy_min).
- Imports / Exports = ``NotModel`` globally (no Import_*/Export_* templates).
- Network = ``CopperPlateNetwork`` (commit #6 will introduce the aggregation
  fallback that handles |areas|>1 + CopperPlate; for now the per-area views
  populated by io_manager are validated by the new tests).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
A1_DIR = REPO_ROOT / "Data" / "no_exchange_run_of_river"
A2_DIR = REPO_ROOT / "Data" / "no_exchange_monthly_hydro_budget_multiple_balancing_p50"
OUT_DIR = REPO_ROOT / "Data" / "zonal_test"


def _read(path: Path, **kwargs) -> pd.DataFrame:
    return pd.read_csv(path, **kwargs)


def _tag(name: str, area: str) -> str:
    return f"{name}@{area}@"


def build() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ----- formulations.csv -------------------------------------------------
    formulations = pd.DataFrame(
        [
            ["Thermal", "NoRampsDispatchFormulation",
             "Thermal aggregations are dispatched without ramping constraints."],
            ["Hydro", "RunOfRiverFormulation",
             "Run-of-river: dispatch follows the hourly time series; "
             "no monthly/daily budget constraints (locked global choice)."],
            ["Imports", "NotModel",
             "Imports are not represented in this fixture (zonal_test)."],
            ["Exports", "NotModel",
             "Exports are not represented in this fixture (zonal_test)."],
            ["Network", "CopperPlateNetwork",
             "Single system-wide energy balance; aggregation fallback for "
             "|areas|>1 lands in commit #6."],
        ],
        columns=["Component", "Formulation", "Description"],
    )
    formulations.to_csv(OUT_DIR / "formulations.csv", index=False)

    # ----- areas.csv --------------------------------------------------------
    areas = pd.DataFrame(
        [
            ["A1", "Run-of-river hydro area (from no_exchange_run_of_river)"],
            ["A2", "Multiple balancing units area "
             "(from no_exchange_monthly_hydro_budget_multiple_balancing_p50)"],
        ],
        columns=["area_id", "description"],
    )
    areas.to_csv(OUT_DIR / "areas.csv", index=False)

    # ----- Wide hourly files (Encoding B) ----------------------------------
    wide_specs = [
        ("Load_hourly.csv", "Load_hourly_2050.csv", "Load_hourly_2025.csv", "Load"),
        ("Nucl_hourly.csv", "Nucl_hourly_2019.csv", "Nucl_hourly_2025.csv", "Nuclear"),
        ("otre_hourly.csv", "otre_hourly_2019.csv", "otre_hourly_2025.csv",
         "OtherRenewables"),
        ("lahy_hourly.csv", "lahy_hourly_2019.csv", "lahy_hourly_2025.csv", "LargeHydro"),
    ]
    for out_name, a1_name, a2_name, entity in wide_specs:
        df1 = _read(A1_DIR / a1_name)
        df2 = _read(A2_DIR / a2_name)
        key = df1.columns[0]  # "*Hour"
        # Both source files share an identical key column.
        out = pd.DataFrame({key: df1[key]})
        out[_tag(entity, "A1")] = df1[df1.columns[1]].values
        out[_tag(entity, "A2")] = df2[df2.columns[1]].values
        out.to_csv(OUT_DIR / out_name, index=False)

    # ----- StorageData.csv (Encoding B, indexed by Property) ---------------
    sd1 = _read(A1_DIR / "StorageData_2050.csv", index_col=0)
    sd2 = _read(A2_DIR / "StorageData_2025.csv", index_col=0)
    storage = pd.DataFrame(index=sd1.index)
    for tech in sd1.columns:
        storage[_tag(tech, "A1")] = sd1[tech]
    for tech in sd2.columns:
        storage[_tag(tech, "A2")] = sd2[tech]
    storage.index.name = sd1.index.name  # keep blank label as in source
    storage.to_csv(OUT_DIR / "StorageData.csv")

    # ----- CapSolar / CapWind (Encoding A) ---------------------------------
    for out_name, a1_name, a2_name in [
        ("CapSolar.csv", "CapSolar_2050.csv", "CapSolar_2025.csv"),
        ("CapWind.csv", "CapWind_2050.csv", "CapWind_2025.csv"),
    ]:
        df1 = _read(A1_DIR / a1_name)
        df2 = _read(A2_DIR / a2_name)
        df1 = df1.copy()
        df2 = df2.copy()
        df1["area_id"] = "A1"
        df2["area_id"] = "A2"
        # sc_gid must be globally unique. A1 uses integer ids (132876, ...)
        # and A2 uses "Nordeste" — no collisions, but we still verify.
        merged = pd.concat([df1, df2], ignore_index=True)
        if merged["sc_gid"].duplicated().any():
            dups = merged.loc[merged["sc_gid"].duplicated(keep=False), "sc_gid"].tolist()
            raise RuntimeError(f"sc_gid collisions in {out_name}: {dups}")
        merged.to_csv(OUT_DIR / out_name, index=False)

    # ----- CFSolar / CFWind (plant-keyed wide; no @ tag needed) ------------
    for out_name, a1_name, a2_name in [
        ("CFSolar.csv", "CFSolar_2050.csv", "CFSolar_2025.csv"),
        ("CFWind.csv", "CFWind_2050.csv", "CFWind_2025.csv"),
    ]:
        df1 = _read(A1_DIR / a1_name)
        df2 = _read(A2_DIR / a2_name)
        key = df1.columns[0]
        # Concatenate plant columns from both sources side-by-side; the time
        # key column is identical so we just take A1's.
        df2_no_key = df2.drop(columns=[key])
        out = pd.concat([df1, df2_no_key], axis=1)
        # Sanity: no duplicate plant column headers.
        if out.columns.duplicated().any():
            dups = out.columns[out.columns.duplicated()].tolist()
            raise RuntimeError(f"Plant id collisions in {out_name}: {dups}")
        out.to_csv(OUT_DIR / out_name, index=False)

    # ----- Zonal topology (commit #5) --------------------------------------
    # Single line A1 <-> A2, constant 500 MW capacity in both directions.
    # The fixture keeps Network=CopperPlateNetwork for now (commit #12 flips
    # it), so these files are present-but-not-required.
    interconnections = pd.DataFrame(
        [["L_A1_A2", "A1", "A2"]],
        columns=["line_id", "from_area", "to_area"],
    )
    interconnections.to_csv(OUT_DIR / "interconnections.csv", index=False)

    # Match the hour-key column name used by the other 8760-row CSVs ("*Hour").
    hour_key = _read(A1_DIR / "Load_hourly_2050.csv").columns[0]
    n_hours = 8760
    line_cap = pd.DataFrame({
        hour_key: range(1, n_hours + 1),
        "L_A1_A2": [500.0] * n_hours,
    })
    line_cap.to_csv(OUT_DIR / "LineCap_FT.csv", index=False)
    line_cap.to_csv(OUT_DIR / "LineCap_TF.csv", index=False)

    # ----- Data_BalancingUnits.csv (Encoding A) ----------------------------
    bu1 = _read(A1_DIR / "Data_BalancingUnits_2030(in).csv").copy()
    bu2 = _read(A2_DIR / "Data_BalancingUnits_2025.csv").copy()
    bu1["area_id"] = "A1"
    bu2["area_id"] = "A2"
    bu = pd.concat([bu1, bu2], ignore_index=True)
    if bu["Plant_id"].duplicated().any():
        dups = bu.loc[bu["Plant_id"].duplicated(keep=False), "Plant_id"].tolist()
        raise RuntimeError(f"Plant_id collisions in Data_BalancingUnits.csv: {dups}")
    bu.to_csv(OUT_DIR / "Data_BalancingUnits.csv", index=False)

    # ----- scalars.csv (use A1; A2 differs but tests only check parsing) ---
    scalars = _read(A1_DIR / "scalars.csv")
    scalars.to_csv(OUT_DIR / "scalars.csv", index=False)

    print(f"Built fixture at {OUT_DIR}")
    for path in sorted(OUT_DIR.iterdir()):
        if path.is_file():
            n_lines = sum(1 for _ in path.open(encoding="utf-8"))
            print(f"  {path.name:32s}  {n_lines:6d} lines")


if __name__ == "__main__":
    build()
