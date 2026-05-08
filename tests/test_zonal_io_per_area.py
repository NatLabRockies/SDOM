"""Tests for the per-area data parsing in `io_manager` (zonal commit #4 / #12).

Covers:

- The private `_parse_area_tagged_header` helper.
- Wide-CSV `@area_id@` header tag parsing for legacy and zonal layouts.
- Row-oriented `area_id` column support for ``CapSolar.csv`` / ``CapWind.csv``
  / ``Data_BalancingUnits.csv``.
- ``areas.csv`` loader (synthesized default and explicit list-of-dicts).
- Validation rules: mixed legacy/tagged columns, stray ``@`` characters,
  unknown ``area_id`` references, duplicate ``sc_gid`` across areas.
- The new ``per_area_*`` keys are populated for legacy folders and survive
  ``copy.deepcopy`` (parametric module deep-copies ``data`` per worker).

The zonal happy-path tests consume the canonical fixture committed at
``Data/zonal_test/`` (built by ``scripts/build_zonal_test_fixture.py`` from
the two existing legacy folders). The validation-error tests copy the
fixture into ``tmp_path`` and mutate one CSV in the copy.
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
_ZONAL_FIXTURE = "Data/zonal_test"


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
# Helpers for tmp_path-based mutation tests
# ---------------------------------------------------------------------------


def _copy_fixture_to(tmp_path: Path) -> Path:
    """Copy the canonical zonal fixture into ``tmp_path/data``.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest-provided temporary directory.

    Returns
    -------
    pathlib.Path
        Path to the copied fixture root, suitable for ``load_data``.
    """
    dst = tmp_path / "data"
    shutil.copytree(_ZONAL_FIXTURE, dst)
    return dst


def _rewrite_csv_header(path: Path, replacements: dict) -> None:
    """Replace exact column-name strings in a CSV header (line 1) only.

    Parameters
    ----------
    path : pathlib.Path
        CSV file to mutate in place.
    replacements : dict
        Mapping of ``old_column_name -> new_column_name``. Each key must
        appear exactly once on the header line.

    Raises
    ------
    AssertionError
        If any replacement key is not found in the header.
    """
    text = path.read_text(encoding="utf-8")
    header, _, rest = text.partition("\n")
    cols = header.split(",")
    pending = dict(replacements)
    for i, col in enumerate(cols):
        if col in pending:
            cols[i] = pending.pop(col)
    if pending:
        raise AssertionError(
            f"Replacement keys not found in {path.name}: {list(pending)}"
        )
    path.write_text(",".join(cols) + "\n" + rest, encoding="utf-8")


# ---------------------------------------------------------------------------
# Zonal happy path — read directly from Data/zonal_test/
# ---------------------------------------------------------------------------


def test_areas_csv_present_is_loaded_as_list_of_dicts():
    data = load_data(_ZONAL_FIXTURE)

    assert isinstance(data["areas"], list)
    assert all(isinstance(item, dict) for item in data["areas"])
    assert {a["area_id"] for a in data["areas"]} == {"A1", "A2"}
    assert all("description" in a for a in data["areas"])


def test_wide_csv_zonal_load_splits_by_area():
    data = load_data(_ZONAL_FIXTURE)

    assert set(data["per_area_demand"]) == {"A1", "A2"}
    a1 = data["per_area_demand"]["A1"]
    a2 = data["per_area_demand"]["A2"]
    assert "Load" in a1.columns
    assert "Load" in a2.columns
    # Tag must be stripped from per-area column names.
    assert AREA_TAG_DELIMITER not in "".join(a1.columns)
    assert AREA_TAG_DELIMITER not in "".join(a2.columns)
    # Both per-area frames have the full hourly horizon.
    assert len(a1) == len(a2) == 8760


def test_wide_csv_zonal_nuclear_splits_by_area():
    data = load_data(_ZONAL_FIXTURE)
    per_area = data["per_area_nuclear"]
    assert set(per_area) == {"A1", "A2"}
    assert "Nuclear" in per_area["A1"].columns
    assert "Nuclear" in per_area["A2"].columns


def test_wide_csv_zonal_other_renewables_splits_by_area():
    data = load_data(_ZONAL_FIXTURE)
    per_area = data["per_area_other_renewables"]
    assert set(per_area) == {"A1", "A2"}
    assert "OtherRenewables" in per_area["A1"].columns


def test_wide_csv_zonal_hydro_splits_by_area():
    data = load_data(_ZONAL_FIXTURE)
    per_area = data["per_area_hydro"]
    assert set(per_area) == {"A1", "A2"}
    # Run-of-river formulation → only the LargeHydro series; no max/min merge.
    assert "LargeHydro" in per_area["A1"].columns
    assert "LargeHydro" in per_area["A2"].columns


def test_wide_csv_zonal_storage_splits_by_area():
    data = load_data(_ZONAL_FIXTURE)
    per_area = data["per_area_storage"]
    assert set(per_area) == {"A1", "A2"}
    # Tech ids may repeat across areas because @area_id@ disambiguates them
    # in the source file; per-area frames carry the untagged tech ids.
    expected_techs = {"Li-Ion", "CAES", "PHS", "H2"}
    assert set(per_area["A1"].columns) == expected_techs
    assert set(per_area["A2"].columns) == expected_techs
    # Property index preserved on each per-area slice.
    assert "Coupled" in per_area["A1"].index
    assert "Coupled" in per_area["A2"].index


def test_row_csv_zonal_cap_solar_splits_by_area_id():
    data = load_data(_ZONAL_FIXTURE)
    per_area = data["per_area_pv_plants"]
    assert set(per_area) == {"A1", "A2"}
    assert (per_area["A1"]["area_id"] == "A1").all()
    assert (per_area["A2"]["area_id"] == "A2").all()
    # 100 reV plants in A1, single ``Nordeste`` plant in A2 (see
    # build_zonal_test_fixture.py).
    assert len(per_area["A1"]) == 100
    assert len(per_area["A2"]) == 1


def test_row_csv_zonal_cap_wind_splits_by_area_id():
    data = load_data(_ZONAL_FIXTURE)
    per_area = data["per_area_wind_plants"]
    assert set(per_area) == {"A1", "A2"}
    assert (per_area["A1"]["area_id"] == "A1").all()
    assert (per_area["A2"]["area_id"] == "A2").all()
    assert len(per_area["A1"]) == 100
    assert len(per_area["A2"]) == 1


def test_row_csv_zonal_balancing_units_splits_by_area_id():
    data = load_data(_ZONAL_FIXTURE)
    per_area = data["per_area_balancing_units"]
    assert set(per_area) == {"A1", "A2"}
    assert (per_area["A1"]["area_id"] == "A1").all()
    assert (per_area["A2"]["area_id"] == "A2").all()
    # 2 thermal aggregations in A1 (83_GAS, 83_Coal); 13 in A2.
    assert len(per_area["A1"]) == 2
    assert len(per_area["A2"]) == 13
    assert {"Plant_id", "MaxCapacity"}.issubset(per_area["A1"].columns)


def test_capacity_factors_pv_resolved_via_plant_join():
    data = load_data(_ZONAL_FIXTURE)
    cf = data["per_area_capacity_factors_pv"]
    cap = data["per_area_pv_plants"]
    assert set(cf) == {"A1", "A2"}
    # Time key + plant columns; #plant cols matches the per-area cap table.
    for area in ("A1", "A2"):
        plant_ids = set(cap[area]["sc_gid"].astype(str))
        cf_plant_cols = set(cf[area].columns[1:].astype(str))
        assert cf_plant_cols == plant_ids


def test_capacity_factors_wind_resolved_via_plant_join():
    data = load_data(_ZONAL_FIXTURE)
    cf = data["per_area_capacity_factors_wind"]
    cap = data["per_area_wind_plants"]
    assert set(cf) == {"A1", "A2"}
    for area in ("A1", "A2"):
        plant_ids = set(cap[area]["sc_gid"].astype(str))
        cf_plant_cols = set(cf[area].columns[1:].astype(str))
        assert cf_plant_cols == plant_ids


# ---------------------------------------------------------------------------
# areas.csv synthesis (legacy + zonal-without-areas.csv)
# ---------------------------------------------------------------------------


def test_areas_csv_absent_synthesizes_default_area():
    data = load_data(_LEGACY_FOLDER)
    assert data["areas"] == [
        {"area_id": DEFAULT_AREA_ID, "description": "Default area"}
    ]


def test_wide_csv_synthesizes_areas_when_areas_csv_absent(tmp_path):
    folder = _copy_fixture_to(tmp_path)
    (folder / "areas.csv").unlink()

    data = load_data(str(folder))

    assert {a["area_id"] for a in data["areas"]} == {"A1", "A2"}
    assert set(data["per_area_demand"]) == {"A1", "A2"}


# ---------------------------------------------------------------------------
# Legacy CapSolar (no area_id column) → DEFAULT_AREA_ID
# ---------------------------------------------------------------------------


def test_row_csv_legacy_cap_solar_tagged_as_default():
    data = load_data(_LEGACY_FOLDER)

    assert set(data["per_area_pv_plants"]) == {DEFAULT_AREA_ID}
    pv_default = data["per_area_pv_plants"][DEFAULT_AREA_ID]
    assert "sc_gid" in pv_default.columns


# ---------------------------------------------------------------------------
# Validation errors — mutate a copy of Data/zonal_test/
# ---------------------------------------------------------------------------


def test_wide_csv_mixed_legacy_and_tagged_columns_errors(tmp_path):
    folder = _copy_fixture_to(tmp_path)
    target = folder / "Load_hourly.csv"
    # Drop the @A2@ tag so the file mixes one tagged and one untagged column.
    _rewrite_csv_header(
        target,
        {f"Load{AREA_TAG_DELIMITER}A2{AREA_TAG_DELIMITER}": "Load"},
    )

    with pytest.raises(ValueError, match="mixes"):
        load_data(str(folder))


def test_wide_csv_stray_at_in_header_errors(tmp_path):
    folder = _copy_fixture_to(tmp_path)
    target = folder / "Load_hourly.csv"
    # Strip the trailing @ → header becomes "Load@A2" (stray delimiter).
    _rewrite_csv_header(
        target,
        {
            f"Load{AREA_TAG_DELIMITER}A2{AREA_TAG_DELIMITER}":
                f"Load{AREA_TAG_DELIMITER}A2",
        },
    )

    with pytest.raises(ValueError, match="area tag"):
        load_data(str(folder))


def test_wide_csv_tag_unknown_area_errors(tmp_path):
    folder = _copy_fixture_to(tmp_path)
    target = folder / "Load_hourly.csv"
    # Reference an undeclared area_id (areas.csv only declares A1/A2).
    _rewrite_csv_header(
        target,
        {
            f"Load{AREA_TAG_DELIMITER}A2{AREA_TAG_DELIMITER}":
                f"Load{AREA_TAG_DELIMITER}GHOST{AREA_TAG_DELIMITER}",
        },
    )

    with pytest.raises(ValueError, match="GHOST"):
        load_data(str(folder))


def test_row_csv_duplicate_sc_gid_across_areas_errors(tmp_path):
    folder = _copy_fixture_to(tmp_path)
    target = folder / "CapSolar.csv"
    cap = pd.read_csv(target)
    # Force every sc_gid to a single value; areas remain split A1/A2.
    cap["sc_gid"] = "DUPLICATE_PLANT"
    cap.to_csv(target, index=False)

    with pytest.raises(ValueError, match="globally unique"):
        load_data(str(folder))
