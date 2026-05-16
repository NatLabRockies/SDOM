"""Lock the canonical ``Data/zonal_test/`` fixture invariants.

The fixture pairs ``no_exchange_run_of_river`` (area A1) with the monthly-
hydro-budget folder (area A2), then **drops A2's hydro budget bounds** so
the global ``RunOfRiverFormulation`` is satisfied for both areas (locked
2026-05-08 decision; option (b) in the fixture-finalization plan).

These invariants exist so a future regeneration of the fixture cannot
silently re-introduce hydro budgets and break the AT path's assumptions.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "Data" / "zonal_test"


def test_fixture_directory_exists():
    assert FIXTURE_DIR.is_dir(), f"missing fixture directory: {FIXTURE_DIR}"


def test_hydro_formulation_is_run_of_river():
    forms = pd.read_csv(FIXTURE_DIR / "formulations.csv")
    hydro_row = forms.loc[forms["Component"] == "Hydro"]
    assert len(hydro_row) == 1, "expected exactly one Hydro row"
    assert hydro_row["Formulation"].iloc[0] == "RunOfRiverFormulation"


def test_no_hydro_budget_files_shipped():
    """Option (b) requires that A2's budget bounds be dropped."""
    forbidden = ["lahy_max_hourly.csv", "lahy_min_hourly.csv"]
    present = [f.name for f in FIXTURE_DIR.iterdir() if f.is_file()]
    for name in forbidden:
        assert name not in present, (
            f"{name} must NOT be shipped under the RoR-only fixture "
            "(see scripts/build_zonal_test_fixture.py docstring)."
        )
    # And no year-suffixed variants either.
    for name in present:
        assert not name.startswith("lahy_max_hourly"), name
        assert not name.startswith("lahy_min_hourly"), name


def test_lahy_hourly_has_both_areas():
    df = pd.read_csv(FIXTURE_DIR / "lahy_hourly.csv")
    cols = list(df.columns)
    assert "LargeHydro@A1@" in cols
    assert "LargeHydro@A2@" in cols


def test_areas_csv_lists_a1_and_a2():
    areas = pd.read_csv(FIXTURE_DIR / "areas.csv")
    assert sorted(areas["area_id"].tolist()) == ["A1", "A2"]


def test_network_is_area_transportation():
    forms = pd.read_csv(FIXTURE_DIR / "formulations.csv")
    net_row = forms.loc[forms["Component"] == "Network"]
    assert len(net_row) == 1
    assert net_row["Formulation"].iloc[0] == "AreaTransportationModelNetwork"


def test_imports_exports_are_not_modeled():
    forms = pd.read_csv(FIXTURE_DIR / "formulations.csv")
    for comp in ("Imports", "Exports"):
        row = forms.loc[forms["Component"] == comp]
        assert len(row) == 1, f"missing {comp} row"
        assert row["Formulation"].iloc[0] == "NotModel", (
            f"{comp} formulation must be NotModel under the canonical fixture"
        )
