"""Regenerate documentation figures from the 168-hour zonal daily-hydro case.

Run ``uv run python scripts/generate_zonal_documentation_examples.py`` from
the repository root. The 12-case study writes CSVs and plots under
``results/zonal_documentation_168h`` and refreshes the published example
assets only after every case solves optimally and every required plot exists.
The canonical ``Data/zonal_test`` inputs are never modified.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from sdom import OptimizationResults, get_default_solver_config_dict, load_data
from sdom.analytic_tools import plot_parametric_results
from sdom.parametric import ParametricStudy

ROOT = Path(__file__).resolve().parents[1]
N_HOURS = 168
CASE_PLOTS = {
    "capacity_donut.png": "capacity_donut.png",
    "capacity_generation_donuts.png": "capacity_generation_donuts.png",
    "heatmap_Net_Load_(MW).png": "heatmap_net_load.png",
    "heatmap_VRE_Generation_(MW).png": "heatmap_vre_generation.png",
    **{
        filename: filename
        for filename in (
            "area_capacity_stacks_power.png",
            "line_flow_heatmap.png",
            "duration_curve_system_load.png",
            "duration_curve_system_net_load.png",
            "duration_curve_system_vre_curtailment_pct.png",
            "duration_curve_zonal_load.png",
            "duration_curve_zonal_vre_curtailment_pct.png",
            "duration_curve_zonal_marginal_prices.png",
            "duration_curve_interregional_signed_flows.png",
        )
    },
}
SENSITIVITY_PLOTS = (
    "capacity_comparison.png",
    "generation_comparison.png",
    "curtailment_absolute.png",
    "curtailment_percentage.png",
    "cost_comparison.png",
)


def prepare_zonal_inputs(source: Path, destination: Path) -> Path:
    """Copy the canonical fixture and apply the tested daily-hydro setup.

    Parameters
    ----------
    source : pathlib.Path
        Canonical zonal input directory.
    destination : pathlib.Path
        New directory for the copied inputs; must not already exist.

    Returns
    -------
    pathlib.Path
        Prepared directory with strict daily hydro budgets, profile-based
        maximum bounds, and zero minimum bounds.
    """
    shutil.copytree(source, destination)
    path = destination / "formulations.csv"
    formulations = pd.read_csv(path)
    hydro_rows = formulations["Component"] == "Hydro"
    formulations.loc[hydro_rows, "Formulation"] = "DailyBudgetFormulation"
    formulations.loc[hydro_rows, "Description"] = "Strict daily hydro budgets for the 168-hour example."
    formulations.to_csv(path, index=False)

    hydro = pd.read_csv(destination / "lahy_hourly.csv")
    columns = [column for column in hydro if column.startswith("LargeHydro@")]
    maximum = hydro[["*Hour", *columns]].rename(
        columns={column: column.replace("LargeHydro", "LargeHydro_Max", 1) for column in columns}
    )
    minimum = maximum.copy()
    minimum.loc[:, minimum.columns != "*Hour"] = 0.0
    maximum.to_csv(destination / "lahy_max_hourly.csv", index=False)
    minimum.to_csv(destination / "lahy_min_hourly.csv", index=False)
    return destination


def publish_examples(
    study: ParametricStudy,
    results: list[OptimizationResults],
    *,
    assets_dir: Path,
) -> None:
    """Publish verified figures and numeric provenance for the base case.

    Parameters
    ----------
    study : sdom.parametric.ParametricStudy
        Completed study with metadata and an output directory.
    results : list of OptimizationResults
        Results in the study's metadata order.
    assets_dir : pathlib.Path
        Documentation asset directory containing case and sensitivity plots.

    Raises
    ------
    RuntimeError
        If any case is not optimal.
    ValueError
        If metadata and results differ in length, the output directory is
        absent, or the base case is missing.
    FileNotFoundError
        If any required plot is absent; existing assets are not overwritten.
    """
    cases = list(zip(study.case_metadata, results, strict=True))
    failures = [
        f"{metadata['case_name']}: {result.termination_condition}"
        for metadata, result in cases
        if not result.is_optimal
    ]
    if failures:
        raise RuntimeError("Cannot publish unsuccessful example cases: " + "; ".join(failures))
    if study.output_dir is None:
        raise ValueError("Publishing example figures requires a study output directory.")
    baseline = [
        (metadata, result)
        for metadata, result in cases
        if all(metadata[key] == 1.0 for key in ("GenMix_Target", "P_Capex", "load_data"))
    ]
    if len(baseline) != 1:
        raise ValueError("Expected exactly one base example case with all three sweep values equal to 1.0.")
    metadata, result = baseline[0]
    output_dir = Path(study.output_dir)
    case_dir = output_dir / metadata["case_name"] / "plots"
    copies = [
        (case_dir / source, assets_dir / "case_plots" / target) for source, target in CASE_PLOTS.items()
    ]
    copies.extend(
        (output_dir / "sensitivity_plots" / filename, assets_dir / "sensitivity_plots" / filename)
        for filename in SENSITIVITY_PLOTS
    )
    for source, _ in copies:
        if not source.is_file():
            raise FileNotFoundError(f"Missing required example plot: {source}")
    for source, target in copies:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    provenance = {
        "source": "Data/zonal_test",
        "test": "tests/test_zonal_daily_hydro_budget.py",
        "hydro_formulation": "DailyBudgetFormulation",
        "n_hours": N_HOURS,
        "solver": "highs",
        "case_count": len(cases),
        "base_case": metadata,
        "base_capacity_MW": result.capacity,
        "base_storage_capacity": result.storage_capacity,
        "cases": [
            {
                **entry,
                "termination_condition": case.termination_condition,
                "total_cost_USD": case.total_cost,
                "solar_capacity_MW": case.total_cap_pv,
                "wind_capacity_MW": case.total_cap_wind,
                "thermal_capacity_MW": case.total_cap_thermal,
            }
            for entry, case in cases
        ],
    }
    (assets_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def generate_examples() -> None:
    """Solve the 12-case zonal study and regenerate the published example pack."""
    with TemporaryDirectory(prefix="sdom_zonal_example_") as temporary:
        input_dir = prepare_zonal_inputs(ROOT / "Data" / "zonal_test", Path(temporary) / "inputs")
        data = load_data(str(input_dir))
        solver = get_default_solver_config_dict(solver_name="highs", executable_path="")
        solver["solve_keywords"].update(tee=False, report_timing=False, keepfiles=False)
        study = ParametricStudy(
            base_data=data,
            solver_config=solver,
            n_hours=N_HOURS,
            output_dir=str(ROOT / "results" / "zonal_documentation_168h"),
            n_cores=3,
        )
        study.add_scalar_sweep("scalars", "GenMix_Target", [0.0, 0.8, 1.0])
        study.add_storage_factor_sweep("P_Capex", [1.0, 0.7])
        study.add_ts_sweep("load_data", [1.0, 1.4])
        results = study.run()
        if len(results) != 12 or any(not result.is_optimal for result in results):
            statuses = ", ".join(result.termination_condition for result in results)
            raise RuntimeError(f"Expected 12 optimal zonal example cases, got {len(results)}: {statuses}")
        plot_parametric_results(
            study,
            results,
            group_by=["GenMix_Target", "P_Capex"],
            hue_by="load_data",
            max_cases_per_figure=36,
            plot_per_case=True,
        )
        publish_examples(
            study, results, assets_dir=ROOT / "docs" / "source" / "_static" / "parametric_example"
        )
        print(f"Published {len(results)} optimal cases over {N_HOURS} hours. Outputs: {study.output_dir}")


if __name__ == "__main__":
    generate_examples()
