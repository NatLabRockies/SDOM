"""Negative and defaulting tests for the Network formulation in `load_data`.

This file is grown commit-by-commit as the zonal io_manager refactor lands.
The current scope (commit #3) covers:

- Backward-compatible defaulting when `formulations.csv` lacks a `Network` row.
- Rejection of unknown `Network` formulation values.
- Acceptance of an explicit `CopperPlateNetwork` row (no log noise about default).
- Acceptance of an explicit `AreaTransportationModelNetwork` row (constant only;
  full data-loading wiring lands in later commits).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from sdom import load_data
from sdom.constants import DEFAULT_NETWORK_FORMULATION
from sdom.io_manager import get_formulation

# Reuse the existing run-of-river fixture as a clean baseline.
_LEGACY_FOLDER = "Data/no_exchange_run_of_river"


def _copy_to(tmp_path: Path) -> Path:
    """Copy the legacy data folder into ``tmp_path/data`` and return the path."""
    dst = tmp_path / "data"
    shutil.copytree(_LEGACY_FOLDER, dst)
    return dst


def _set_network_row(folder: Path, value: str | None) -> None:
    """Rewrite ``formulations.csv`` with a Network row set to ``value``.

    If ``value`` is ``None``, the Network row is removed entirely.
    """
    csv_path = folder / "formulations.csv"
    df = pd.read_csv(csv_path)
    df = df.loc[df["Component"].str.lower() != "network"].copy()
    if value is not None:
        df = pd.concat(
            [df, pd.DataFrame([{"Component": "Network", "Formulation": value}])],
            ignore_index=True,
        )
    df.to_csv(csv_path, index=False)


def test_load_data_defaults_network_when_row_absent(tmp_path, caplog):
    folder = _copy_to(tmp_path)
    _set_network_row(folder, None)

    with caplog.at_level("INFO"):
        data = load_data(str(folder))

    assert data["network_formulation"] == DEFAULT_NETWORK_FORMULATION
    assert any(
        "Network" in record.message and "default" in record.message.lower()
        for record in caplog.records
    ), "An INFO log explaining the default should be emitted."


def test_load_data_accepts_explicit_copper_plate(tmp_path):
    folder = _copy_to(tmp_path)
    _set_network_row(folder, "CopperPlateNetwork")

    data = load_data(str(folder))
    assert data["network_formulation"] == "CopperPlateNetwork"


def test_load_data_accepts_explicit_area_transportation(tmp_path):
    """AT formulation requires topology files (commit #5 wired this up)."""
    # Use the zonal fixture, which already ships with interconnections.csv +
    # LineCap_FT.csv + LineCap_TF.csv.
    src = Path("Data/zonal_test")
    folder = tmp_path / "data"
    shutil.copytree(src, folder)
    df = pd.read_csv(folder / "formulations.csv")
    df.loc[df["Component"].str.lower() == "network", "Formulation"] = (
        "AreaTransportationModelNetwork"
    )
    df.to_csv(folder / "formulations.csv", index=False)

    data = load_data(str(folder))
    assert data["network_formulation"] == "AreaTransportationModelNetwork"
    assert len(data["lines"]) == 1


def test_load_data_rejects_unknown_network_value(tmp_path):
    folder = _copy_to(tmp_path)
    _set_network_row(folder, "GhostMeshNetwork")

    with pytest.raises(ValueError, match="GhostMeshNetwork"):
        load_data(str(folder))


def test_get_formulation_default_keyword_returns_default():
    df = pd.DataFrame(
        [{"Component": "Hydro", "Formulation": "RunOfRiverFormulation"}]
    )
    data = {"formulations": df}

    assert (
        get_formulation(data, component="Network", default="CopperPlateNetwork")
        == "CopperPlateNetwork"
    )


def test_get_formulation_no_default_raises_on_missing():
    df = pd.DataFrame(
        [{"Component": "Hydro", "Formulation": "RunOfRiverFormulation"}]
    )
    data = {"formulations": df}

    with pytest.raises(IndexError):
        get_formulation(data, component="Network")
