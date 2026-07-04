"""Tests for infrasys System parametric helpers."""

from __future__ import annotations

import pandas as pd
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


def _system():
    """Build a compact infrasys System fixture."""
    return load_system_from_data(load_data("Data/no_exchange_run_of_river"))


def test_apply_scalar_sweep_to_system_returns_new_mutated_system():
    """Scalar helper should not mutate the source system backing data."""
    system = _system()
    original_value = float(system_to_data_dict(system)["scalars"].loc["GenMix_Target", "Value"])

    mutated = apply_scalar_sweep_to_system(system, "GenMix_Target", 0.91)

    assert mutated is not system
    assert float(system_to_data_dict(mutated)["scalars"].loc["GenMix_Target", "Value"]) == pytest.approx(0.91)
    assert float(system_to_data_dict(system)["scalars"].loc["GenMix_Target", "Value"]) == pytest.approx(original_value)


def test_apply_time_series_sweep_to_system_returns_new_mutated_system():
    """Time-series helper should scale copied source data only."""
    system = _system()
    original_load = system_to_data_dict(system)["load_data"]["Load"].copy()

    mutated = apply_time_series_sweep_to_system(system, "load_data", 1.1)

    pd.testing.assert_series_equal(
        system_to_data_dict(mutated)["load_data"]["Load"],
        original_load * 1.1,
        check_names=False,
    )
    pd.testing.assert_series_equal(system_to_data_dict(system)["load_data"]["Load"], original_load)


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

    add_parametric_results_to_system(system, study, results, run_id="param-run")

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

    add_parametric_results_to_system(system, study, [OptimizationResults(total_cost=1.0)], run_id="run-a")
    add_parametric_results_to_system(system, study, [OptimizationResults(total_cost=2.0)], run_id="run-b")

    assert len(query_result_attributes(system, run_id="run-a", attribute_type=SDOMScenarioMetadata)) == 1
    assert len(query_result_attributes(system, run_id="run-b", attribute_type=SDOMScenarioMetadata)) == 1


def test_add_parametric_results_to_system_rejects_metadata_mismatch():
    """Parametric result attachment should require aligned metadata."""
    system = _system()
    study = SystemParametricStudy(system, solver_config={})

    with pytest.raises(ValueError, match="case metadata length must match results length"):
        add_parametric_results_to_system(system, study, [OptimizationResults()], run_id="bad-run")
