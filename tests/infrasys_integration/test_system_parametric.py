"""Tests for infrasys System parametric helpers."""

from __future__ import annotations

import copy
import pickle

import pandas as pd
import pyomo.environ as pyo
import pytest

infrasys = pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from sdom import load_data  # noqa: E402
from sdom.infrasys_integration.make_system import load_system_from_data, system_to_data_dict  # noqa: E402
from sdom.infrasys_integration.models import SDOMScenarioMetadata  # noqa: E402
from sdom.infrasys_integration.parametric import (  # noqa: E402
    SystemParametricStudy,
    add_parametric_results_to_system,
    apply_scalar_sweep_to_system,
    apply_time_series_sweep_to_system,
)
from sdom.infrasys_integration.results import query_result_attributes  # noqa: E402
from sdom.results import OptimizationResults  # noqa: E402
from sdom.optimization_main import get_default_solver_config_dict  # noqa: E402


N_HOURS = 24
GENMIX_TARGETS = [0.5, 1.0]
PRD_2_4_COLUMNS = [
    "line_id",
    "from_area",
    "to_area",
    "hour",
    "flow_signed_MW",
    "flow_FT_MW",
    "flow_TF_MW",
    "cap_FT_MW",
    "cap_TF_MW",
    "utilization_FT",
    "utilization_TF",
]


def _system():
    """Build a compact infrasys System fixture."""
    return load_system_from_data(load_data("Data/no_exchange_run_of_river"))


def _zonal_system():
    """Build the canonical two-area infrasys System fixture."""
    return load_system_from_data(load_data("Data/zonal_test"))


def _highs_available() -> bool:
    """Return whether either supported HiGHS interface is available."""
    for name in ("appsi_highs", "highs"):
        try:
            solver = pyo.SolverFactory(name)
            if solver is not None and solver.available(exception_flag=False):
                return True
        except Exception:
            continue
    return False


@pytest.fixture(scope="module")
def zonal_system_study_run():
    """Run a System-backed zonal parametric study once for module tests."""
    if not _highs_available():
        pytest.skip("HiGHS solver not available")

    system = _zonal_system()
    source_data = system_to_data_dict(system)
    source_scalars_before = source_data["scalars"].copy(deep=True)
    source_per_area_demand_before = {
        area_id: frame.copy(deep=True)
        for area_id, frame in source_data["per_area_demand"].items()
    }
    solver_config = get_default_solver_config_dict(solver_name="highs", executable_path="")
    solver_config["solve_keywords"].update(
        tee=False,
        report_timing=False,
        keepfiles=False,
    )
    study = SystemParametricStudy(
        system,
        solver_config=solver_config,
        n_hours=N_HOURS,
        n_cores=2,
    )
    study.add_genmix_sweep(GENMIX_TARGETS)

    return {
        "study": study,
        "results": study.run(),
        "source_data": source_data,
        "source_scalars_before": source_scalars_before,
        "source_per_area_demand_before": source_per_area_demand_before,
    }


def test_apply_scalar_sweep_to_system_returns_new_mutated_system():
    """Scalar helper should not mutate the source system backing data."""
    system = _system()
    original_value = float(system_to_data_dict(system)["scalars"].loc["GenMix_Target", "Value"])

    mutated = apply_scalar_sweep_to_system(system, parameter_name="GenMix_Target", value=0.91)

    assert mutated is not system
    assert float(system_to_data_dict(mutated)["scalars"].loc["GenMix_Target", "Value"]) == pytest.approx(0.91)
    assert float(system_to_data_dict(system)["scalars"].loc["GenMix_Target", "Value"]) == pytest.approx(original_value)


def test_apply_time_series_sweep_to_system_returns_new_mutated_system():
    """Time-series helper should scale copied source data only."""
    system = _system()
    original_load = system_to_data_dict(system)["load_data"]["Load"].copy()

    mutated = apply_time_series_sweep_to_system(system, ts_key="load_data", factor=1.1)

    pd.testing.assert_series_equal(
        system_to_data_dict(mutated)["load_data"]["Load"],
        original_load * 1.1,
        check_names=False,
    )
    pd.testing.assert_series_equal(system_to_data_dict(system)["load_data"]["Load"], original_load)


def test_apply_time_series_sweep_to_system_scales_zonal_load_views():
    """Time-series helper should scale zonal source and modeled area demand."""
    system = _zonal_system()
    original_data = system_to_data_dict(system)
    original_source = original_data["load_data"].copy()
    original_loads = {
        area_id: frame["Load"].copy()
        for area_id, frame in original_data["per_area_demand"].items()
    }

    mutated_data = system_to_data_dict(
        apply_time_series_sweep_to_system(system, ts_key="load_data", factor=1.1)
    )

    for area_id, original_load in original_loads.items():
        pd.testing.assert_series_equal(
            mutated_data["per_area_demand"][area_id]["Load"],
            original_load * 1.1,
            check_names=False,
        )
    pd.testing.assert_frame_equal(
        mutated_data["load_data"],
        original_source.assign(
            **{
                column: original_source[column] * 1.1
                for column in original_source.columns
                if column.startswith("Load@")
            }
        ),
    )
    assert list(mutated_data["load_data"].columns) == ["*Hour", "Load@A1@", "Load@A2@"]


def test_system_parametric_study_runs_zonal_cases_optimally(zonal_system_study_run):
    """System-backed zonal parametric cases should solve end-to-end."""
    results = zonal_system_study_run["results"]

    assert len(results) == len(GENMIX_TARGETS)
    for index, result in enumerate(results):
        assert result.is_optimal, (
            f"scenario {index} (GenMix_Target={GENMIX_TARGETS[index]}) failed: "
            f"solver_status={result.solver_status}, termination={result.termination_condition}"
        )


def test_system_parametric_study_results_are_zonal(zonal_system_study_run):
    """System-backed cases should retain zonal topology metadata."""
    for result in zonal_system_study_run["results"]:
        assert result.is_zonal is True
        assert set(result.areas) == {"A1", "A2"}
        assert {line["line_id"] for line in result.lines} == {"L_A1_A2"}


def test_system_parametric_study_collects_interregional_exchanges(zonal_system_study_run):
    """System-backed cases should collect the documented line-flow schema."""
    for result in zonal_system_study_run["results"]:
        exchanges = result.interregional_exchanges_df
        assert isinstance(exchanges, pd.DataFrame)
        assert not exchanges.empty
        assert list(exchanges.columns) == PRD_2_4_COLUMNS
        assert len(exchanges) == N_HOURS


def test_system_parametric_study_zonal_sweep_changes_objective(zonal_system_study_run):
    """System-backed GenMix sweep should produce distinct finite objectives."""
    costs = [result.total_cost for result in zonal_system_study_run["results"]]

    for cost in costs:
        assert cost is not None
        assert cost > 0
        assert cost == cost
        assert cost < float("inf")
    assert abs(costs[0] - costs[1]) > 1.0


def test_system_parametric_study_preserves_source_data(zonal_system_study_run):
    """System-backed study execution should not mutate retained source data."""
    source_data = zonal_system_study_run["source_data"]
    pd.testing.assert_frame_equal(
        source_data["scalars"],
        zonal_system_study_run["source_scalars_before"],
    )
    for area_id, frame_before in zonal_system_study_run["source_per_area_demand_before"].items():
        pd.testing.assert_frame_equal(source_data["per_area_demand"][area_id], frame_before)


def test_system_parametric_study_source_data_is_pickleable(zonal_system_study_run):
    """System-backed zonal source data should support worker serialization."""
    source_data = zonal_system_study_run["source_data"]
    restored = pickle.loads(pickle.dumps(source_data))
    deep_copy = copy.deepcopy(source_data)

    for data in (restored, deep_copy):
        assert set(data["per_area_demand"]) == {"A1", "A2"}
        for area_id in ("A1", "A2"):
            pd.testing.assert_frame_equal(
                data["per_area_demand"][area_id],
                source_data["per_area_demand"][area_id],
            )


def test_system_parametric_study_builds_genmix_cases():
    """SystemParametricStudy should delegate GenMix sweeps to ParametricStudy."""
    study = SystemParametricStudy(_system(), solver_config={}, n_hours=1, n_cores=1)

    study.add_genmix_sweep([0.8, 1.0])
    case_dicts = study._study._build_case_dicts()

    assert [case["case_index"] for case in case_dicts] == [0, 1]
    assert [case["scalar_mutations"][0] for case in case_dicts] == [
        ("scalars", "GenMix_Target", 0.8),
        ("scalars", "GenMix_Target", 1.0),
    ]


def test_add_parametric_results_to_system_attaches_all_case_metadata():
    """Parametric results should attach multiple cases under one run ID."""
    system = _system()
    study = SystemParametricStudy(system, solver_config={})
    study._study._case_metadata = [
        {"case_name": "GenMix_Target=0.8", "case_index": 0, "GenMix_Target": 0.8},
        {"case_name": "GenMix_Target=1.0", "case_index": 1, "GenMix_Target": 1.0},
    ]
    results = [
        OptimizationResults(total_cost=1.0, termination_condition="optimal"),
        OptimizationResults(total_cost=2.0, termination_condition="optimal"),
    ]

    add_parametric_results_to_system(system, study, results=results, run_id="param-run")

    metadata_attrs = sorted(
        query_result_attributes(system, run_id="param-run", attribute_type=SDOMScenarioMetadata),
        key=lambda attr: attr.metadata["case_index"],
    )
    assert [attr.case_name for attr in metadata_attrs] == ["GenMix_Target=0.8", "GenMix_Target=1.0"]
    assert [attr.scenario_name for attr in metadata_attrs] == ["param-run:0", "param-run:1"]
    assert metadata_attrs[0].metadata == {
        "parametric_run_id": "param-run",
        "scenario_id": "param-run:0",
        "case_name": "GenMix_Target=0.8",
        "case_index": 0,
        "sweep_values": {"GenMix_Target": 0.8},
    }


def test_add_parametric_results_to_system_preserves_multiple_runs():
    """Distinct parametric run IDs should coexist on one System."""
    system = _system()
    study = SystemParametricStudy(system, solver_config={})
    study._study._case_metadata = [{"case_name": "case-a", "case_index": 0, "GenMix_Target": 0.8}]

    add_parametric_results_to_system(system, study, results=[OptimizationResults(total_cost=1.0)], run_id="run-a")
    add_parametric_results_to_system(system, study, results=[OptimizationResults(total_cost=2.0)], run_id="run-b")

    assert len(query_result_attributes(system, run_id="run-a", attribute_type=SDOMScenarioMetadata)) == 1
    assert len(query_result_attributes(system, run_id="run-b", attribute_type=SDOMScenarioMetadata)) == 1


def test_add_parametric_results_to_system_rejects_metadata_mismatch():
    """Parametric result attachment should require aligned metadata."""
    system = _system()
    study = SystemParametricStudy(system, solver_config={})

    with pytest.raises(ValueError, match="case metadata length must match results length"):
        add_parametric_results_to_system(system, study, results=[OptimizationResults()], run_id="bad-run")
