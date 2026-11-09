"""Long-format individual thermal dispatch from real model inputs."""

import os

import numpy as np
import pandas as pd
import pytest
from pyomo.environ import Var, value
from test_hydro_curtailment_results import _collect, _reporting_data

from sdom import export_results, initialize_model
from sdom.results import _collect_thermal_generation_dataframe

THERMAL_COLUMNS = ["Hour", "Area", "Plant ID", "Generation (MW)"]


def _thermal_model(plant_count, *, zonal):
    """Assign dispatch for collector tests, without claiming system feasibility."""
    data = _reporting_data("DailyBudgetUpperBoundFormulation", zonal=zonal)
    plants = data["thermal_data"]
    data["thermal_data"] = (
        plants.groupby("area_id", sort=False).head(plant_count).copy()
        if zonal
        else plants.head(plant_count).copy()
    )
    if zonal:
        data["per_area_balancing_units"] = {
            area: frame.head(plant_count).copy()
            for area, frame in data["per_area_balancing_units"].items()
        }
    model = initialize_model(data, n_hours=1)
    for variable in model.component_data_objects(Var):
        variable.set_value(max(0.0, variable.lb or 0.0))
    hosts = [model.area[area] for area in model.A] if zonal else [model]
    for host in hosts:
        for index, plant in enumerate(host.thermal.plants_set):
            for hour in host.h:
                host.thermal.generation[hour, plant].set_value(0.0 if hour == 1 else float(index + 1))
    return model


@pytest.mark.parametrize("zonal", [False, True], ids=["copperplate", "zonal"])
@pytest.mark.parametrize("plant_count", [0, 1, 2])
def test_thermal_dispatch_has_one_dense_row_per_hour_and_owned_plant(tmp_path, plant_count, *, zonal):
    model = _thermal_model(plant_count, zonal=zonal)
    results = _collect(model)
    frame = results.get_thermal_generation_dataframe()
    assert list(frame.columns) == THERMAL_COLUMNS
    expected_areas = list(model.A) if zonal else ["copperplate"]
    assert len(frame) == len(model.h) * len(expected_areas) * plant_count
    assert not frame.isna().any().any()
    assert not frame.duplicated(["Hour", "Area", "Plant ID"]).any()
    if plant_count:
        assert set(frame["Area"]) == set(expected_areas)
        assert frame.loc[frame["Hour"] == 1, "Generation (MW)"].eq(0.0).all()
    for area in expected_areas:
        host = model.area[area] if zonal else model
        local = frame.loc[frame["Area"] == area]
        assert set(local["Plant ID"]) == {str(plant) for plant in host.thermal.plants_set}
        for row in local.to_dict("records"):
            assert row["Generation (MW)"] == value(host.thermal.generation[row["Hour"], row["Plant ID"]])
        if zonal:
            pd.testing.assert_frame_equal(
                results.area_thermal_generation_df[area],
                local.drop(columns="Area").reset_index(drop=True),
            )
    export_results(results, case="thermal", output_dir=str(tmp_path))
    path = tmp_path / "OutputThermalGeneration_thermal.csv"
    assert path.exists() == bool(plant_count)
    if plant_count:
        exported = pd.read_csv(path, dtype={"Plant ID": str})
        pd.testing.assert_frame_equal(exported, frame)
        assert exported["Generation (MW)"].sum() == pytest.approx(
            results.generation_df["All Thermal Generation (MW)"].sum()
        )


@pytest.mark.parametrize("plant_count", [1, 2])
def test_deprecated_model_export_uses_same_long_thermal_schema(tmp_path, plant_count):
    model = _thermal_model(plant_count, zonal=False)
    expected = _collect(model).get_thermal_generation_dataframe()
    export_results(model, case="legacy", output_dir=str(tmp_path) + os.sep)
    actual = pd.read_csv(tmp_path / "OutputThermalGeneration_legacy.csv", dtype={"Plant ID": str})
    pd.testing.assert_frame_equal(actual, expected)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf")])
def test_thermal_dispatch_rejects_nonfinite_extracted_values(invalid):
    model = _thermal_model(1, zonal=False)
    with pytest.raises(ValueError, match="Nonfinite thermal dispatch"):
        _collect_thermal_generation_dataframe(model, generation=np.full((len(model.h), 1), invalid))
