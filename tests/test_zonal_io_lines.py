"""Tests for the zonal topology loaders (commit #5).

Covers:

- ``_load_interconnections`` happy path and validation rules
  (duplicate ``line_id``, duplicate (from, to) pair, self-loop,
  unknown area FK).
- ``_load_line_capacities`` happy path and validation rules
  (column-set mismatch with ``interconnections.csv``, wrong row count,
  negative values).
- Wiring through ``load_data``: ``data["lines"]``, ``data["line_cap_ft"]``,
  ``data["line_cap_tf"]`` populated from ``Data/zonal_test/`` and empty for
  legacy folders.
- Conditional ERROR when ``Network=AreaTransportationModelNetwork`` is set
  but the topology files are missing.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from sdom import load_data


_LEGACY_FOLDER = "Data/no_exchange_run_of_river"
_ZONAL_FIXTURE = "Data/zonal_test"


def _copy_fixture_to(tmp_path: Path) -> Path:
    """Copy the canonical zonal fixture into ``tmp_path/data``."""
    dst = tmp_path / "data"
    shutil.copytree(_ZONAL_FIXTURE, dst)
    return dst


# ---------------------------------------------------------------------------
# Happy path — Data/zonal_test/
# ---------------------------------------------------------------------------


def test_lines_loaded_as_list_of_dicts():
    data = load_data(_ZONAL_FIXTURE)
    assert isinstance(data["lines"], list)
    assert len(data["lines"]) == 1
    assert data["lines"][0] == {
        "line_id": "L_A1_A2",
        "from_area": "A1",
        "to_area": "A2",
    }


def test_line_cap_ft_shape_and_values():
    data = load_data(_ZONAL_FIXTURE)
    cap = data["line_cap_ft"]
    assert isinstance(cap, pd.DataFrame)
    assert cap.shape == (8760, 1)
    assert list(cap.columns) == ["L_A1_A2"]
    assert (cap["L_A1_A2"] == 500.0).all()


def test_line_cap_tf_shape_and_values():
    data = load_data(_ZONAL_FIXTURE)
    cap = data["line_cap_tf"]
    assert isinstance(cap, pd.DataFrame)
    assert cap.shape == (8760, 1)
    assert list(cap.columns) == ["L_A1_A2"]
    assert (cap["L_A1_A2"] == 500.0).all()


def test_legacy_folder_has_no_lines_and_empty_caps():
    data = load_data(_LEGACY_FOLDER)
    assert data["lines"] == []
    assert isinstance(data["line_cap_ft"], pd.DataFrame)
    assert isinstance(data["line_cap_tf"], pd.DataFrame)
    assert data["line_cap_ft"].empty
    assert data["line_cap_tf"].empty


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_duplicate_line_id_raises(tmp_path):
    folder = _copy_fixture_to(tmp_path)
    # Add a second row that re-uses the same line_id but with a different pair.
    pd.DataFrame(
        [
            ["L_A1_A2", "A1", "A2"],
            ["L_A1_A2", "A2", "A1"],
        ],
        columns=["line_id", "from_area", "to_area"],
    ).to_csv(folder / "interconnections.csv", index=False)

    with pytest.raises(ValueError, match="duplicate line_id"):
        load_data(str(folder))


def test_unknown_from_area_raises(tmp_path):
    folder = _copy_fixture_to(tmp_path)
    pd.DataFrame(
        [["L_X", "GHOST", "A2"]],
        columns=["line_id", "from_area", "to_area"],
    ).to_csv(folder / "interconnections.csv", index=False)

    with pytest.raises(ValueError, match="unknown area_id"):
        load_data(str(folder))


def test_self_loop_raises(tmp_path):
    folder = _copy_fixture_to(tmp_path)
    pd.DataFrame(
        [["L_A1_A1", "A1", "A1"]],
        columns=["line_id", "from_area", "to_area"],
    ).to_csv(folder / "interconnections.csv", index=False)

    with pytest.raises(ValueError, match="self-loop"):
        load_data(str(folder))


def test_line_cap_ft_column_mismatch_raises(tmp_path):
    folder = _copy_fixture_to(tmp_path)
    cap = pd.read_csv(folder / "LineCap_FT.csv")
    # Rename the only line column so it no longer matches the lines set.
    cap = cap.rename(columns={"L_A1_A2": "L_OTHER"})
    cap.to_csv(folder / "LineCap_FT.csv", index=False)

    with pytest.raises(ValueError, match="LineCap_FT.csv"):
        load_data(str(folder))


def test_line_cap_ft_wrong_row_count_raises(tmp_path):
    folder = _copy_fixture_to(tmp_path)
    cap = pd.read_csv(folder / "LineCap_FT.csv")
    cap.head(8000).to_csv(folder / "LineCap_FT.csv", index=False)

    with pytest.raises(ValueError, match="8760 hourly rows"):
        load_data(str(folder))


def test_negative_value_in_line_cap_tf_raises(tmp_path):
    folder = _copy_fixture_to(tmp_path)
    cap = pd.read_csv(folder / "LineCap_TF.csv")
    cap.loc[42, "L_A1_A2"] = -1.0
    cap.to_csv(folder / "LineCap_TF.csv", index=False)

    with pytest.raises(ValueError, match="non-negative"):
        load_data(str(folder))


def test_at_formulation_missing_interconnections_raises(tmp_path):
    """``AreaTransportationModelNetwork`` without topology files is an ERROR."""
    folder = _copy_fixture_to(tmp_path)
    # Flip Network to AT and remove interconnections.csv.
    formulations = pd.read_csv(folder / "formulations.csv")
    formulations.loc[
        formulations["Component"].str.lower() == "network", "Formulation"
    ] = "AreaTransportationModelNetwork"
    formulations.to_csv(folder / "formulations.csv", index=False)
    (folder / "interconnections.csv").unlink()

    with pytest.raises(ValueError, match="AreaTransportationModelNetwork"):
        load_data(str(folder))


def test_at_formulation_missing_line_cap_ft_raises(tmp_path):
    """Topology present but LineCap_FT.csv missing → ERROR under AT."""
    folder = _copy_fixture_to(tmp_path)
    formulations = pd.read_csv(folder / "formulations.csv")
    formulations.loc[
        formulations["Component"].str.lower() == "network", "Formulation"
    ] = "AreaTransportationModelNetwork"
    formulations.to_csv(folder / "formulations.csv", index=False)
    (folder / "LineCap_FT.csv").unlink()

    with pytest.raises(ValueError, match="LineCap_FT.csv"):
        load_data(str(folder))
