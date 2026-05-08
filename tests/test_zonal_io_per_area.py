"""Tests for the per-area data parsing in `io_manager` (zonal commit #4).

Covers:

- The private `_parse_area_tagged_header` helper.
- Wide-CSV `@area_id@` header tag parsing for legacy and zonal layouts.
- Row-oriented `area_id` column support for ``CapSolar.csv`` / ``CapWind.csv``.
- ``areas.csv`` loader (synthesized default and explicit list-of-dicts).
- Validation rules: mixed legacy/tagged columns, stray ``@`` characters,
  unknown ``area_id`` references, duplicate ``sc_gid`` across areas.
- The new ``per_area_*`` keys are populated for legacy folders and survive
  ``copy.deepcopy`` (parametric module deep-copies ``data`` per worker).

The tests build minimal in-memory zonal CSV folders inside ``tmp_path``.
A full ``Data/zonal_test`` fixture lands in commit #12.
"""

from __future__ import annotations

import copy
import pickle
import shutil
from pathlib import Path

import pandas as pd
import pytest

from sdom import load_data
from sdom.constants import AREA_TAG_DELIMITER, DEFAULT_AREA_ID
from sdom.io_manager import _parse_area_tagged_header

_LEGACY_FOLDER = "Data/no_exchange_run_of_river"


# ---------------------------------------------------------------------------
# _parse_area_tagged_header
# ---------------------------------------------------------------------------


def test_parse_header_returns_none_area_when_untagged():
    entity, area = _parse_area_tagged_header("Load")
    assert entity == "Load"
    assert area is None


def test_parse_header_extracts_entity_and_area():
    entity, area = _parse_area_tagged_header("Load@A1@")
    assert entity == "Load"
    assert area == "A1"


def test_parse_header_rejects_stray_at_sign():
    with pytest.raises(ValueError, match="area tag"):
        _parse_area_tagged_header("Load@A1")


def test_parse_header_rejects_double_tags():
    with pytest.raises(ValueError, match="area tag"):
        _parse_area_tagged_header("Load@A1@@A2@")


def test_parse_header_rejects_lone_delimiter():
    with pytest.raises(ValueError, match="area tag"):
        _parse_area_tagged_header("Load@")


# ---------------------------------------------------------------------------
# Legacy folder: per_area_* views are synthesized with DEFAULT_AREA_ID
# ---------------------------------------------------------------------------

_PER_AREA_KEYS = (
    "per_area_demand",
    "per_area_pv_plants",
    "per_area_wind_plants",
    "per_area_balancing_units",
    "per_area_storage",
    "per_area_hydro",
    "per_area_nuclear",
    "per_area_other_renewables",
    "per_area_capacity_factors_pv",
    "per_area_capacity_factors_wind",
)


def test_legacy_folder_populates_per_area_keys_with_default_area():
    data = load_data(_LEGACY_FOLDER)

    assert data["areas"] == [
        {"area_id": DEFAULT_AREA_ID, "description": "Default area"}
    ]

    for key in _PER_AREA_KEYS:
        assert key in data, f"Missing per-area key: {key}"
        assert isinstance(data[key], dict)
        assert list(data[key].keys()) == [DEFAULT_AREA_ID], (
            f"Legacy folder must produce a single '{DEFAULT_AREA_ID}' area for {key}."
        )


def test_legacy_folder_per_area_demand_matches_global():
    data = load_data(_LEGACY_FOLDER)
    per_area_demand = data["per_area_demand"][DEFAULT_AREA_ID]
    assert isinstance(per_area_demand, pd.DataFrame)
    # Same number of rows as the global hourly load table.
    assert len(per_area_demand) == len(data["load_data"])


def test_legacy_folder_per_area_pv_matches_global_cap_solar():
    data = load_data(_LEGACY_FOLDER)
    per_area_pv = data["per_area_pv_plants"][DEFAULT_AREA_ID]
    assert isinstance(per_area_pv, pd.DataFrame)
    assert len(per_area_pv) == len(data["cap_solar"])


def test_legacy_folder_per_area_keys_are_pickleable():
    """`parametric` deep-copies `data` per worker; per-area keys must survive."""
    data = load_data(_LEGACY_FOLDER)
    payload = {key: data[key] for key in _PER_AREA_KEYS if key in data}
    payload["areas"] = data["areas"]
    blob = pickle.dumps(payload)
    restored = pickle.loads(blob)
    assert set(restored) == set(payload)
    deep = copy.deepcopy(payload)
    assert set(deep) == set(payload)


# ---------------------------------------------------------------------------
# Zonal fixtures (built on the fly inside tmp_path)
# ---------------------------------------------------------------------------


def _copy_legacy_to(tmp_path: Path) -> Path:
    """Copy the legacy data folder into ``tmp_path/data`` and return the path."""
    dst = tmp_path / "data"
    shutil.copytree(_LEGACY_FOLDER, dst)
    return dst


def _resolve(folder: Path, basename: str) -> Path:
    """Locate the actual filename for ``basename`` inside ``folder`` (year suffixes)."""
    base_norm = basename.replace("_", "").replace(".csv", "").lower()
    for path in folder.iterdir():
        if not path.name.lower().endswith(".csv"):
            continue
        norm = path.stem.replace("_", "").lower()
        if norm.startswith(base_norm):
            return path
    raise FileNotFoundError(f"No file matching {basename} in {folder}")


def _write_areas(folder: Path, area_ids: list[str]) -> None:
    rows = [{"area_id": a, "description": f"Area {a}"} for a in area_ids]
    pd.DataFrame(rows).to_csv(folder / "areas.csv", index=False)


def _make_zonal_load(folder: Path, areas: list[str]) -> None:
    """Replace the hourly load file with a zonal version (``Load@A@``)."""
    target = _resolve(folder, "Load_hourly.csv")
    legacy = pd.read_csv(target)
    key = legacy.columns[0]
    out = pd.DataFrame({key: legacy[key]})
    for area in areas:
        # Equally split the legacy load across areas to preserve totals.
        out[f"Load{AREA_TAG_DELIMITER}{area}{AREA_TAG_DELIMITER}"] = (
            legacy[legacy.columns[1]] / len(areas)
        )
    out.to_csv(target, index=False)


# ---------------------------------------------------------------------------
# Wide-CSV behavior
# ---------------------------------------------------------------------------


def test_wide_csv_zonal_load_splits_by_area(tmp_path):
    folder = _copy_legacy_to(tmp_path)
    _write_areas(folder, ["A1", "A2"])
    _make_zonal_load(folder, ["A1", "A2"])

    data = load_data(str(folder))

    assert {a["area_id"] for a in data["areas"]} == {"A1", "A2"}
    assert set(data["per_area_demand"]) == {"A1", "A2"}
    a1 = data["per_area_demand"]["A1"]
    a2 = data["per_area_demand"]["A2"]
    assert "Load" in a1.columns
    assert "Load" in a2.columns
    # Tag should be stripped from column names.
    assert AREA_TAG_DELIMITER not in "".join(a1.columns)


def test_wide_csv_synthesizes_areas_when_areas_csv_absent(tmp_path):
    folder = _copy_legacy_to(tmp_path)
    _make_zonal_load(folder, ["A1", "A2"])
    # No areas.csv → must be synthesized from observed tags.
    assert not (folder / "areas.csv").exists()

    data = load_data(str(folder))

    assert {a["area_id"] for a in data["areas"]} >= {"A1", "A2"}
    assert set(data["per_area_demand"]) == {"A1", "A2"}


def test_wide_csv_mixed_legacy_and_tagged_columns_errors(tmp_path):
    folder = _copy_legacy_to(tmp_path)
    _write_areas(folder, ["A1"])
    target = _resolve(folder, "Load_hourly.csv")
    legacy = pd.read_csv(target)
    key = legacy.columns[0]
    pd.DataFrame(
        {
            key: legacy[key],
            "Load": legacy[legacy.columns[1]],
            f"Load{AREA_TAG_DELIMITER}A1{AREA_TAG_DELIMITER}": legacy[
                legacy.columns[1]
            ],
        }
    ).to_csv(target, index=False)

    with pytest.raises(ValueError, match="mixes"):
        load_data(str(folder))


def test_wide_csv_stray_at_in_header_errors(tmp_path):
    folder = _copy_legacy_to(tmp_path)
    _write_areas(folder, ["A1"])
    target = _resolve(folder, "Load_hourly.csv")
    legacy = pd.read_csv(target)
    key = legacy.columns[0]
    pd.DataFrame(
        {
            key: legacy[key],
            f"Load{AREA_TAG_DELIMITER}A1": legacy[legacy.columns[1]],
        }
    ).to_csv(target, index=False)

    with pytest.raises(ValueError, match="area tag"):
        load_data(str(folder))


def test_wide_csv_tag_unknown_area_errors(tmp_path):
    folder = _copy_legacy_to(tmp_path)
    _write_areas(folder, ["A1"])  # only A1 declared
    _make_zonal_load(folder, ["A1", "GHOST"])  # GHOST not in areas.csv

    with pytest.raises(ValueError, match="GHOST"):
        load_data(str(folder))


# ---------------------------------------------------------------------------
# Row-oriented behavior (CapSolar / CapWind)
# ---------------------------------------------------------------------------


def test_row_csv_legacy_cap_solar_tagged_as_default(tmp_path):
    folder = _copy_legacy_to(tmp_path)
    data = load_data(str(folder))

    assert set(data["per_area_pv_plants"]) == {DEFAULT_AREA_ID}
    pv_default = data["per_area_pv_plants"][DEFAULT_AREA_ID]
    assert "sc_gid" in pv_default.columns


def test_row_csv_zonal_cap_solar_splits_by_area_id(tmp_path):
    folder = _copy_legacy_to(tmp_path)
    _write_areas(folder, ["A1", "A2"])

    target = _resolve(folder, "CapSolar.csv")
    cap = pd.read_csv(target)
    half = len(cap) // 2
    cap["area_id"] = ["A1"] * half + ["A2"] * (len(cap) - half)
    cap.to_csv(target, index=False)

    data = load_data(str(folder))

    assert set(data["per_area_pv_plants"]) == {"A1", "A2"}
    a1 = data["per_area_pv_plants"]["A1"]
    a2 = data["per_area_pv_plants"]["A2"]
    assert (a1["area_id"] == "A1").all()
    assert (a2["area_id"] == "A2").all()
    assert len(a1) + len(a2) == len(cap)


def test_row_csv_duplicate_sc_gid_across_areas_errors(tmp_path):
    folder = _copy_legacy_to(tmp_path)
    _write_areas(folder, ["A1", "A2"])

    target = _resolve(folder, "CapSolar.csv")
    cap = pd.read_csv(target)
    # Force every sc_gid to be the same value, then assign half to A1, half to A2.
    cap["sc_gid"] = "DUPLICATE_PLANT"
    half = len(cap) // 2
    cap["area_id"] = ["A1"] * half + ["A2"] * (len(cap) - half)
    cap.to_csv(target, index=False)

    with pytest.raises(ValueError, match="globally unique"):
        load_data(str(folder))


# ---------------------------------------------------------------------------
# areas.csv loader
# ---------------------------------------------------------------------------


def test_areas_csv_absent_synthesizes_default_area():
    data = load_data(_LEGACY_FOLDER)
    assert data["areas"] == [
        {"area_id": DEFAULT_AREA_ID, "description": "Default area"}
    ]


def test_areas_csv_present_is_loaded_as_list_of_dicts(tmp_path):
    folder = _copy_legacy_to(tmp_path)
    _write_areas(folder, ["A1", "A2"])
    _make_zonal_load(folder, ["A1", "A2"])

    data = load_data(str(folder))

    assert isinstance(data["areas"], list)
    assert all(isinstance(item, dict) for item in data["areas"])
    assert {a["area_id"] for a in data["areas"]} == {"A1", "A2"}
    assert all("description" in a for a in data["areas"])
