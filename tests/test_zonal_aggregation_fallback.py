"""Tests for the aggregation fallback (commit #6).

Covers PRD §4.6: when a multi-area input folder is loaded with
``Network=CopperPlateNetwork``, ``load_data`` collapses every per-area
entity into a single synthetic ``default`` area. Hourly profiles are
summed; import / export prices are aggregated as a capacity-weighted
average; row-oriented per-device tables shed their ``area_id`` column;
the storage table sheds its ``@area_id@`` header tags. Transmission
files are dropped with a ``WARNING``.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pandas as pd
import pytest

from sdom import load_data
from sdom.constants import DEFAULT_AREA_ID


_ZONAL_FIXTURE = "Data/zonal_test"


def _copy_fixture_to(tmp_path: Path) -> Path:
    """Copy the canonical zonal fixture into ``tmp_path/data``."""
    dst = tmp_path / "data"
    shutil.copytree(_ZONAL_FIXTURE, dst)
    return dst


def _flip_to_copper_plate(folder: Path) -> None:
    """Rewrite ``formulations.csv`` so the Network row is CopperPlate."""
    csv_path = folder / "formulations.csv"
    df = pd.read_csv(csv_path)
    df.loc[
        df["Component"].str.lower() == "network", "Formulation"
    ] = "CopperPlateNetwork"
    df.to_csv(csv_path, index=False)


def _dedupe_storage_techs(folder: Path) -> None:
    """Rename storage tech columns so they remain unique after tag stripping.

    The canonical fixture intentionally reuses tech ids across areas
    (``Li-Ion@A1@`` and ``Li-Ion@A2@``). To exercise the happy-path
    aggregation we suffix each id with its area before stripping the
    ``@area_id@`` tag.
    """
    csv_path = folder / "StorageData.csv"
    df = pd.read_csv(csv_path, index_col=0)
    new_cols = []
    for col in df.columns:
        # Header shape: "<entity>@<area>@"
        if "@" in col:
            entity, area_with_tail = col.split("@", 1)
            area = area_with_tail.rstrip("@")
            new_cols.append(f"{entity}-{area}@{area}@")
        else:
            new_cols.append(col)
    df.columns = new_cols
    df.to_csv(csv_path)


def _zonal_copper_plate_folder(tmp_path: Path, *, dedupe_storage: bool = True) -> Path:
    folder = _copy_fixture_to(tmp_path)
    _flip_to_copper_plate(folder)
    if dedupe_storage:
        _dedupe_storage_techs(folder)
    return folder


# ---------------------------------------------------------------------------
# Happy path — areas collapsed, hourly profiles summed
# ---------------------------------------------------------------------------


def test_areas_collapse_to_single_default(tmp_path):
    folder = _zonal_copper_plate_folder(tmp_path)
    data = load_data(str(folder))

    assert data["network_formulation"] == "CopperPlateNetwork"
    assert data["areas"] == [
        {"area_id": DEFAULT_AREA_ID, "description": "Aggregated default area"}
    ]


def test_load_data_summed_across_areas(tmp_path):
    # Read the original per-area profile straight from the fixture.
    src = pd.read_csv(Path(_ZONAL_FIXTURE) / "Load_hourly.csv")
    expected = src["Load@A1@"] + src["Load@A2@"]

    folder = _zonal_copper_plate_folder(tmp_path)
    data = load_data(str(folder))

    load_df = data["load_data"]
    assert list(load_df.columns)[1:] == ["Load"]
    assert load_df.shape == (8760, 2)
    pd.testing.assert_series_equal(
        load_df["Load"].reset_index(drop=True),
        expected.reset_index(drop=True),
        check_names=False,
    )


def test_nuclear_and_other_renewables_summed(tmp_path):
    nucl_src = pd.read_csv(Path(_ZONAL_FIXTURE) / "Nucl_hourly.csv")
    otre_src = pd.read_csv(Path(_ZONAL_FIXTURE) / "otre_hourly.csv")
    expected_nuc = nucl_src["Nuclear@A1@"] + nucl_src["Nuclear@A2@"]
    expected_otr = otre_src["OtherRenewables@A1@"] + otre_src["OtherRenewables@A2@"]

    folder = _zonal_copper_plate_folder(tmp_path)
    data = load_data(str(folder))

    pd.testing.assert_series_equal(
        data["nuclear_data"].iloc[:, 1].reset_index(drop=True),
        expected_nuc.reset_index(drop=True),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        data["other_renewables_data"].iloc[:, 1].reset_index(drop=True),
        expected_otr.reset_index(drop=True),
        check_names=False,
    )


# ---------------------------------------------------------------------------
# Row-oriented tables: drop area_id column, keep all rows
# ---------------------------------------------------------------------------


def test_cap_solar_drops_area_id_keeps_all_rows(tmp_path):
    src_rows = len(pd.read_csv(Path(_ZONAL_FIXTURE) / "CapSolar.csv"))
    folder = _zonal_copper_plate_folder(tmp_path)
    data = load_data(str(folder))

    assert "area_id" not in data["cap_solar"].columns
    assert len(data["cap_solar"]) == src_rows


def test_thermal_data_drops_area_id_keeps_all_rows(tmp_path):
    src_rows = len(pd.read_csv(Path(_ZONAL_FIXTURE) / "Data_BalancingUnits.csv"))
    folder = _zonal_copper_plate_folder(tmp_path)
    data = load_data(str(folder))

    assert "area_id" not in data["thermal_data"].columns
    assert len(data["thermal_data"]) == src_rows


# ---------------------------------------------------------------------------
# Storage: tag stripping + collision detection
# ---------------------------------------------------------------------------


def test_storage_tags_stripped_after_dedupe(tmp_path):
    folder = _zonal_copper_plate_folder(tmp_path)
    data = load_data(str(folder))

    storage = data["storage_data"]
    # No '@' should survive in any column header.
    assert all("@" not in c for c in storage.columns)
    # Eight original techs (4 per area) become 8 unique techs after the
    # rename helper appended the area suffix.
    assert len(storage.columns) == 8
    # STORAGE_SET_J_TECHS must be refreshed from the new headers.
    assert data["STORAGE_SET_J_TECHS"] == list(storage.columns)


def test_storage_collision_raises(tmp_path):
    """Same tech id in two areas -> ERROR per PRD §4.6."""
    folder = _zonal_copper_plate_folder(tmp_path, dedupe_storage=False)
    with pytest.raises(ValueError, match="storage tech identifiers collide"):
        load_data(str(folder))


# ---------------------------------------------------------------------------
# Topology dropped + WARNING emitted
# ---------------------------------------------------------------------------


def test_lines_dropped_and_warning_logged(tmp_path, caplog):
    folder = _zonal_copper_plate_folder(tmp_path)
    with caplog.at_level(logging.WARNING):
        data = load_data(str(folder))

    assert data["lines"] == []
    assert data["line_cap_ft"].empty
    assert data["line_cap_tf"].empty
    assert any(
        "Aggregation fallback" in record.message
        and "transmission" in record.message.lower()
        for record in caplog.records
    )


def test_aggregation_warning_logged(tmp_path, caplog):
    folder = _zonal_copper_plate_folder(tmp_path)
    with caplog.at_level(logging.WARNING):
        load_data(str(folder))

    assert any(
        "Aggregating" in record.message and "default" in record.message
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# Per-area views are rebuilt to a single-key dict
# ---------------------------------------------------------------------------


def test_per_area_views_collapsed_to_single_key(tmp_path):
    folder = _zonal_copper_plate_folder(tmp_path)
    data = load_data(str(folder))

    for key in (
        "per_area_demand",
        "per_area_nuclear",
        "per_area_other_renewables",
        "per_area_pv_plants",
        "per_area_wind_plants",
        "per_area_balancing_units",
        "per_area_storage",
        "per_area_capacity_factors_pv",
        "per_area_capacity_factors_wind",
    ):
        assert list(data[key].keys()) == [DEFAULT_AREA_ID], (
            f"{key} should expose only the synthetic default area"
        )


# ---------------------------------------------------------------------------
# Legacy single-area folders are NOT aggregated (regression guard)
# ---------------------------------------------------------------------------


def test_legacy_folder_not_aggregated(tmp_path, caplog):
    """``no_exchange_run_of_river`` already has |areas| == 1 → no warning."""
    with caplog.at_level(logging.WARNING):
        data = load_data("Data/no_exchange_run_of_river")

    assert data["network_formulation"] == "CopperPlateNetwork"
    assert len(data["areas"]) == 1
    assert not any(
        "Aggregation fallback" in record.message for record in caplog.records
    )
    assert not any(
        "Aggregating" in record.message and "default" in record.message
        for record in caplog.records
    )
