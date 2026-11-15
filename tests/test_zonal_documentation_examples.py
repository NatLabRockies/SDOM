"""Test preparation and safe publication of the zonal documentation examples."""

import json
import math
import re
import runpy
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from PIL import Image

from sdom import OptimizationResults, initialize_model, load_data

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = runpy.run_path(str(ROOT / "scripts" / "generate_zonal_documentation_examples.py"))
prepare_zonal_inputs = EXAMPLE["prepare_zonal_inputs"]
publish_examples = EXAMPLE["publish_examples"]


def test_example_inputs_match_daily_hydro_setup_without_changing_source(tmp_path):
    source = ROOT / "Data" / "zonal_test"
    original_formulations = (source / "formulations.csv").read_bytes()
    destination = prepare_zonal_inputs(source, tmp_path / "inputs")
    data = load_data(str(destination))
    model = initialize_model(data, n_hours=168)

    assert (source / "formulations.csv").read_bytes() == original_formulations
    assert not (source / "lahy_max_hourly.csv").exists()
    assert not (source / "lahy_min_hourly.csv").exists()
    hydro = pd.read_csv(destination / "lahy_hourly.csv")
    maximum = pd.read_csv(destination / "lahy_max_hourly.csv")
    minimum = pd.read_csv(destination / "lahy_min_hourly.csv")
    for column in hydro.columns:
        if column.startswith("LargeHydro@"):
            pd.testing.assert_series_equal(
                maximum[column.replace("LargeHydro", "LargeHydro_Max", 1)],
                hydro[column],
                check_names=False,
            )
            assert (minimum[column.replace("LargeHydro", "LargeHydro_Max", 1)] == 0).all()
    for area in model.A:
        assert len(model.area[area].hydro.budget_constraint) == 7
        assert all(constraint.equality for constraint in model.area[area].hydro.budget_constraint.values())


def test_example_publication_rejects_failed_solves_without_writing_assets(tmp_path):
    study = SimpleNamespace(
        output_dir=str(tmp_path / "outputs"),
        case_metadata=[{"case_name": "failed_case"}],
    )
    result = OptimizationResults(termination_condition="infeasible")
    with pytest.raises(RuntimeError, match=r"failed_case.*infeasible"):
        publish_examples(study, [result], assets_dir=tmp_path / "assets")
    assert not (tmp_path / "assets").exists()


def test_example_missing_plot_does_not_overwrite_existing_assets(tmp_path):
    study = SimpleNamespace(
        output_dir=str(tmp_path / "outputs"),
        case_metadata=[
            {
                "case_name": "base",
                "GenMix_Target": 1.0,
                "P_Capex": 1.0,
                "load_data": 1.0,
            }
        ],
    )
    plots = tmp_path / "outputs" / "base" / "plots"
    plots.mkdir(parents=True)
    (plots / "capacity_donut.png").write_bytes(b"new")
    target = tmp_path / "assets" / "case_plots"
    target.mkdir(parents=True)
    (target / "capacity_donut.png").write_bytes(b"original")

    with pytest.raises(FileNotFoundError, match="plot"):
        publish_examples(
            study,
            [OptimizationResults(termination_condition="optimal")],
            assets_dir=tmp_path / "assets",
        )
    assert (target / "capacity_donut.png").read_bytes() == b"original"
    assert not (tmp_path / "assets" / "provenance.json").exists()


def test_published_zonal_example_images_and_results_match_documentation():
    assets = ROOT / "docs" / "source" / "_static" / "parametric_example"
    provenance = json.loads((assets / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["n_hours"] == 168
    cases = provenance["cases"]
    assert len(cases) == provenance["case_count"] == 12
    assert all(
        case["termination_condition"] == "optimal"
        and math.isfinite(case["total_cost_USD"])
        and case["total_cost_USD"] > 0
        for case in cases
    )
    assert all(provenance["base_case"][key] == 1.0 for key in ("GenMix_Target", "P_Capex", "load_data"))
    documents = [
        ROOT / "README.md",
        ROOT / "docs" / "source" / "user_guide" / "running_and_outputs.md",
        ROOT / "docs" / "source" / "user_guide" / "parametric_analysis.md",
    ]
    for document in documents:
        targets = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", document.read_text(encoding="utf-8"))
        example_images = [target for target in targets if "_static/parametric_example/" in target]
        assert example_images
        for target in example_images:
            image = (document.parent / target).resolve()
            assert image.is_file(), f"Missing example image linked from {document.name}: {target}"
            with Image.open(image) as png:
                png.verify()
