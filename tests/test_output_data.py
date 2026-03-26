#include tests for csv outputs
import logging
import os
import shutil
import tempfile

import pandas as pd
import pytest

from sdom import load_data
from sdom import run_solver, initialize_model, export_results, get_default_solver_config_dict

from constants_test import REL_PATH_DATA_RUN_OF_RIVER_TEST

def test_output_files_creation_case_no_resiliency():

    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_RUN_OF_RIVER_TEST)
    test_data_path = os.path.abspath(test_data_path)
    
    data = load_data( test_data_path )

    model = initialize_model( data, n_hours = 24, with_resilience_constraints = False )

    #solver_dict = get_default_solver_config_dict(solver_name="cbc", executable_path=".\\Solver\\bin\\cbc.exe")
    solver_dict = get_default_solver_config_dict(solver_name="highs", executable_path="")
    results = run_solver( model, solver_dict )

    case_name = 'test_data'
    export_results(results, case_name)
    
    files_names = ["OutputGeneration_" + case_name, "OutputThermalGeneration_" + case_name, "OutputStorage_" + case_name, "OutputSummary_" + case_name, "OutputInstalledPowerPlants_" + case_name]
    for file_name in files_names:
        assert os.path.exists(os.path.join('./results_pyomo/', f"{file_name}.csv"))

    #cleanup
    for file_name in files_names:
        os.remove(os.path.join('./results_pyomo/', f"{file_name}.csv"))

# =============================================================================
# export_results → _export_from_results_object
# =============================================================================

@pytest.fixture(scope="module")
def _solved_run_of_river():
    """Solve a 24-hour run-of-river model and return (model, results)."""
    test_data_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_RUN_OF_RIVER_TEST)
    )
    data = load_data(test_data_path)
    model = initialize_model(data, n_hours=24, with_resilience_constraints=False)
    solver_dict = get_default_solver_config_dict(solver_name="highs", executable_path="")
    results = run_solver(model, solver_dict)
    return model, results


def test_export_results_from_results_object_creates_files(_solved_run_of_river):
    """export_results with OptimizationResults must write all expected CSV files."""
    _, results = _solved_run_of_river
    tmp_dir = tempfile.mkdtemp()
    try:
        case_name = "test_io_manager"
        export_results(results, case_name, tmp_dir + os.sep)

        for stem in (
            f"OutputGeneration_{case_name}",
            f"OutputStorage_{case_name}",
            f"OutputSummary_{case_name}",
            f"OutputThermalGeneration_{case_name}",
            f"OutputInstalledPowerPlants_{case_name}",
        ):
            path = os.path.join(tmp_dir, f"{stem}.csv")
            assert os.path.exists(path), f"{stem}.csv not created"
            assert os.path.getsize(path) > 0, f"{stem}.csv is empty"
    finally:
        shutil.rmtree(tmp_dir)


def test_export_results_summary_has_expected_columns(_solved_run_of_river):
    """OutputSummary must contain Metric, Technology, Optimal Value, and Unit columns."""
    _, results = _solved_run_of_river
    tmp_dir = tempfile.mkdtemp()
    try:
        case_name = "test_summary_cols"
        export_results(results, case_name, tmp_dir + os.sep)

        summary_path = os.path.join(tmp_dir, f"OutputSummary_{case_name}.csv")
        df = pd.read_csv(summary_path)
        for col in ("Metric", "Technology", "Optimal Value", "Unit"):
            assert col in df.columns, f"Column '{col}' missing from OutputSummary"
    finally:
        shutil.rmtree(tmp_dir)


# =============================================================================
# export_results → _export_from_model_legacy  (deprecated path)
# =============================================================================

def test_export_from_model_legacy_creates_files(_solved_run_of_river):
    """Passing a Pyomo model to export_results must trigger the legacy path and write CSVs."""
    model, _ = _solved_run_of_river
    tmp_dir = tempfile.mkdtemp()
    try:
        case_name = "test_legacy"
        # Passing the raw model (not OptimizationResults) triggers _export_from_model_legacy
        export_results(model, case_name, tmp_dir + os.sep)

        for stem in (
            f"OutputGeneration_{case_name}",
            f"OutputStorage_{case_name}",
            f"OutputSummary_{case_name}",
        ):
            path = os.path.join(tmp_dir, f"{stem}.csv")
            assert os.path.exists(path), f"{stem}.csv not created (legacy path)"
            assert os.path.getsize(path) > 0, f"{stem}.csv is empty (legacy path)"
    finally:
        shutil.rmtree(tmp_dir)


def test_export_from_model_legacy_uses_logging_warning(_solved_run_of_river, caplog):
    """export_results with a raw model must log a deprecation warning."""
    model, _ = _solved_run_of_river
    tmp_dir = tempfile.mkdtemp()
    try:
        with caplog.at_level(logging.WARNING, logger="sdom"):
            export_results(model, "warn_check", tmp_dir + os.sep)
        assert any("deprecated" in record.message.lower() for record in caplog.records), (
            "Expected a deprecation warning to be logged when passing a raw model"
        )
    finally:
        shutil.rmtree(tmp_dir)
