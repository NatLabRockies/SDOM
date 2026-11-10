from __future__ import annotations

from pathlib import Path

import pyomo.environ as pyo
import pytest
from pyomo.opt import SolverResults, SolverStatus, TerminationCondition

import sdom.optimization_main as optimization_main
from sdom import export_results, initialize_model, load_data, run_solver
from sdom.results import collect_results_from_model
from sdom.results.summary import _build_summary_dataframe, _build_zonal_summary_dataframe

ROOT = Path(__file__).resolve().parents[2]
COLLECTION_CASES = [
    pytest.param(("no_exchange_run_of_river", 8760), id="copperplate-annual", marks=pytest.mark.bench_deep),
    pytest.param(
        ("exchange_hydro_daily_budget_multiple_balancing_p95", 8760),
        id="copperplate-exchanges-annual",
        marks=pytest.mark.bench_deep,
    ),
    pytest.param(("zonal_test", 8760), id="zonal-annual", marks=pytest.mark.bench_deep),
]


@pytest.mark.parametrize(
    "scenario",
    ["no_exchange_run_of_river", "exchange_hydro_daily_budget_multiple_balancing_p95", "zonal_test"],
)
def test_collection_fixture_does_not_solve(monkeypatch, scenario):
    """Keep fixture preparation solver-free and avoid claiming optimality."""

    def reject_solver(*args, **kwargs):
        raise AssertionError("Collection benchmark fixtures must not invoke a solver")

    monkeypatch.setattr(pyo, "SolverFactory", reject_solver)
    monkeypatch.setattr(optimization_main, "SolverFactory", reject_solver)
    model, solver_result, results = _build_collection_case(scenario, n_hours=24)

    assert len(model.h) == 24
    assert str(solver_result.solver.termination_condition) == "unknown"
    assert not results.is_optimal
    assert results.total_cost == pytest.approx(pyo.value(model.Obj))
    assert results.generation_df["Hour"].nunique() == 24
    assert results.summary_df.columns.tolist() == ["Metric", "Technology", "Run", "Optimal Value", "Unit"]
    assert not results.summary_df["Optimal Value"].isna().any()
    hosts = [model.area[area] for area in model.A] if results.is_zonal else [model]
    for host in hosts:
        for variable in host.component_data_objects(pyo.Var):
            assert variable.value is not None
        if hasattr(host.imports, "variable"):
            area_summary = results.area_summary_df[host.index()] if results.is_zonal else results.summary_df
            imports = area_summary.loc[
                (area_summary["Metric"] == "Total Imports/Exports") & (area_summary["Technology"] == "Imports"),
                "Optimal Value",
            ].item()
            assert imports == pytest.approx(sum(pyo.value(host.imports.variable[h]) for h in host.h))


def _build_collection_case(scenario: str, *, n_hours: int = 8760):
    """Prepare real-data models with synthetic values, without solving.

    Parameters
    ----------
    scenario : str
        Scenario folder under Data.
    n_hours : int, optional
        Model horizon, defaulting to 8760 for the collection benchmarks.

    Returns
    -------
    tuple
        Initialized model, unknown-status solver metadata, and reference
        collection. Assigned values do not represent a feasible or optimal
        solution; only hydro-budget dispatch is matched to its input profile
        to satisfy the collector's explicit budget validation.
    """
    data = load_data(str(ROOT / "Data" / scenario))
    model = initialize_model(data, n_hours=n_hours)
    for variable in model.component_data_objects(pyo.Var):
        lower, upper = variable.bounds
        value = max(1.0, lower) if lower is not None else 1.0
        if upper is not None:
            value = min(value, upper)
        variable.set_value(value)
    hosts = [model.area[area] for area in model.A] if hasattr(model, "A") else [model]
    for host in hosts:
        if hasattr(host.hydro, "budget_constraint"):
            for hour in host.h:
                host.hydro.generation[hour].set_value(pyo.value(host.hydro.ts_parameter[hour]))
    solver_result = SolverResults()
    solver_result.solver.status = SolverStatus.unknown
    solver_result.solver.termination_condition = TerminationCondition.unknown
    results = collect_results_from_model(model, solver_result, case_name="benchmark")
    assert not results.is_optimal
    return model, solver_result, results


@pytest.fixture(scope="module")
def collection_case(request):
    """Initialize annual dispatch outside timing, without invoking any solver."""
    scenario, n_hours = request.param
    case = _build_collection_case(scenario, n_hours=n_hours)
    assert len(case[0].h) == 8760
    return case


@pytest.mark.parametrize("collection_case", COLLECTION_CASES, indirect=True)
def test_bench_collect_results(benchmark, collection_case):
    """Benchmark collection only, excluding solving, pricing solves, and CSV I/O."""
    model, solver_result, reference = collection_case
    hosts = [model.area[area] for area in model.A] if reference.is_zonal else [model]
    benchmark.extra_info.update(
        {
            "hours": len(model.h),
            "fixture": "Synthetic initialized dispatch; no solver; not a feasible or optimal solution",
            "areas": len(hosts),
            "storage_technologies": sum(len(host.storage.j) for host in hosts),
            "thermal_plants": sum(len(host.thermal.plants_set) for host in hosts),
            "summary": reference.summary_df.to_dict("split"),
            "summary_dtypes": reference.summary_df.dtypes.astype(str).to_dict(),
            "area_summaries": {
                area: frame.to_dict("split") for area, frame in reference.area_summary_df.items()
            },
            "area_summary_dtypes": {
                area: frame.dtypes.astype(str).to_dict() for area, frame in reference.area_summary_df.items()
            },
        }
    )
    results = benchmark(collect_results_from_model, model, solver_result, case_name="benchmark")
    assert results.total_cost == pytest.approx(reference.total_cost)
    assert len(results.generation_df) == len(reference.generation_df)
    assert len(results.summary_df) == len(reference.summary_df)


@pytest.mark.parametrize("collection_case", COLLECTION_CASES, indirect=True)
def test_bench_build_summary(benchmark, collection_case):
    """Benchmark copperplate or aggregate zonal summary table construction."""
    model, _, results = collection_case
    if results.is_zonal:
        technologies = sorted(
            {tech for area in model.A for tech in model.area[area].storage.j}
        )
        frame = benchmark(_build_zonal_summary_dataframe, results, technologies)
    else:
        frame = benchmark(_build_summary_dataframe, model, results, list(model.storage.j))
    assert frame.columns.tolist() == ["Metric", "Technology", "Run", "Optimal Value", "Unit"]
    assert frame.iloc[0]["Optimal Value"] == pytest.approx(results.total_cost)


@pytest.mark.bench_quick
def test_bench_export_results_legacy(
    benchmark,
    tmp_path,
    legacy_data_path,
    highs_solver_config,
):
    """Benchmark CSV export for legacy optimization results."""
    data = load_data(str(legacy_data_path))
    model = initialize_model(data, n_hours=24)
    results = run_solver(model, highs_solver_config, case_name="bench_export_legacy")

    def _export():
        export_results(results, case="bench_export_legacy", output_dir=str(tmp_path / "legacy"))

    benchmark(_export)


@pytest.mark.bench_quick
def test_bench_export_results_zonal(
    benchmark,
    tmp_path,
    zonal_data_path,
    highs_solver_config,
):
    """Benchmark CSV export for zonal optimization results."""
    data = load_data(str(zonal_data_path))
    model = initialize_model(data, n_hours=24)
    results = run_solver(model, highs_solver_config, case_name="bench_export_zonal")

    def _export():
        export_results(results, case="bench_export_zonal", output_dir=str(tmp_path / "zonal"))

    benchmark(_export)
